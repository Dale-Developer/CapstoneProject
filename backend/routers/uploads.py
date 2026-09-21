import json
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models.enrollment import Enrollment
from models.exam import Exam
from models.exam_submission import ExamSubmission, SubmissionStatus
from models.user import User
from services.auth_service import get_current_user
from services.ocr_hybrid import (
    easyocr_available,
    easyocr_error,
    extract_text,
    ollama_available,
    ollama_error,
)
from services.ocr_match import match_students
from services.scanner import analyze_capture
from services.submission_pipeline import (
    MAX_MCQ_PER_PAGE,
    PageInput,
    expected_essay_pages,
    json_safe,
    persist_result,
    process_submission_background,
    read_upload_limited,
    run_pipeline,
    split_questions,
    student_file_base,
    write_pages,
)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
# Sheets uploaded by a professor land in the same tree/format as student
# self-uploads (see routers/student.py), keyed by exam then student, so they
# show up identically everywhere downstream (submissions list, grading, etc).
UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "uploads" / "student_submissions"
ALLOWED = {".jpg", ".jpeg", ".png", ".pdf", ".webp"}


def _require_professor(user: User):
    if user.role.value != "Professor":
        raise HTTPException(status_code=403, detail="Only professors can upload answer sheets.")


def _owned_exam(db: Session, exam_id: int, user: User) -> Exam:
    exam = db.query(Exam).filter(Exam.exam_id == exam_id, Exam.teacher_id == user.user_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found.")
    return exam


def _roster(db: Session, class_id: int) -> list[dict]:
    rows = (
        db.query(User)
        .join(Enrollment, Enrollment.student_id == User.user_id)
        .filter(Enrollment.class_id == class_id)
        .order_by(User.last_name, User.first_name)
        .all()
    )
    return [{"id": u.user_id, "name": f"{u.first_name} {u.last_name}", "email": u.email} for u in rows]


@router.get("/submissions/{submission_id}/file")
async def get_submission_file(
    submission_id: int,
    which: str = "page1",
    index: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve a scanned submission image/PDF.

    A professor may read any submission for an exam they own; a student may
    read only their own pages, which is what lets the student result screen
    show the sheet that was actually scanned.
    """
    submission = db.query(ExamSubmission).filter(ExamSubmission.submission_id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found.")

    is_owner_student = (
        current_user.role.value == "Student" and submission.student_id == current_user.user_id
    )
    if not is_owner_student:
        _require_professor(current_user)
        exam = db.query(Exam).filter(
            Exam.exam_id == submission.exam_id, Exam.teacher_id == current_user.user_id
        ).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Submission not found.")

    if which == "page1":
        rel_path = submission.page1_path
    elif which == "essay":
        pages = json.loads(submission.essay_pages_json) if submission.essay_pages_json else []
        rel_path = pages[index] if 0 <= index < len(pages) else None
    else:
        raise HTTPException(status_code=422, detail="which must be 'page1' or 'essay'.")

    if not rel_path:
        raise HTTPException(status_code=404, detail="That page was not uploaded for this submission.")

    full_path = (UPLOAD_ROOT / rel_path).resolve()
    if UPLOAD_ROOT.resolve() not in full_path.parents or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(full_path)


@router.get("/submissions/status")
async def submission_status(
    exam_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Report whether this student already has a processed sheet.

    The professor's upload screen calls this once a student is selected, so it
    can warn that submitting again will discard existing scores instead of
    surfacing the conflict only after the sheet has been processed.
    """
    _require_professor(current_user)
    _owned_exam(db, exam_id, current_user)

    submission = db.query(ExamSubmission).filter(
        ExamSubmission.exam_id == exam_id,
        ExamSubmission.student_id == student_id,
    ).first()

    if not submission:
        return {"exists": False, "locked": False, "attemptCount": 0}

    status_value = (
        submission.submission_status.value
        if hasattr(submission.submission_status, "value")
        else str(submission.submission_status)
    )
    error_detail = None
    if status_value == "Failed" and submission.processing_metadata_json:
        try:
            error_detail = json.loads(submission.processing_metadata_json).get("error")
        except (TypeError, ValueError):
            error_detail = None

    return {
        "exists": True,
        "submissionId": submission.submission_id,
        "locked": submission.locked_for_student(),
        "status": status_value,
        # True while grading is still running in the background — the sheet
        # was accepted and locked, but final_score is not ready yet.
        "processing": status_value in ("Uploaded", "OCR_Processing", "NLP_Processing"),
        "failed": status_value == "Failed",
        "error": error_detail,
        "submittedAt": submission.submitted_at,
        "processedAt": submission.processed_at,
        "attemptCount": int(submission.attempt_count or 0),
        "scoresReleased": bool(submission.scores_released),
        "finalScore": float(submission.final_score) if submission.final_score is not None else None,
        "maxScore": float(submission.max_score) if submission.max_score is not None else None,
    }


@router.post("/match")
async def match_answer_sheet_owner(
    exam_id: int = Form(...),
    page1: UploadFile | None = File(None),
    essay_pages: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """OCR the available identification page and return ranked roster matches.

    MCQ exams identify from Page 1; essay-only exams identify from the first
    essay page. Mixed exams use Page 1 first. The professor still confirms
    the student.
    """
    _require_professor(current_user)
    exam = _owned_exam(db, exam_id, current_user)
    essay_pages = [f for f in essay_pages if f is not None]
    first_essay_page = essay_pages[0] if essay_pages else None
    if not page1 and not first_essay_page:
        raise HTTPException(status_code=422, detail="Provide at least one answer-sheet page for student identification.")

    upload = page1 or first_essay_page
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {ext or 'unknown'}")

    roster = _roster(db, exam.class_id)
    extraction = {"easyocr_text": "", "ollama_text": "", "combined_text": ""}
    if ext != ".pdf":
        data = await read_upload_limited(upload)
        # OCR is CPU-bound. Running it in a worker thread keeps the event loop
        # free so the app stays responsive during identification. The roster
        # is passed through so Ollama (if it fires) matches against real
        # candidate names instead of transcribing blind — faster and more
        # accurate; see extract_text()'s docstring.
        extraction = await run_in_threadpool(extract_text, data, None, roster)

    candidates = match_students(extraction, roster)
    top = candidates[: min(5, len(candidates))]

    easy_available = easyocr_available()
    ollama_ok = ollama_available()
    return json_safe({
        "easyocrAvailable": easy_available,
        "easyocrError": None if easy_available else easyocr_error(),
        "ollamaAvailable": ollama_ok,
        "ollamaError": None if ollama_ok else ollama_error(),
        "easyocrText": extraction["easyocr_text"],
        "ollamaText": extraction["ollama_text"],
        "candidates": top,
        "roster": candidates,
        "identificationPage": 1 if page1 else 2,
    })


def _authorize_scan_preview(db: Session, exam_id: int, user: User) -> Exam:
    """Allow the exam's owning professor OR an enrolled student to preview scans.

    This endpoint only runs page-alignment detection and stores nothing, so
    the access rule is the same "can this person legitimately be scanning
    this exam's answer sheet" check used by the real upload endpoints —
    just without also requiring an existing submission. Both the professor
    upload flow and the student self-upload flow use the same CameraScanner
    component and therefore need to reach this endpoint.
    """
    if user.role.value == "Professor":
        return _owned_exam(db, exam_id, user)

    exam = db.query(Exam).filter(Exam.exam_id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found.")
    enrolled = db.query(Enrollment).filter(
        Enrollment.class_id == exam.class_id, Enrollment.student_id == user.user_id
    ).first()
    if not enrolled:
        raise HTTPException(status_code=403, detail="You are not enrolled in this class.")
    return exam


@router.post("/scan-preview")
async def scan_preview(
    exam_id: int = Form(...),
    page_number: int = Form(1),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live camera page detection. No OCR, OMR answers, or files are stored.

    Open to the exam's professor and to enrolled students — the professor
    upload flow and the student self-upload flow share the same live-scanning
    UI (auto-frame detection, corner tracking, stability-based auto-capture),
    so both need to reach this endpoint.
    """
    exam = _authorize_scan_preview(db, exam_id, current_user)
    if page_number < 1:
        raise HTTPException(status_code=422, detail="page_number must be 1 or greater.")
    ext = Path(image.filename or "").suffix.lower()
    if ext not in ALLOWED or ext == ".pdf":
        raise HTTPException(status_code=422, detail="Live scanning requires a JPG, PNG, or WEBP image.")
    # Live preview frames are lightweight by design (this runs ~2x/second
    # while scanning), so they get a much tighter cap than a full-page
    # upload — also protects against a client hammering this endpoint with
    # oversized frames.
    data = await read_upload_limited(image, max_mb=5)

    # This runs on every camera frame, so it must never occupy the event loop.
    result = await run_in_threadpool(analyze_capture, data)
    return json_safe({
        "examId": exam.exam_id,
        "pageNumber": page_number,
        "ready": bool(result.get("ready")),
        "alignment": result.get("alignment", {}),
        "quality": result.get("quality", {}),
        "source_corners": result.get("source_corners"),
        "source_frame_size": result.get("source_frame_size"),
        "recommendation": result.get("recommendation"),
        "error": result.get("error"),
    })


async def collect_pages(
    page1: UploadFile | None,
    essay_pages: List[UploadFile],
) -> list[PageInput]:
    """Read every uploaded page into memory and validate its extension."""
    pages: list[PageInput] = []

    if page1 is not None:
        ext = Path(page1.filename or "").suffix.lower()
        if ext not in ALLOWED:
            raise HTTPException(status_code=422, detail="Unsupported file type for page 1.")
        pages.append(PageInput("page1", 0, await read_upload_limited(page1), ext, page1.filename or ""))

    for i, upload in enumerate(essay_pages):
        ext = Path(upload.filename or "").suffix.lower()
        if ext not in ALLOWED:
            raise HTTPException(status_code=422, detail=f"Unsupported file type for essay page {i + 1}.")
        pages.append(PageInput("essay", i, await read_upload_limited(upload), ext, upload.filename or ""))

    return pages


@router.post("/submissions")
async def upload_answer_sheet_for_student(
    background_tasks: BackgroundTasks,
    exam_id: int = Form(...),
    student_id: int = Form(...),
    allow_replace: bool = Form(False),
    page1: UploadFile | None = File(None),
    essay_pages: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save the pages this exam requires, then run OMR, OCR and NLP grading.

    The request returns as soon as the files are saved and the submission is
    locked — grading runs afterward in a background task. This is what lets
    a professor scan one student and move straight to the next without
    waiting for OCR and essay grading to finish; poll
    ``GET /uploads/submissions/status`` (or reopen the exam) to see when a
    given sheet's score is ready.

    A submission that has already been accepted is locked. The professor —
    and only the professor — can replace it, but must opt in explicitly via
    ``allow_replace``, so a re-scan is always deliberate rather than an
    accidental overwrite of work that may already be released to a student.
    """
    _require_professor(current_user)
    exam = _owned_exam(db, exam_id, current_user)
    essay_pages = [f for f in essay_pages if f is not None]

    student = db.query(User).filter(User.user_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    enrolled = db.query(Enrollment).filter(
        Enrollment.class_id == exam.class_id, Enrollment.student_id == student_id
    ).first()
    if not enrolled:
        raise HTTPException(status_code=422, detail="That student is not enrolled in this exam's class.")

    submission = db.query(ExamSubmission).filter(
        ExamSubmission.exam_id == exam_id,
        ExamSubmission.student_id == student.user_id,
    ).first()

    if submission and submission.locked_for_student() and not allow_replace:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{student.first_name} {student.last_name} already has a processed answer sheet "
                "for this examination. Re-scanning will discard the current scores. "
                "Confirm the replacement to continue."
            ),
        )

    mcqs, essays = split_questions(db, exam_id)

    if mcqs and not page1:
        raise HTTPException(status_code=422, detail="This examination contains multiple-choice questions. Page 1 is required.")
    if not mcqs and not essays:
        raise HTTPException(status_code=422, detail="This examination has no questions to process.")
    if len(mcqs) > MAX_MCQ_PER_PAGE:
        raise HTTPException(
            status_code=422,
            detail=(
                f"More than {MAX_MCQ_PER_PAGE} multiple-choice questions require a second MCQ "
                "answer page, which is not yet supported alongside essay pages."
            ),
        )

    expected = expected_essay_pages(essays)
    if essays and len(essay_pages) != expected:
        noun = "page" if expected == 1 else "pages"
        raise HTTPException(
            status_code=422,
            detail=(
                f"This examination requires {expected} essay answer {noun}. "
                "Short answers share a page, two per page; a multi-paragraph "
                "answer takes a page of its own."
            ),
        )

    pages = await collect_pages(page1, essay_pages)
    student_base = student_file_base(student.first_name, student.last_name, student.user_id)
    saved_paths, essay_saved_paths = write_pages(
        UPLOAD_ROOT, exam_id, student.user_id, student_base, pages
    )

    if not submission:
        submission = ExamSubmission(exam_id=exam_id, student_id=student.user_id)
        db.add(submission)
        db.flush()

    # A replacement invalidates any previously released score: the student
    # must not keep seeing a number that no longer matches their sheet.
    if allow_replace and submission.scores_released:
        submission.scores_released = False
        submission.released_at = None
        submission.released_by = None

    # Everything from here down is fast: writing rows and a commit. The
    # sheet is locked and marked processing IMMEDIATELY, before any OCR/OMR
    # runs, so a second upload attempt is rejected right away rather than
    # racing the pipeline. The heavy work (scanner, OMR, EasyOCR, Ollama,
    # spaCy) is handed to a background task and does not block this
    # response — a professor scanning a class does not wait through OCR and
    # essay grading between students; only the file save has to finish.
    submission.is_locked = True
    submission.submission_status = SubmissionStatus.OCR_Processing
    submission.submitted_at = datetime.now()
    submission.attempt_count = int(submission.attempt_count or 0) + 1
    submission.uploaded_by = current_user.user_id
    submission.student_filename = f"{student_base}.pdf"

    db.commit()
    db.refresh(submission)

    background_tasks.add_task(
        process_submission_background,
        submission.submission_id,
        pages,
        exam_id,
        [q.question_number for q in mcqs],
        len(essays),
        bool(mcqs),
        saved_paths,
        essay_saved_paths,
    )

    return json_safe({
        "message": (
            f"Answer sheet received for {student.first_name} {student.last_name}. "
            "Grading is running in the background — you can scan the next student now."
        ),
        "submissionId": submission.submission_id,
        "studentId": student.user_id,
        "filename": submission.student_filename,
        "status": submission.submission_status.value,
        "processing": True,
        "replaced": bool(allow_replace),
        "scoresReleased": bool(submission.scores_released),
    })
