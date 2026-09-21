"""ESSCAN submission processing pipeline.

One place where an uploaded answer sheet becomes scores, shared by the
professor upload flow (`routers/uploads.py`) and the student self-upload flow
(`routers/student.py`). Before V7.9 only the professor path ran OMR/OCR at
all: a student upload just wrote files to disk and marked the row "Uploaded",
which is why student scores never appeared.

Design
------
The pipeline is split in two halves on purpose:

    run_pipeline()               pure CPU/network work, no database
    persist_result()              database writes for the pipeline's output
    process_submission_background() ties the two together and is what the
                                     upload endpoints hand to FastAPI's
                                     BackgroundTasks

The upload endpoints do only the fast part inline — save the files, lock the
submission, commit — and return immediately. run_pipeline() and
persist_result() then run in a background task, with their own database
session, after the response has already gone out. This is what lets a
professor scan one student's sheet and move straight to the next without
waiting through OCR and essay grading; the previous synchronous design made
every upload block on the full pipeline (potentially many seconds per sheet,
worse under Ollama verification), which is exactly what stopped a professor
from scanning a class back-to-back.

Pages are also processed concurrently within a single pipeline run, rather
than one after another.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from fastapi import HTTPException, UploadFile

from models.exam_question import ExamQuestion, QuestionType
from models.exam_submission import ExamSubmission, SubmissionStatus
from models.submission_answer import AnswerProcessingStatus, SubmissionAnswer
from services import essay_grader
from services import nlp_spacy
from services import sheet_layout as layout
from services.essay_grader import parse_json_list
from services.rubric import load_rubric_for_question
from services.ocr_hybrid import (
    easyocr_available,
    extract_essay_page,
    extract_text,
    ollama_available,
)
from services.omr import analyze_page as analyze_omr_page, available as omr_available
from services.runtime import map_pages
from services.scanner import prepare_scan

logger = logging.getLogger("esscan.pipeline")

# The printable answer sheet places a maximum of 2 essay answers per page.
ESSAYS_PER_PAGE = 2

# More than this many MCQs would need a second bubble page, which the current
# printable sheet does not produce.
MAX_MCQ_PER_PAGE = 60


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def essay_response_formats(essays) -> list[str]:
    """The ``expected_response_format`` of each essay question, in order."""
    return [
        str(getattr(q, "expected_response_format", "one_paragraph") or "one_paragraph")
        for q in essays
    ]


def essay_page_plan(essays) -> list[list[int]]:
    """Which essay questions appear on which printed page.

    ``essays`` is the ordered list of essay ``ExamQuestion`` rows. Delegates to
    ``sheet_layout.plan_essay_pages`` so this matches what ``exam_pdf`` printed.
    """
    return layout.plan_essay_pages(essay_response_formats(essays))


def expected_essay_pages(essays) -> int:
    """How many essay answer pages this exam prints.

    Accepts the ordered essay questions. A bare integer is still accepted for
    older callers and assumes every answer is a short one, which is the
    assumption this whole change exists to remove — pass the questions.
    """
    if isinstance(essays, int):
        return math.ceil(essays / ESSAYS_PER_PAGE) if essays else 0
    return len(essay_page_plan(essays))


def process_submission_background(
    submission_id: int,
    pages: list["PageInput"],
    exam_id: int,
    mcq_numbers: list[int],
    essay_count: int,
    has_mcq: bool,
    saved_paths: list[str],
    essay_saved_paths: list[str],
) -> None:
    """Run OMR/OCR/NLP and persist the result, entirely off the request.

    Handed to FastAPI's ``BackgroundTasks`` so the upload endpoint can return
    the moment the files are safely on disk, instead of making whoever is
    scanning wait through OCR and essay grading before they can move on to
    the next answer sheet. A class set can take several minutes of pipeline
    time in total; none of it should block the person doing the scanning.

    This function opens its own database session rather than reusing the
    request's. FastAPI closes a ``yield``-based dependency (``get_db``)
    *before* background tasks run, so the request's session would already be
    closed by the time this executes — reusing it would raise on first use.
    For the same reason, ORM objects fetched during the request (the exam,
    its questions, the submission row) are detached once that session closes
    and cannot be read here; everything needed is re-fetched fresh instead.

    Never lets an exception vanish silently: on failure the submission is
    marked ``Failed`` with the error recorded in ``processing_metadata_json``,
    so a professor sees exactly what went wrong instead of a sheet stuck
    forever in "processing".
    """
    from database import SessionLocal

    db = SessionLocal()
    try:
        submission = (
            db.query(ExamSubmission)
            .filter(ExamSubmission.submission_id == submission_id)
            .first()
        )
        if submission is None:
            logger.error(
                "Background processing: submission %s no longer exists", submission_id
            )
            return

        mcqs, essays = split_questions(db, exam_id)
        topic_hint = _build_topic_hint(essays)
        pipeline = run_pipeline(
            pages, mcq_numbers, essay_count, has_mcq,
            topic_hint=topic_hint,
            essay_plan=essay_page_plan(essays),
        )
        persist_result(
            db, submission, pipeline, mcqs, essays,
            saved_paths, essay_saved_paths,
        )
        db.commit()
    except Exception as exc:
        logger.exception(
            "Background processing failed for submission %s: %s", submission_id, exc
        )
        db.rollback()
        try:
            submission = (
                db.query(ExamSubmission)
                .filter(ExamSubmission.submission_id == submission_id)
                .first()
            )
            if submission is not None:
                submission.submission_status = SubmissionStatus.Failed
                submission.processing_metadata_json = json.dumps(
                    {
                        "error": f"{type(exc).__name__}: {exc}",
                        "stage": "background_processing",
                    },
                    ensure_ascii=False,
                )
                db.commit()
        except Exception:
            logger.exception(
                "Also failed to record the failure for submission %s", submission_id
            )
            db.rollback()
    finally:
        db.close()


def json_safe(value):
    """Convert stray numpy scalars/arrays to native Python types.

    FastAPI's encoder cannot serialize numpy.int32/float32/ndarray, so any
    left inside a returned dict turns a successful upload into a 500. This is
    a safety net around the whole OCR/OMR pipeline, not a fix for one field.
    """
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if type(value).__module__ == "numpy":
        item = getattr(value, "item", None)
        if callable(item) and getattr(value, "shape", None) == ():
            return item()
        tolist = getattr(value, "tolist", None)
        if callable(tolist):
            return tolist()
    return value


def prepare_scan_safe(data: bytes, question_count: int = 0) -> dict:
    """Normalize a page, never failing the upload if normalization can't run."""
    try:
        return prepare_scan(data, question_count=question_count)
    except Exception as exc:
        logger.warning("Scanner normalization failed, using original image: %s", exc)
        return {
            "normalized": False,
            "master_bytes": data,
            "omr_bytes": data,
            "alignment": {"alignment_method": "scanner_failed", "confidence": 0.0},
            "quality": {},
        }


MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))


async def read_upload_limited(file: UploadFile, max_mb: int | None = None) -> bytes:
    """Read an UploadFile into memory, rejecting anything unreasonably large.

    Before this, every upload endpoint called ``UploadFile.read()`` directly
    with no size check at all — a single request could exhaust memory or
    disk with an arbitrarily large file. A scanned answer-sheet photo is
    realistically a few MB; MAX_UPLOAD_MB (default 15) gives generous
    headroom above that without being unbounded. Raises 413 rather than
    silently truncating, so a legitimately-too-large photo is a clear error
    instead of a corrupted partial scan.
    """
    limit_mb = max_mb if max_mb is not None else MAX_UPLOAD_MB
    data = await file.read()
    if len(data) > limit_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=(
                f"'{file.filename or 'file'}' is {len(data) / 1024 / 1024:.1f} MB, which is "
                f"larger than the {limit_mb} MB limit per page. Use a lower camera resolution "
                "or compress the image before uploading."
            ),
        )
    return data


class PageInput:
    """One uploaded page, already read into memory."""

    __slots__ = ("kind", "index", "data", "ext", "filename")

    def __init__(self, kind: str, index: int, data: bytes, ext: str, filename: str = ""):
        self.kind = kind          # "page1" | "essay"
        self.index = index        # 0-based within its kind
        self.data = data
        self.ext = (ext or "").lower()
        self.filename = filename

    @property
    def is_pdf(self) -> bool:
        return self.ext == ".pdf"


