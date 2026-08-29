from datetime import datetime
from io import BytesIO
import json
from types import SimpleNamespace
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.class_model import Class
from models.enrollment import Enrollment
from models.exam import Exam, ExamStatus
from models.exam_question import ExamQuestion, QuestionType
from models.exam_rubric import ExamRubric
from models.exam_submission import ExamSubmission, SubmissionStatus
from models.submission_answer import AnswerProcessingStatus, SubmissionAnswer
from models.user import User, UserRole
from schemas.exam_schema import (
    EssayScoreOverride,
    ExamCreate,
    ExamCreateResponse,
    ExamResponse,
    ExamUpdate,
    MCQQuestionResponse,
    EssayQuestionResponse,
    ReleaseRequest,
    RubricResponse,
    SubmissionResponse,
)
from services.auth_service import get_current_user
from services.essay_grader import highlight_spans, normalize_format
from services.rubric import CRITERIA, load_rubric_for_question, resolve_key
from services.exam_pdf import build_exam_answer_sheet
from services.submission_pipeline import recalculate_totals


router = APIRouter(prefix="/api/exams", tags=["exams"])


def _require_professor(user: User):
    if user.role != UserRole.Professor:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only professors can perform this action.")


def _owned_class(db: Session, class_id: int, user: User) -> Class:
    cls = db.query(Class).filter(Class.class_id == class_id).first()
    if not cls:
        raise HTTPException(status_code=404, detail=f"Class {class_id} not found.")
    if cls.teacher_id != user.user_id:
        raise HTTPException(status_code=403, detail="You do not own this class.")
    return cls


def _to_time(value):
    return value.strftime("%H:%M") if value else None