# ---------------------------------------------------------------------------
# Stage 1: pure processing (no database)
# ---------------------------------------------------------------------------

def run_pipeline(
    pages: list[PageInput],
    mcq_numbers: list[int],
    essay_count: int,
    has_mcq: bool,
    topic_hint: str = "",
    essay_plan: list[list[int]] | None = None,
) -> dict[str, Any]:
    """Run scanner + OMR + OCR over every page, concurrently.

    ``essay_plan`` is the per-page grouping of essay questions from
    ``essay_page_plan``. When it is omitted the old uniform two-per-page
    assumption is used, which is correct only if every answer is a short one.

    Returns a plain dict; the caller writes it to the database. Never raises
    for a single bad page — a failure is recorded against that page so the
    rest of the sheet still produces a score.
    """
    started = time.monotonic()
    plan = essay_plan if essay_plan is not None else [
        list(range(i, min(i + ESSAYS_PER_PAGE, essay_count)))
        for i in range(0, essay_count, ESSAYS_PER_PAGE)
    ]
    page1 = next((p for p in pages if p.kind == "page1"), None)
    essay_inputs = sorted([p for p in pages if p.kind == "essay"], key=lambda p: p.index)

    timings: dict[str, float] = {}

    def process_page1(_: Any) -> dict[str, Any]:
        t0 = time.monotonic()
        if page1 is None or page1.is_pdf:
            return {
                "scan": None,
                "extraction": {"easyocr_text": "", "ollama_text": "", "combined_text": ""},
                "omr": None,
                "seconds": 0.0,
            }
        scan = prepare_scan_safe(page1.data, question_count=len(mcq_numbers))
        extraction = extract_text(page1.data, prepared_scan=scan)

        omr_result = None
        if mcq_numbers:
            omr_result = analyze_omr_page(
                scan.get("omr_bytes") or page1.data,
                mcq_numbers[:MAX_MCQ_PER_PAGE],
                fill_threshold=float(os.getenv("OMR_FILL_THRESHOLD", "0.24")),
                ambiguity_margin=float(os.getenv("OMR_AMBIGUITY_MARGIN", "0.055")),
                already_aligned=bool(scan.get("normalized")),
            )
        return {
            "scan": scan,
            "extraction": extraction,
            "omr": omr_result,
            "seconds": round(time.monotonic() - t0, 2),
        }

    def process_essay(page: PageInput) -> dict[str, Any]:
        t0 = time.monotonic()
        if page.is_pdf:
            return {
                "index": page.index,
                "scan": None,
                "extraction": {"answers": [], "easyocr_text": "", "ollama_text": "", "combined_text": ""},
                "seconds": 0.0,
            }
        scan = prepare_scan_safe(page.data, question_count=0)
        # How many answer boxes were printed on THIS page. A page carrying a
        # multi-paragraph answer has one full-height box; deriving the count
        # from the running total instead assumed two, and cropped a single
        # answer into two half-page slices.
        if page.index < len(plan):
            box_count = len(plan[page.index])
        else:
            box_count = max(1, min(ESSAYS_PER_PAGE, essay_count - page.index * ESSAYS_PER_PAGE))
        extraction = extract_essay_page(
            page.data,
            answer_count=max(1, min(ESSAYS_PER_PAGE, box_count)),
            has_mcq=has_mcq,
            prepared_scan=scan,
            # Only the first physical answer-sheet page carries the tall boxed
            # ID field. Without the index the cropper cannot tell page 1 of an
            # essay-only exam from page 2 and misses the top of every later
            # page by 56pt.
            page_index=page.index,
            topic_hint=topic_hint,
        )
        return {
            "index": page.index,
            "scan": scan,
            "extraction": extraction,
            "seconds": round(time.monotonic() - t0, 2),
        }

    # Page 1 and every essay page are independent. Submit them all together
    # so OpenCV work on one page overlaps the Ollama wait on another.
    tasks: list[tuple[str, Any]] = []
    if page1 is not None:
        tasks.append(("page1", None))
    tasks.extend(("essay", p) for p in essay_inputs)

    def dispatch(task):
        kind, payload = task
        return process_page1(payload) if kind == "page1" else process_essay(payload)

    outcomes = map_pages(dispatch, tasks)

    page1_result: dict[str, Any] = {
        "scan": None,
        "extraction": {"easyocr_text": "", "ollama_text": "", "combined_text": ""},
        "omr": None,
    }
    essay_results: list[dict[str, Any]] = []

    for (kind, payload), outcome in zip(tasks, outcomes):
        if isinstance(outcome, Exception):
            logger.exception("Page processing failed (%s): %s", kind, outcome)
            if kind == "page1":
                page1_result["error"] = f"{type(outcome).__name__}: {outcome}"
            else:
                essay_results.append({
                    "index": payload.index,
                    "scan": None,
                    "extraction": {"answers": [], "easyocr_text": "", "ollama_text": "", "combined_text": ""},
                    "error": f"{type(outcome).__name__}: {outcome}",
                })
            continue
        if kind == "page1":
            page1_result = outcome
            timings["page1"] = outcome.get("seconds", 0.0)
        else:
            essay_results.append(outcome)
            timings[f"essay_{outcome['index'] + 1}"] = outcome.get("seconds", 0.0)

    essay_results.sort(key=lambda r: r["index"])
    timings["total"] = round(time.monotonic() - started, 2)

    return {
        "page1": page1_result,
        "essayPages": essay_results,
        # Carried through to grade_essays so the answer-to-question mapping is
        # the same grouping that decided the crops, not a second guess at it.
        "essayPlan": plan,
        "timings": timings,
        "services": {
            "easyocr_available": easyocr_available(),
            "ollama_available": ollama_available(),
            "omr_available": omr_available(),
        },
    }


# ---------------------------------------------------------------------------
# Stage 2: persistence and scoring (database)
# ---------------------------------------------------------------------------

def _store_omr_answers(
    db: Session,
    submission: ExamSubmission,
    questions: list[ExamQuestion],
    omr_result: dict | None,
) -> None:
    if not questions or not omr_result:
        return

    by_number = {q.question_number: q for q in questions}
    for detected in omr_result.get("answers", []) or []:
        q = by_number.get(detected.get("question_number"))
        if not q:
            continue

        if detected["is_blank"]:
            status = AnswerProcessingStatus.Blank
        elif detected["is_ambiguous"]:
            status = AnswerProcessingStatus.Ambiguous
        else:
            status = AnswerProcessingStatus.Detected

        row = _get_or_create_answer(db, submission.submission_id, q.question_id)
        row.selected_option = detected["selected_option"]
        row.processing_status = status
        row.is_blank = int(detected["is_blank"])
        row.is_ambiguous = int(detected["is_ambiguous"])
        row.confidence = detected["confidence"]
        row.best_fill_ratio = detected["best_fill_ratio"]
        row.second_fill_ratio = detected["second_fill_ratio"]
        row.option_measurements = json.dumps(json_safe(detected["options"]), ensure_ascii=False)
        row.max_score = float(q.points or 0)


def _get_or_create_answer(db: Session, submission_id: int, question_id: int) -> SubmissionAnswer:
    row = db.query(SubmissionAnswer).filter(
        SubmissionAnswer.submission_id == submission_id,
        SubmissionAnswer.question_id == question_id,
    ).first()
    if not row:
        row = SubmissionAnswer(submission_id=submission_id, question_id=question_id)
        db.add(row)
        db.flush()
    return row