def _json_load(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _json_dump(values):
    cleaned = [str(value).strip() for value in (values or []) if str(value).strip()]
    return json.dumps(cleaned, ensure_ascii=False)


# Maps a canonical criterion's ExamQuestion column to the matching field on
# the incoming API payload, so validation can run before anything is written.
_PAYLOAD_EVIDENCE_FIELD = {
    "answer_key": "answerKey",
    "key_concepts": "keyConcepts",
    "keywords": "keywords",
    "requirements": "requirements",
}


def _rubric_response(rubric):
    return RubricResponse(
        id=rubric.rubric_id,
        name=rubric.criterion_name,
        weight=float(rubric.weight),
        questionId=rubric.question_id,
    )


def _question_payload(exam: Exam):
    mcqs, essays = [], []
    legacy_rubrics = []
    for q in sorted(exam.questions, key=lambda item: item.question_number):
        options = [q.option_a or "", q.option_b or "", q.option_c or "", q.option_d or "", q.option_e or ""]
        if q.question_type == QuestionType.MCQ:
            idx = None
            if q.correct_option:
                idx = "ABCDE".find(q.correct_option.upper())
                if idx < 0:
                    idx = None
            mcqs.append(
                MCQQuestionResponse(
                    id=q.question_id,
                    question=q.question_text,
                    options=options,
                    correctAnswer=idx,
                    points=float(q.points or 0),
                )
            )
        else:
            linked_rubrics = [_rubric_response(r) for r in q.rubrics]
            # Older V6.3 exams stored one exam-level rubric. Keep it usable when
            # an essay has no question-specific rubric yet.
            if not linked_rubrics and exam.rubrics:
                linked_rubrics = [_rubric_response(r) for r in exam.rubrics if r.question_id is None]
            essays.append(
                EssayQuestionResponse(
                    id=q.question_id,
                    question=q.question_text,
                    answerKey=q.answer_key or "",
                    keyConcepts=_json_load(q.key_concepts),
                    keywords=_json_load(q.keywords),
                    requirements=_json_load(q.requirements),
                    points=float(q.points or 0),
                    expectedResponseFormat=q.expected_response_format or "one_paragraph",
                    rubric=linked_rubrics,
                )
            )

    legacy_rubrics = [_rubric_response(r) for r in exam.rubrics if r.question_id is None]
    return mcqs, essays, legacy_rubrics


def _to_response(db: Session, exam: Exam) -> ExamResponse:
    cls = db.query(Class).filter(Class.class_id == exam.class_id).first()
    students = db.query(func.count(Enrollment.enrollment_id)).filter(Enrollment.class_id == exam.class_id).scalar() or 0
    submissions = db.query(func.count(ExamSubmission.submission_id)).filter(ExamSubmission.exam_id == exam.exam_id).scalar() or 0
    mcqs, essays, rubrics = _question_payload(exam)
    return ExamResponse(
        id=exam.exam_id,
        classId=exam.class_id,
        className=cls.class_name if cls else "",
        section=cls.section if cls else None,
        title=exam.exam_title,
        subject=exam.exam_subject,
        date=exam.exam_date.isoformat() if exam.exam_date else None,
        dueDate=exam.exam_date.isoformat() if exam.exam_date else None,
        time=_to_time(exam.start_time),
        status=exam.status.value if hasattr(exam.status, "value") else str(exam.status),
        totalItems=exam.total_items or 0,
        totalPoints=float(exam.total_points or 0),
        students=students,
        submissions=submissions,
        mcqQuestions=mcqs,
        essayQuestions=essays,
        rubric=rubrics,
    )


def _validate_rubric(rubric, label, question=None):
    """Weights must total 100, and each weighted criterion must be gradable.

    The second check is the important one: without it a professor could give
    Answer Relevance 40% on a question with no answer key, and the engine
    would have to silently drop or redistribute it at grading time. Catching
    it here means the rubric they configure is the rubric that runs.
    """
    if not rubric:
        raise HTTPException(status_code=422, detail=f"{label} requires a grading rubric.")

    if question is not None:
        for r in rubric:
            if float(r.weight or 0) <= 0:
                continue
            key = resolve_key(r.name)
            if key is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{label}: '{r.name}' is not a grading criterion this system recognises.",
                )
            crit = CRITERIA[key]
            if crit.evidence_field is None:
                continue
            value = getattr(question, _PAYLOAD_EVIDENCE_FIELD[crit.evidence_field], None)
            filled = bool(str(value).strip()) if isinstance(value, str) else bool(value)
            if not filled:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{label}: '{crit.label}' is weighted at {float(r.weight):g}% but this "
                        f"question has no {crit.evidence_label}. Add {crit.evidence_label}, or "
                        f"set that criterion's weight to 0 and redistribute it."
                    ),
                )

    total = sum(float(r.weight) for r in rubric)
    if abs(total - 100) > 0.01:
        raise HTTPException(status_code=422, detail=f"{label} rubric weights must total 100%. Current total: {total:g}%.")


def _validate_questions(payload: ExamCreate | ExamUpdate):
    mcqs = getattr(payload, "mcqQuestions", None)
    essays = getattr(payload, "essayQuestions", None)
    legacy_rubric = getattr(payload, "rubric", None)

    if not (mcqs and len(mcqs) > 0) and not (essays and len(essays) > 0):
        raise HTTPException(status_code=422, detail="An examination must contain at least one multiple-choice or essay question.")

    if mcqs is not None:
        for i, q in enumerate(mcqs, start=1):
            if len(q.options) != 5 or any(not str(x).strip() for x in q.options):
                raise HTTPException(status_code=422, detail=f"MCQ {i} must have exactly 5 non-empty options (A-E).")
            if q.correctAnswer is None or str(q.correctAnswer) == "":
                raise HTTPException(status_code=422, detail=f"MCQ {i} must have a correct answer.")
            if float(q.points) <= 0:
                raise HTTPException(status_code=422, detail=f"MCQ {i} must have points greater than 0.")

    if essays is not None:
        for i, q in enumerate(essays, start=1):
            if not q.question.strip():
                raise HTTPException(status_code=422, detail=f"Essay {i} requires a question.")
            if float(q.points) <= 0:
                raise HTTPException(status_code=422, detail=f"Essay {i} must have points greater than 0.")
            _validate_rubric(q.rubric, f"Essay {i}", question=q)

    # Backward compatibility: older clients may still send an exam-level rubric.
    if legacy_rubric:
        _validate_rubric(legacy_rubric, "Exam")


def _write_questions_and_rubric(db: Session, exam: Exam, mcqs, essays, legacy_rubric=None):
    # Rubrics reference questions, so delete rubrics before deleting questions.
    for r in list(exam.rubrics):
        db.delete(r)
    for q in list(exam.questions):
        db.delete(q)
    db.flush()

    number = 1
    total_points = 0.0

    for q in mcqs:
        correct = q.correctAnswer
        try:
            idx = int(correct)
        except (TypeError, ValueError):
            idx = "ABCDE".find(str(correct).upper())
        if idx < 0 or idx > 4:
            idx = None
        options = [str(x).strip() for x in q.options]
        points = float(q.points)
        db.add(
            ExamQuestion(
                exam_id=exam.exam_id,
                question_number=number,
                question_type=QuestionType.MCQ,
                question_text=q.question.strip(),
                option_a=options[0],
                option_b=options[1],
                option_c=options[2],
                option_d=options[3],
                option_e=options[4],
                correct_option="ABCDE"[idx] if idx is not None else None,
                points=points,
                expected_response_format="one_paragraph",
            )
        )
        total_points += points
        number += 1

    for q in essays:
        points = float(q.points)
        essay = ExamQuestion(
            exam_id=exam.exam_id,
            question_number=number,
            question_type=QuestionType.Essay,
            question_text=q.question.strip(),
            answer_key=q.answerKey.strip(),
            points=points,
            key_concepts=_json_dump(q.keyConcepts),
            keywords=_json_dump(q.keywords),
            requirements=_json_dump(q.requirements),
            # The professor's chosen format, not a hard-coded default. This
            # value drives the Structure criterion at grading time.
            expected_response_format=normalize_format(q.expectedResponseFormat),
        )
        db.add(essay)
        db.flush()

        rubric_items = q.rubric or legacy_rubric or []
        for order, r in enumerate(rubric_items, start=1):
            db.add(
                ExamRubric(
                    exam_id=exam.exam_id,
                    question_id=essay.question_id,
                    criterion_order=order,
                    criterion_name=r.name.strip(),
                    weight=r.weight,
                )
            )
        total_points += points
        number += 1

    # If a legacy client creates an exam without essays but sends an exam-level
    # rubric, preserve it as unassigned exam metadata.
    if not essays and legacy_rubric:
        for order, r in enumerate(legacy_rubric, start=1):
            db.add(
                ExamRubric(
                    exam_id=exam.exam_id,
                    question_id=None,
                    criterion_order=order,
                    criterion_name=r.name.strip(),
                    weight=r.weight,
                )
            )

    exam.total_items = len(mcqs) + len(essays)
    exam.total_points = total_points