def _essay_texts_by_question(
    essay_results: list[dict[str, Any]],
    essays: list[ExamQuestion],
    plan: list[list[int]] | None = None,
) -> dict[int, str]:
    """Map each essay question to its transcribed answer.

    ``plan[page][box]`` is the index into ``essays`` of the question printed in
    that box, so the mapping follows the sheet that was actually printed.

    The old ``page_index * 2 + box_index`` arithmetic assumed every page held
    two answers. A ``multi_paragraph`` question takes a page to itself, so any
    exam mixing formats shifted every subsequent answer onto the wrong
    question. Nothing failed visibly: a real transcription was graded against
    a different question's answer key.
    """
    if plan is None:
        plan = essay_page_plan(essays)

    mapping: dict[int, str] = {}
    for result in essay_results:
        page_index = result["index"]
        if page_index >= len(plan):
            logger.warning(
                "Essay page %s has no place in a %s-page layout; skipping it.",
                page_index + 1, len(plan),
            )
            continue
        question_indices = plan[page_index]
        answers = (result.get("extraction") or {}).get("answers") or []
        for box_index, answer in enumerate(answers):
            if box_index >= len(question_indices):
                continue
            position = question_indices[box_index]
            if position >= len(essays):
                continue
            mapping[essays[position].question_id] = str(answer.get("answer") or "")
    return mapping


def score_mcq(db: Session, submission: ExamSubmission, mcqs: list[ExamQuestion]) -> tuple[float, float]:
    """Sum points for correctly-filled bubbles. Returns (score, max)."""
    if not mcqs:
        return 0.0, 0.0

    db.flush()
    rows = {
        row.question_id: row
        for row in db.query(SubmissionAnswer)
        .filter(SubmissionAnswer.submission_id == submission.submission_id)
        .all()
    }

    score = 0.0
    maximum = 0.0
    for q in mcqs:
        points = float(q.points or 0)
        maximum += points
        row = rows.get(q.question_id)
        if not row or row.is_blank or row.is_ambiguous:
            continue
        if not row.selected_option or not q.correct_option:
            continue
        if row.selected_option.strip().upper() == q.correct_option.strip().upper():
            score += points
            row.auto_score = points
        else:
            row.auto_score = 0.0
    return round(score, 2), round(maximum, 2)


def grade_essays(
    db: Session,
    submission: ExamSubmission,
    essays: list[ExamQuestion],
    essay_results: list[dict[str, Any]],
    plan: list[list[int]] | None = None,
) -> tuple[float, float, list[dict[str, Any]]]:
    """Run the spaCy grader over every essay answer. Returns (score, max, detail).

    An existing professor override is never overwritten by a re-scan: the AI
    score is refreshed but ``override_score`` is left alone, because losing a
    manual grade to an automatic re-run would be far worse than a stale AI
    number.
    """
    if not essays:
        return 0.0, 0.0, []

    texts = _essay_texts_by_question(essay_results, essays, plan)
    total = 0.0
    maximum = 0.0
    detail: list[dict[str, Any]] = []

    # Batch every essay answer's semantic-relevance encoding into a single
    # Sentence-BERT call instead of one call per question. This mirrors the
    # OCR-context analysis grade_answer() builds internally for the SAME
    # text (so spelling detection can tell OCR damage to a domain term apart
    # from a real mistake) — a small amount of duplicated spaCy work in
    # exchange for turning N separate SBERT forward passes into one. spaCy
    # analysis of one answer is milliseconds; the SBERT call is the actually
    # expensive part on both CPU and GPU, so batching that is what matters.
    similarity_pairs: list[tuple] = []
    for q in essays:
        text = texts.get(q.question_id, "")
        answer_key = str(getattr(q, "answer_key", "") or "")
        ocr_context = (
            [answer_key]
            + parse_json_list(getattr(q, "key_concepts", None))
            + parse_json_list(getattr(q, "keywords", None))
            + parse_json_list(getattr(q, "requirements", None))
        )
        analysis = nlp_spacy.analyze(nlp_spacy.normalize(text), ocr_context=ocr_context)
        similarity_pairs.append((analysis, answer_key))

    try:
        batched_similarities = nlp_spacy.batch_semantic_similarity(similarity_pairs)
    except Exception as exc:
        logger.warning("Batched similarity failed, essays will compute it individually: %s", exc)
        batched_similarities = [None] * len(essays)

    for q, precomputed in zip(essays, batched_similarities):
        points = float(q.points or 0)
        maximum += points
        text = texts.get(q.question_id, "")

        try:
            # The professor's rubric for THIS question drives the score:
            # question-specific first, then a legacy exam-level rubric, then
            # the documented system default.
            question_rubric = load_rubric_for_question(db, q)
            graded = essay_grader.grade_answer(
                text, q, max_points=points, rubric=question_rubric,
                precomputed_similarity=precomputed,
            )
        except Exception as exc:
            logger.exception("Essay grading failed for question %s: %s", q.question_id, exc)
            graded = {
                "score": 0.0, "maxScore": points, "percentage": 0.0, "isBlank": not text,
                "criteria": [], "analysis": {}, "semanticPending": True,
                "rubric": {"source": "error", "adjusted": False, "configured": []},
                "engine": {"nlp": "error", "similarity": "error"},
                "summary": f"Automatic grading failed: {type(exc).__name__}. Please grade manually.",
            }

        row = _get_or_create_answer(db, submission.submission_id, q.question_id)
        row.answer_text = text or None
        row.auto_score = graded["score"]
        row.max_score = points
        row.feedback_json = json.dumps(json_safe(graded), ensure_ascii=False)
        row.is_blank = int(bool(graded.get("isBlank")))
        if row.override_score is not None:
            row.processing_status = AnswerProcessingStatus.Overridden
        else:
            row.processing_status = AnswerProcessingStatus.Graded

        effective = row.override_score if row.override_score is not None else graded["score"]
        total += float(effective or 0)

        detail.append({
            "questionId": q.question_id,
            "questionNumber": q.question_number,
            "autoScore": graded["score"],
            "overrideScore": float(row.override_score) if row.override_score is not None else None,
            "maxScore": points,
            "summary": graded.get("summary"),
        })

    return round(total, 2), round(maximum, 2), detail