@router.post("/preview-pdf")
def preview_exam_pdf(
    payload: ExamCreate,
    current_user: User = Depends(get_current_user),
):
    """Generate a non-persistent printable exam preview from the current form."""
    _require_professor(current_user)
    _validate_questions(payload)

    fake_exam = SimpleNamespace(
        exam_id=0,
        exam_subject=payload.subject.strip(),
        exam_title=payload.title.strip(),
        questions=[],
        rubrics=[],
    )

    number = 1
    for q in payload.mcqQuestions:
        options = [str(x).strip() for x in q.options]
        fake_exam.questions.append(
            SimpleNamespace(
                question_id=number,
                question_number=number,
                question_type=QuestionType.MCQ,
                question_text=q.question.strip(),
                option_a=options[0], option_b=options[1], option_c=options[2],
                option_d=options[3], option_e=options[4],
                correct_option="ABCDE"[int(q.correctAnswer)] if str(q.correctAnswer).isdigit() and 0 <= int(q.correctAnswer) <= 4 else str(q.correctAnswer).upper(),
                answer_key=None,
                points=float(q.points),
                key_concepts=None,
                keywords=None,
                requirements=None,
                expected_response_format="one_paragraph",
                rubrics=[],
            )
        )
        number += 1

    for q in payload.essayQuestions:
        fake_exam.questions.append(
            SimpleNamespace(
                question_id=number,
                question_number=number,
                question_type=QuestionType.Essay,
                question_text=q.question.strip(),
                option_a=None, option_b=None, option_c=None, option_d=None, option_e=None,
                correct_option=None,
                answer_key=q.answerKey.strip(),
                points=float(q.points),
                key_concepts=_json_dump(q.keyConcepts),
                keywords=_json_dump(q.keywords),
                requirements=_json_dump(q.requirements),
                expected_response_format=normalize_format(q.expectedResponseFormat),
                rubrics=[],
            )
        )
        number += 1

    try:
        pdf_bytes = build_exam_answer_sheet(fake_exam, None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF preview generation failed: {exc}") from exc

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="ESSCAN_Exam_Preview.pdf"'},
    )


@router.get("", response_model=List[ExamResponse])
def list_exams(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_professor(current_user)
    exams = (
        db.query(Exam)
        .filter(Exam.teacher_id == current_user.user_id)
        .order_by(Exam.created_at.desc(), Exam.exam_id.desc())
        .all()
    )
    return [_to_response(db, exam) for exam in exams]


@router.post("", response_model=ExamCreateResponse, status_code=201)
def create_exam(
    payload: ExamCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_professor(current_user)
    _validate_questions(payload)

    # The existing database model associates an exam with one class.
    # If several classes are selected in the UI, create one identical exam per class.
    try:
        class_ids = list(dict.fromkeys(int(class_id) for class_id in payload.classIds))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Each selected class must have a valid numeric class ID.")
    classes = [_owned_class(db, class_id, current_user) for class_id in class_ids]

    created = []
    try:
        for cls in classes:
            exam = Exam(
                class_id=cls.class_id,
                teacher_id=current_user.user_id,
                exam_title=payload.title.strip(),
                exam_subject=payload.subject.strip(),
                status=ExamStatus.Published if payload.status.lower() == "published" else ExamStatus.Draft,
            )
            db.add(exam)
            db.flush()
            _write_questions_and_rubric(db, exam, payload.mcqQuestions, payload.essayQuestions, payload.rubric)
            created.append(exam)

        db.commit()
        for exam in created:
            db.refresh(exam)
            _ = exam.questions
            _ = exam.rubrics
    except Exception:
        db.rollback()
        raise

    return ExamCreateResponse(
        exam=_to_response(db, created[0]),
        createdExamIds=[e.exam_id for e in created],
    )


@router.get("/{exam_id}", response_model=ExamResponse)
def get_exam(exam_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_professor(current_user)
    exam = db.query(Exam).filter(Exam.exam_id == exam_id, Exam.teacher_id == current_user.user_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return _to_response(db, exam)


@router.put("/{exam_id}", response_model=ExamResponse)
def update_exam(
    exam_id: int,
    payload: ExamUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_professor(current_user)
    exam = db.query(Exam).filter(Exam.exam_id == exam_id, Exam.teacher_id == current_user.user_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    _validate_questions(payload)

    if payload.title is not None:
        exam.exam_title = payload.title.strip()
    if payload.subject is not None:
        exam.exam_subject = payload.subject.strip()
    if payload.status is not None:
        try:
            exam.status = ExamStatus(payload.status)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid exam status.")

    if payload.classIds:
        _owned_class(db, payload.classIds[0], current_user)
        exam.class_id = payload.classIds[0]

    if payload.mcqQuestions is not None or payload.essayQuestions is not None or payload.rubric is not None:
        # Convert response objects back to the create schema is unnecessary; require full lists for edits.
        if payload.mcqQuestions is None or payload.essayQuestions is None or payload.rubric is None:
            raise HTTPException(status_code=422, detail="Questions and rubric must be submitted together when editing an exam.")
        _write_questions_and_rubric(db, exam, payload.mcqQuestions, payload.essayQuestions, payload.rubric)

    db.commit()
    db.refresh(exam)
    return _to_response(db, exam)


@router.get("/{exam_id}/submissions", response_model=List[SubmissionResponse])
def list_submissions(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_professor(current_user)
    exam = db.query(Exam).filter(Exam.exam_id == exam_id, Exam.teacher_id == current_user.user_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    rows = (
        db.query(ExamSubmission, User)
        .join(User, User.user_id == ExamSubmission.student_id)
        .filter(ExamSubmission.exam_id == exam_id)
        .order_by(User.last_name, User.first_name)
        .all()
    )
    override_counts = dict(
        db.query(SubmissionAnswer.submission_id, func.count(SubmissionAnswer.answer_id))
        .filter(
            SubmissionAnswer.submission_id.in_([s.submission_id for s, _ in rows] or [0]),
            SubmissionAnswer.override_score.isnot(None),
        )
        .group_by(SubmissionAnswer.submission_id)
        .all()
    )

    return [
        SubmissionResponse(
            id=s.submission_id,
            studentId=s.student_id,
            studentName=f"{u.first_name} {u.last_name}",
            status=s.submission_status.value if hasattr(s.submission_status, "value") else str(s.submission_status),
            score=float(s.final_score) if s.final_score is not None else None,
            submittedAt=s.submitted_at,
            maxScore=float(s.max_score) if s.max_score is not None else None,
            mcqScore=float(s.mcq_score) if s.mcq_score is not None else None,
            essayScore=float(s.essay_score) if s.essay_score is not None else None,
            scoresReleased=bool(s.scores_released),
            releasedAt=s.released_at,
            locked=s.locked_for_student(),
            overriddenCount=int(override_counts.get(s.submission_id, 0)),
        )
        for s, u in rows
    ]


@router.get("/{exam_id}/submissions/by-student/{student_id}")
def get_submission_by_student(
    exam_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full grading detail for one student's submission, including the
    Page 1 (MCQ/OMR) score computed from the stored bubble detections.
    """
    _require_professor(current_user)
    exam = db.query(Exam).filter(Exam.exam_id == exam_id, Exam.teacher_id == current_user.user_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    student = db.query(User).filter(User.user_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    submission = db.query(ExamSubmission).filter(
        ExamSubmission.exam_id == exam_id,
        ExamSubmission.student_id == student_id,
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail="No submission found for that student.")

    mcqs = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.exam_id == exam_id, ExamQuestion.question_type == QuestionType.MCQ)
        .order_by(ExamQuestion.question_number).all()
    )
    essays = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.exam_id == exam_id, ExamQuestion.question_type == QuestionType.Essay)
        .order_by(ExamQuestion.question_number).all()
    )

    answers_by_question = {
        row.question_id: row
        for row in db.query(SubmissionAnswer).filter(SubmissionAnswer.submission_id == submission.submission_id).all()
    }

    mcq_questions = []
    mcq_score = 0.0
    mcq_max = 0.0
    for q in mcqs:
        points = float(q.points or 0)
        mcq_max += points
        row = answers_by_question.get(q.question_id)
        selected = row.selected_option if row else None
        is_blank = bool(row.is_blank) if row else True
        is_ambiguous = bool(row.is_ambiguous) if row else False
        correct = bool(
            row
            and not is_blank
            and not is_ambiguous
            and selected
            and q.correct_option
            and selected.strip().upper() == q.correct_option.strip().upper()
        )
        if correct:
            mcq_score += points
        mcq_questions.append({
            "questionId": q.question_id,
            "questionNumber": q.question_number,
            "questionText": q.question_text,
            "points": points,
            "correctOption": q.correct_option,
            "selectedOption": selected,
            "isBlank": is_blank,
            "isAmbiguous": is_ambiguous,
            "isCorrect": correct,
            "confidence": float(row.confidence) if row and row.confidence is not None else None,
        })

    essay_pages = _json_load(submission.essay_pages_ocr_json) or []
    essay_page_paths = _json_load(submission.essay_pages_json) or []

    try:
        omr_meta = json.loads(submission.omr_result_json) if submission.omr_result_json else {}
    except (TypeError, ValueError):
        omr_meta = {}

    status_value = (
        submission.submission_status.value
        if hasattr(submission.submission_status, "value")
        else str(submission.submission_status)
    )
    is_processing = status_value in ("Uploaded", "OCR_Processing", "NLP_Processing")
    is_failed = status_value == "Failed"
    # A failed submission never actually finished grading either — its
    # per-question rows (if any exist at all) are leftovers from before the
    # pipeline crashed, not real results, so they are hidden the same way a
    # still-processing submission's are.
    hide_breakdown = is_processing or is_failed
    background_error = None
    if is_failed and submission.processing_metadata_json:
        try:
            background_error = json.loads(submission.processing_metadata_json).get("error")
        except (TypeError, ValueError):
            background_error = None

    return {
        "submissionId": submission.submission_id,
        "examId": exam.exam_id,
        "examTitle": exam.exam_title,
        "student": {
            "id": student.user_id,
            "name": f"{student.first_name} {student.last_name}",
        },
        "status": status_value,
        # Grading now runs in a background task after the upload response
        # returns, so a submission can sit briefly (or, on a failure,
        # indefinitely) without a score. The UI needs to tell that apart from
        # "graded with a zero" or "nothing here yet".
        "processing": is_processing,
        "failed": is_failed,
        "error": background_error,
        "submittedAt": submission.submitted_at,
        "finalScore": float(submission.final_score) if submission.final_score is not None else None,
        "mcq": {
            "available": bool(mcqs),
            "omrAvailable": bool(omr_meta.get("available")),
            "score": round(mcq_score, 2) if mcqs and not hide_breakdown else None,
            "maxScore": round(mcq_max, 2) if mcqs else None,
            "questions": [] if hide_breakdown else mcq_questions,
        },
        "essay": {
            "available": bool(essays),
            "score": float(submission.essay_score) if submission.essay_score is not None else None,
            "maxScore": round(sum(float(q.points or 0) for q in essays), 2) if essays else None,
            "pages": [
                {"index": i, "path": essay_page_paths[i] if i < len(essay_page_paths) else None, "ocrText": text}
                for i, text in enumerate(essay_pages)
            ],
            "combinedText": submission.combined_ocr_text,
            "questions": [] if hide_breakdown else _essay_question_payload(essays, answers_by_question),
        },
        "release": {
            "released": bool(submission.scores_released),
            "releasedAt": submission.released_at,
            "canRelease": submission.submission_status in {SubmissionStatus.Graded, SubmissionStatus.Released},
        },
        "locked": submission.locked_for_student(),
        "maxScore": float(submission.max_score) if submission.max_score is not None else None,
        "files": {
            "page1": submission.page1_path,
            "essayPages": essay_page_paths,
        },
    }


def _essay_question_payload(essays, answers_by_question) -> list[dict]:
    """Per-essay grading detail: transcription, AI score, override, breakdown.

    ``score`` is the effective score the professor's override produces, while
    ``autoScore`` keeps the AI's original judgement visible so it is always
    clear what was changed and by how much.
    """
    payload = []
    for q in essays:
        row = answers_by_question.get(q.question_id)
        feedback = {}
        if row and row.feedback_json:
            try:
                feedback = json.loads(row.feedback_json)
            except (TypeError, ValueError):
                feedback = {}

        answer_text = (row.answer_text if row else "") or ""
        payload.append({
            "questionId": q.question_id,
            "questionNumber": q.question_number,
            "questionText": q.question_text,
            "points": float(q.points or 0),
            "answerText": answer_text,
            "autoScore": float(row.auto_score) if row and row.auto_score is not None else None,
            "overrideScore": float(row.override_score) if row and row.override_score is not None else None,
            "score": row.effective_score if row else None,
            "isOverridden": bool(row and row.is_overridden),
            "overrideReason": row.override_reason if row else None,
            "overriddenAt": row.overridden_at if row else None,
            "isBlank": bool(row.is_blank) if row else True,
            "criteria": feedback.get("criteria") or [],
            "analysis": feedback.get("analysis") or {},
            "summary": feedback.get("summary"),
            # Which rubric produced this score, and the weights it used.
            "rubric": feedback.get("rubric") or {},
            "expectedResponseFormat": feedback.get("expectedResponseFormat"),
            "percentage": feedback.get("percentage"),
            # True while similarity comes from the lexical placeholder rather
            # than the fine-tuned Sentence-BERT model.
            "semanticPending": bool(feedback.get("semanticPending")),
            "engine": feedback.get("engine") or {},
            "highlights": highlight_spans(answer_text, q),
        })
    return payload


def _load_owned_submission(db: Session, exam_id: int, student_id: int, current_user: User):
    exam = db.query(Exam).filter(Exam.exam_id == exam_id, Exam.teacher_id == current_user.user_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    submission = db.query(ExamSubmission).filter(
        ExamSubmission.exam_id == exam_id,
        ExamSubmission.student_id == student_id,
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail="No submission found for that student.")
    return exam, submission


@router.put("/{exam_id}/submissions/by-student/{student_id}/essay/{question_id}/score")
def override_essay_score(
    exam_id: int,
    student_id: int,
    question_id: int,
    payload: EssayScoreOverride,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set or clear the professor's manual score for one essay answer.

    The AI score in ``auto_score`` is never modified, so an override can
    always be undone by sending ``score: null``. Totals are recomputed
    immediately so the submission list and the student's released view stay
    consistent with the change.
    """
    _require_professor(current_user)
    _, submission = _load_owned_submission(db, exam_id, student_id, current_user)

    question = db.query(ExamQuestion).filter(
        ExamQuestion.question_id == question_id,
        ExamQuestion.exam_id == exam_id,
    ).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found on this examination.")
    if question.question_type != QuestionType.Essay:
        raise HTTPException(status_code=422, detail="Only essay answers can be scored manually.")

    max_points = float(question.points or 0)
    if payload.score is not None:
        if payload.score < 0:
            raise HTTPException(status_code=422, detail="A score cannot be negative.")
        if payload.score > max_points:
            raise HTTPException(
                status_code=422,
                detail=f"This question is worth {max_points:g} point(s); {payload.score:g} is higher than the maximum.",
            )

    row = db.query(SubmissionAnswer).filter(
        SubmissionAnswer.submission_id == submission.submission_id,
        SubmissionAnswer.question_id == question_id,
    ).first()
    if not row:
        row = SubmissionAnswer(submission_id=submission.submission_id, question_id=question_id)
        db.add(row)
        db.flush()

    if payload.score is None:
        row.override_score = None
        row.override_reason = None
        row.overridden_by = None
        row.overridden_at = None
        row.processing_status = AnswerProcessingStatus.Graded
    else:
        row.override_score = round(float(payload.score), 2)
        row.override_reason = (payload.reason or "").strip() or None
        row.overridden_by = current_user.user_id
        row.overridden_at = datetime.now()
        row.processing_status = AnswerProcessingStatus.Overridden

    row.max_score = max_points
    totals = recalculate_totals(db, submission)
    submission.graded_at = datetime.now()
    db.commit()
    db.refresh(row)
    db.refresh(submission)

    return {
        "questionId": question_id,
        "autoScore": float(row.auto_score) if row.auto_score is not None else None,
        "overrideScore": float(row.override_score) if row.override_score is not None else None,
        "score": row.effective_score,
        "maxScore": max_points,
        "isOverridden": row.is_overridden,
        "finalScore": totals["finalScore"],
        "maxTotal": totals["maxScore"],
        "essayScore": totals["essayScore"],
        "scoresReleased": bool(submission.scores_released),
    }


@router.post("/{exam_id}/submissions/by-student/{student_id}/release")
def release_student_score(
    exam_id: int,
    student_id: int,
    payload: ReleaseRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Make one student's score visible to them, or hide it again.

    Releasing is separate from grading on purpose: a professor can finish
    reviewing and adjusting a whole class before any student sees a number.
    """
    _require_professor(current_user)
    _, submission = _load_owned_submission(db, exam_id, student_id, current_user)

    release = True if payload is None else bool(payload.released)

    if release and submission.final_score is None:
        raise HTTPException(
            status_code=422,
            detail="This submission has no score yet. Process the answer sheet before releasing.",
        )

    submission.scores_released = release
    submission.released_at = datetime.now() if release else None
    submission.released_by = current_user.user_id if release else None
    submission.submission_status = SubmissionStatus.Released if release else SubmissionStatus.Graded
    db.commit()
    db.refresh(submission)

    return {
        "studentId": student_id,
        "released": bool(submission.scores_released),
        "releasedAt": submission.released_at,
        "status": submission.submission_status.value,
        "finalScore": float(submission.final_score) if submission.final_score is not None else None,
    }


@router.post("/{exam_id}/submissions/release")
def release_exam_scores(
    exam_id: int,
    payload: ReleaseRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Release (or hide) scores for many students at once.

    Submissions that have not been scored yet are skipped rather than treated
    as an error, so releasing a whole class works even while a few sheets are
    still outstanding.
    """
    _require_professor(current_user)
    exam = db.query(Exam).filter(Exam.exam_id == exam_id, Exam.teacher_id == current_user.user_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    release = True if payload is None else bool(payload.released)
    student_ids = (payload.studentIds if payload else None) or None

    query = db.query(ExamSubmission).filter(ExamSubmission.exam_id == exam_id)
    if student_ids:
        query = query.filter(ExamSubmission.student_id.in_(student_ids))

    now = datetime.now()
    changed = []
    skipped = []
    for submission in query.all():
        if release and submission.final_score is None:
            skipped.append(submission.student_id)
            continue
        submission.scores_released = release
        submission.released_at = now if release else None
        submission.released_by = current_user.user_id if release else None
        submission.submission_status = SubmissionStatus.Released if release else SubmissionStatus.Graded
        changed.append(submission.student_id)

    db.commit()
    return {
        "examId": exam_id,
        "released": release,
        "updated": len(changed),
        "studentIds": changed,
        "skipped": skipped,
        "message": (
            f"{len(changed)} score(s) released."
            if release else f"{len(changed)} score(s) hidden from students."
        ) + (f" {len(skipped)} submission(s) skipped because they have no score yet." if skipped else ""),
    }


@router.get("/{exam_id}/pdf")
def download_exam_pdf(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_professor(current_user)
    exam = db.query(Exam).filter(Exam.exam_id == exam_id, Exam.teacher_id == current_user.user_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    try:
        pdf_bytes = build_exam_answer_sheet(exam, db)
    except Exception as exc:
        # Return a readable API error instead of an opaque browser/object error.
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc
    safe_title = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in exam.exam_title).strip("_")[:60]
    filename = f"ESSCAN_{exam.exam_id}_{safe_title or 'Exam'}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