def recalculate_totals(db: Session, submission: ExamSubmission) -> dict[str, float]:
    """Recompute mcq/essay/final scores from the stored per-answer rows.

    Called after the pipeline runs and again after any professor override, so
    the totals always reflect the effective (override-aware) scores.
    """
    rows = (
        db.query(SubmissionAnswer, ExamQuestion)
        .join(ExamQuestion, ExamQuestion.question_id == SubmissionAnswer.question_id)
        .filter(SubmissionAnswer.submission_id == submission.submission_id)
        .all()
    )

    mcq_score = 0.0
    essay_score = 0.0
    mcq_max = 0.0
    essay_max = 0.0

    all_questions = (
        db.query(ExamQuestion).filter(ExamQuestion.exam_id == submission.exam_id).all()
    )
    for q in all_questions:
        points = float(q.points or 0)
        if q.question_type == QuestionType.MCQ:
            mcq_max += points
        else:
            essay_max += points

    for row, question in rows:
        value = row.override_score if row.override_score is not None else row.auto_score
        value = float(value or 0)
        if question.question_type == QuestionType.MCQ:
            mcq_score += value
        else:
            essay_score += value

    submission.mcq_score = round(mcq_score, 2) if mcq_max else None
    submission.essay_score = round(essay_score, 2) if essay_max else None
    submission.max_score = round(mcq_max + essay_max, 2)
    submission.final_score = round(mcq_score + essay_score, 2)

    return {
        "mcqScore": mcq_score,
        "essayScore": essay_score,
        "mcqMax": mcq_max,
        "essayMax": essay_max,
        "finalScore": mcq_score + essay_score,
        "maxScore": mcq_max + essay_max,
    }


def persist_result(
    db: Session,
    submission: ExamSubmission,
    pipeline: dict[str, Any],
    mcqs: list[ExamQuestion],
    essays: list[ExamQuestion],
    saved_paths: list[str],
    essay_saved_paths: list[str],
) -> dict[str, Any]:
    """Write pipeline output to the database and compute every score.

    ``submitted_at``, ``attempt_count``, ``uploaded_by`` and
    ``student_filename`` are NOT set here — the caller sets them the moment
    the sheet is accepted, before this function runs (now in a background
    task), so "submitted" reflects when the sheet was handed in rather than
    when grading happened to finish.
    """
    page1_result = pipeline["page1"]
    essay_results = pipeline["essayPages"]
    page1_extraction = page1_result.get("extraction") or {}
    essay_extractions = [r.get("extraction") or {} for r in essay_results]

    _store_omr_answers(db, submission, mcqs, page1_result.get("omr"))
    score_mcq(db, submission, mcqs)
    _, _, essay_detail = grade_essays(
        db, submission, essays, essay_results, pipeline.get("essayPlan")
    )

    easyocr_text = "\n".join(
        x for x in [page1_extraction.get("easyocr_text", "")]
        + [e.get("easyocr_text", "") for e in essay_extractions] if x
    )
    ollama_text = "\n".join(
        x for x in [page1_extraction.get("ollama_text", "")]
        + [e.get("ollama_text", "") for e in essay_extractions] if x
    )
    combined_text = "\n".join(
        x for x in [page1_extraction.get("combined_text", "")]
        + [e.get("combined_text", "") for e in essay_extractions] if x
    )

    now = datetime.now()
    # submitted_at, attempt_count, uploaded_by and student_filename are set by
    # the caller the moment the sheet is accepted (before this function runs
    # in the background), so "submitted" reflects when the student/professor
    # handed in the sheet rather than when grading happened to finish.
    # processed_at is the one genuinely new timestamp here: it marks when the
    # pipeline actually completed.
    submission.processed_at = now
    # Page 1 is whichever saved page is NOT an essay page. Identifying it by
    # filename is what put the essay image in this column: "_page_1." is a
    # substring of "_essay_page_1." as well, so the test matched both and
    # returned whichever happened to come first.
    essay_set = set(essay_saved_paths)
    submission.page1_path = next((p for p in saved_paths if p not in essay_set), None)
    submission.page2_path = essay_saved_paths[0] if essay_saved_paths else None
    submission.essay_pages_json = (
        json.dumps(essay_saved_paths, ensure_ascii=False) if essay_saved_paths else None
    )
    submission.page1_ocr_text = page1_extraction.get("combined_text") or None
    submission.page2_ocr_text = (
        essay_extractions[0].get("combined_text") if essay_extractions else None
    ) or None
    submission.essay_pages_ocr_json = (
        json.dumps([e.get("combined_text", "") for e in essay_extractions], ensure_ascii=False)
        if essay_extractions else None
    )
    submission.easyocr_text = easyocr_text
    submission.ollama_text = ollama_text
    submission.combined_ocr_text = combined_text
    submission.omr_result_json = json.dumps(
        json_safe({"available": omr_available(), "pages": [page1_result.get("omr")] if page1_result.get("omr") else []}),
        ensure_ascii=False,
    )

    totals = recalculate_totals(db, submission)

    # Essay-graded exams stay "Graded" but unreleased; the professor decides
    # when a student may see the number.
    submission.submission_status = SubmissionStatus.Graded
    submission.graded_at = now
    # Processing is complete, so the sheet is locked against a second student
    # upload. Only the professor can replace it from here.
    submission.is_locked = True

    submission.processing_metadata_json = json.dumps(json_safe({
        "exam_types": {"mcq": bool(mcqs), "essay": bool(essays)},
        "essay_pages_expected": expected_essay_pages(essays),
        "timings": pipeline.get("timings", {}),
        "services": pipeline.get("services", {}),
        "nlp": _nlp_status(),
        "omr": {
            "available": omr_available(),
            "fill_threshold": float(os.getenv("OMR_FILL_THRESHOLD", "0.24")),
            "ambiguity_margin": float(os.getenv("OMR_AMBIGUITY_MARGIN", "0.055")),
        },
        "stored_files": saved_paths,
        "scanner": {
            "page1": (page1_result.get("scan") or {}).get("quality", {}),
            "page1_alignment": (page1_result.get("scan") or {}).get("alignment", {}),
        },
        "errors": [
            e for e in [page1_result.get("error")] + [r.get("error") for r in essay_results] if e
        ],
    }), ensure_ascii=False)

    return {
        "totals": totals,
        "essayDetail": essay_detail,
        "ocr": {
            "page1": page1_extraction,
            "essayPages": essay_extractions,
            "easyocrText": easyocr_text,
            "ollamaText": ollama_text,
        },
        "omr": {"available": omr_available(), "pages": [page1_result.get("omr")] if page1_result.get("omr") else []},
        "timings": pipeline.get("timings", {}),
    }


def _nlp_status() -> dict[str, Any]:
    try:
        from services import nlp_spacy

        return nlp_spacy.status()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Shared validation
# ---------------------------------------------------------------------------

def split_questions(db: Session, exam_id: int) -> tuple[list[ExamQuestion], list[ExamQuestion]]:
    mcqs = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.exam_id == exam_id, ExamQuestion.question_type == QuestionType.MCQ)
        .order_by(ExamQuestion.question_number)
        .all()
    )
    essays = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.exam_id == exam_id, ExamQuestion.question_type == QuestionType.Essay)
        .order_by(ExamQuestion.question_number)
        .all()
    )
    return mcqs, essays


def _build_topic_hint(essays: list[ExamQuestion], max_chars: int = 220) -> str:
    """Vocabulary context for the vision transcriber, from the QUESTION TEXT.

    Off by default. Set OCR_TOPIC_HINT=1 to enable.

    This deliberately does NOT use ``keywords`` or ``key_concepts``, even
    though those are the obvious source. ``essay_grader._score_concept_coverage``
    and ``_score_keyword_terminology`` score the transcription by matching
    those exact fields against it. Feeding them to the model that produces the
    transcription would mean showing the answer key to the transcriber and
    then grading the transcription on how many answer-key terms it contains --
    a vision model primed with "threat detection" is measurably more likely to
    emit that string from ambiguous strokes, which is the whole reason the
    roster trick works for names. The inflation would be invisible in the
    output and indefensible under examination.

    The question text is safe because the student read it themselves before
    writing, so it adds no information the answer was not already shaped by,
    and it is not what the rubric matches against.
    """
    if not _env_bool("OCR_TOPIC_HINT", False):
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    for q in essays:
        text = re.sub(r"\s+", " ", str(getattr(q, "question_text", "") or "")).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            parts.append(text)
    return " ".join(parts)[:max_chars]


def student_file_base(first_name: str, last_name: str, user_id: int) -> str:
    first = (first_name or "").strip().replace(" ", "_")
    last = (last_name or "").strip().replace(" ", "_")
    return f"{last}_{first}_{user_id}_answer_sheet"


def write_pages(
    upload_root: Path,
    exam_id: int,
    student_id: int,
    student_base: str,
    pages: list[PageInput],
) -> tuple[list[str], list[str]]:
    """Write the uploaded pages to disk. Returns (all paths, essay paths)."""
    folder = upload_root / str(exam_id) / str(student_id)
    folder.mkdir(parents=True, exist_ok=True)

    # (sort_key, relative_path) so ordering is driven by the page's declared
    # kind rather than by pattern-matching its filename. The old sort tested
    # for the substring "_page_1.", which also matches
    # "..._essay_page_1.jpg" -- so both files scored equally and the tie-break
    # fell through to alphabetical order, where "essay_page_1" sorts ahead of
    # "page_1". The MCQ sheet ended up behind the essay page, and
    # persist_result (which used the same broken test) then recorded the essay
    # page as page1_path.
    ordered: list[tuple[tuple[int, int], str]] = []
    essay_saved: list[str] = []

    for page in pages:
        if page.kind == "page1":
            destination = folder / f"{student_base}_page_1{page.ext}"
            sort_key = (0, 0)
        else:
            destination = folder / f"{student_base}_essay_page_{page.index + 1}{page.ext}"
            sort_key = (1, page.index)
        destination.write_bytes(page.data)
        rel = str(destination.relative_to(upload_root))
        ordered.append((sort_key, rel))
        if page.kind == "essay":
            essay_saved.append(rel)

    # Page 1 first, then essay pages in order, matching the on-sheet order.
    ordered.sort(key=lambda item: item[0])
    saved = [rel for _, rel in ordered]
    return saved, essay_saved


__all__ = [
    "ESSAYS_PER_PAGE",
    "MAX_MCQ_PER_PAGE",
    "PageInput",
    "expected_essay_pages",
    "grade_essays",
    "json_safe",
    "persist_result",
    "prepare_scan_safe",
    "process_submission_background",
    "recalculate_totals",
    "run_pipeline",
    "score_mcq",
    "split_questions",
    "student_file_base",
    "write_pages",
]
