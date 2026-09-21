import json
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from database import get_db
from models.enrollment import Enrollment
from models.exam import Exam
from models.exam_question import ExamQuestion, QuestionType
from models.exam_submission import ExamSubmission, SubmissionStatus
from models.submission_answer import SubmissionAnswer
from models.user import User, UserRole
from services.auth_service import get_current_user
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

router = APIRouter(prefix="/api/student", tags=["student"])
UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "uploads" / "student_submissions"
ALLOWED = {".jpg", ".jpeg", ".png", ".pdf", ".webp"}


def _require_student(user: User):
    if user.role != UserRole.Student:
        raise HTTPException(status_code=403, detail="Only students can access this resource.")


def _enrolled_exam(db: Session, exam_id: int, user: User) -> Exam:
    exam = db.query(Exam).filter(Exam.exam_id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found.")
    enrolled = db.query(Enrollment).filter(
        Enrollment.class_id == exam.class_id,
        Enrollment.student_id == user.user_id,
    ).first()
    if not enrolled:
        raise HTTPException(status_code=403, detail="You are not enrolled in this class.")
    return exam


def _submission_summary(submission: ExamSubmission | None) -> dict | None:
    """What the student is allowed to know about their own submission.

    Scores are deliberately excluded unless the professor has released them.
    """
    if not submission:
        return None

    released = bool(submission.scores_released)
    status_value = (
        submission.submission_status.value
        if hasattr(submission.submission_status, "value")
        else str(submission.submission_status)
    )
    return {
        "id": submission.submission_id,
        "status": status_value,
        # True while grading is still running in the background. The sheet
        # was received and is locked, but no score exists yet.
        "processing": status_value in ("Uploaded", "OCR_Processing", "NLP_Processing"),
        "failed": status_value == "Failed",
        "submittedAt": submission.submitted_at,
        "processedAt": submission.processed_at,
        "locked": submission.locked_for_student(),
        "attemptCount": int(submission.attempt_count or 0),
        "scoresReleased": released,
        "finalScore": float(submission.final_score) if released and submission.final_score is not None else None,
        "maxScore": float(submission.max_score) if released and submission.max_score is not None else None,
    }


@router.get("/exams")
def list_student_exams(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_student(current_user)
    rows = (
        db.query(Exam)
        .join(Enrollment, Enrollment.class_id == Exam.class_id)
        .filter(Enrollment.student_id == current_user.user_id)
        .order_by(Exam.exam_date.asc(), Exam.exam_id.desc())
        .all()
    )

    submissions = {
        s.exam_id: s
        for s in db.query(ExamSubmission)
        .filter(ExamSubmission.student_id == current_user.user_id)
        .all()
    }

    result = []
    for e in rows:
        submission = submissions.get(e.exam_id)
        released = bool(submission and submission.scores_released)
        result.append({
            "id": e.exam_id,
            "classId": e.class_id,
            "title": e.exam_title,
            "subject": e.exam_subject,
            "date": e.exam_date.isoformat() if e.exam_date else None,
            "time": e.start_time.strftime("%H:%M") if e.start_time else None,
            "status": e.status.value if hasattr(e.status, "value") else str(e.status),
            "totalItems": e.total_items or 0,
            "submitted": bool(submission and submission.submitted_at),
            "locked": bool(submission and submission.locked_for_student()),
            "scoresReleased": released,
            "finalScore": float(submission.final_score) if released and submission.final_score is not None else None,
            "maxScore": float(submission.max_score) if released and submission.max_score is not None else None,
        })
    return result


@router.get("/exams/{exam_id}")
def get_student_exam(exam_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_student(current_user)
    exam = _enrolled_exam(db, exam_id, current_user)
    questions = []
    for q in exam.questions:
        item = {
            "id": q.question_id,
            "number": q.question_number,
            "type": q.question_type.value if hasattr(q.question_type, "value") else str(q.question_type),
            "question": q.question_text,
            "points": float(q.points or 0),
        }
        if q.question_type == QuestionType.MCQ:
            item["options"] = [q.option_a or "", q.option_b or "", q.option_c or "", q.option_d or "", q.option_e or ""]
        questions.append(item)

    submission = db.query(ExamSubmission).filter(
        ExamSubmission.exam_id == exam_id,
        ExamSubmission.student_id == current_user.user_id,
    ).first()

    return {
        "id": exam.exam_id,
        "classId": exam.class_id,
        "title": exam.exam_title,
        "subject": exam.exam_subject,
        "date": exam.exam_date.isoformat() if exam.exam_date else None,
        "time": exam.start_time.strftime("%H:%M") if exam.start_time else None,
        "status": exam.status.value if hasattr(exam.status, "value") else str(exam.status),
        "totalItems": exam.total_items or 0,
        "totalPoints": float(exam.total_points or 0),
        "questions": questions,
        "submission": _submission_summary(submission),
    }


@router.get("/exams/{exam_id}/result")
def get_student_result(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The student's own scored result for one examination.

    Until the professor releases the score this returns the submission state
    only, with ``released: false`` and no numbers. That gate is enforced here
    on the server rather than in the UI, so a student cannot read an unreleased
    grade by calling the API directly.
    """
    _require_student(current_user)
    exam = _enrolled_exam(db, exam_id, current_user)

    submission = db.query(ExamSubmission).filter(
        ExamSubmission.exam_id == exam_id,
        ExamSubmission.student_id == current_user.user_id,
    ).first()

    base = {
        "examId": exam.exam_id,
        "classId": exam.class_id,
        "examTitle": exam.exam_title,
        "subject": exam.exam_subject,
        "submitted": bool(submission and submission.submitted_at),
        "released": bool(submission and submission.scores_released),
        "submission": _submission_summary(submission),
    }

    if not submission:
        return {**base, "message": "You have not uploaded an answer sheet for this examination yet."}

    if not submission.scores_released:
        status_value = (
            submission.submission_status.value
            if hasattr(submission.submission_status, "value")
            else str(submission.submission_status)
        )
        if status_value == "Failed":
            message = (
                "We ran into a problem processing your answer sheet. This has been "
                "recorded and your professor can re-scan it for you — no action is "
                "needed from you."
            )
        elif status_value in ("Uploaded", "OCR_Processing", "NLP_Processing"):
            message = (
                "Your answer sheet has been received and is being scanned and graded "
                "right now. Check back in a moment."
            )
        else:
            message = (
                "Your answer sheet has been received. Your score will appear here "
                "once your professor releases it."
            )
        return {**base, "message": message}

    mcqs, essays = split_questions(db, exam_id)
    rows = {
        row.question_id: row
        for row in db.query(SubmissionAnswer)
        .filter(SubmissionAnswer.submission_id == submission.submission_id)
        .all()
    }

    mcq_items = []
    mcq_max = 0.0
    for q in mcqs:
        points = float(q.points or 0)
        mcq_max += points
        row = rows.get(q.question_id)
        selected = row.selected_option if row else None
        is_blank = bool(row.is_blank) if row else True
        is_ambiguous = bool(row.is_ambiguous) if row else False
        correct = bool(
            row and not is_blank and not is_ambiguous and selected and q.correct_option
            and selected.strip().upper() == q.correct_option.strip().upper()
        )
        mcq_items.append({
            "questionId": q.question_id,
            "questionNumber": q.question_number,
            "questionText": q.question_text,
            "points": points,
            "earned": points if correct else 0.0,
            "selectedOption": selected,
            # The answer key is revealed only after release, which is exactly
            # what makes releasing a deliberate decision for the professor.
            "correctOption": q.correct_option,
            "isBlank": is_blank,
            "isAmbiguous": is_ambiguous,
            "isCorrect": correct,
        })

    essay_items = []
    essay_max = 0.0
    for q in essays:
        points = float(q.points or 0)
        essay_max += points
        row = rows.get(q.question_id)
        feedback = {}
        if row and row.feedback_json:
            try:
                feedback = json.loads(row.feedback_json)
            except (TypeError, ValueError):
                feedback = {}

        earned = row.effective_score if row else None
        essay_items.append({
            "questionId": q.question_id,
            "questionNumber": q.question_number,
            "questionText": q.question_text,
            "points": points,
            "earned": float(earned) if earned is not None else None,
            "answerText": row.answer_text if row else None,
            "wasAdjusted": bool(row and row.is_overridden),
            "feedbackSummary": feedback.get("summary"),
            # Criterion values are shown as percentages so a student can see
            # where marks went without exposing internal weighting decisions.
            "criteria": [
                {
                    "label": c.get("label"),
                    "color": c.get("color"),
                    "value": c.get("value"),
                }
                for c in (feedback.get("criteria") or [])
                if c.get("counted", True)
            ],
        })

    return {
        **base,
        "finalScore": float(submission.final_score) if submission.final_score is not None else None,
        "maxScore": float(submission.max_score) if submission.max_score is not None else round(mcq_max + essay_max, 2),
        "mcq": {
            "available": bool(mcqs),
            "score": float(submission.mcq_score) if submission.mcq_score is not None else None,
            "maxScore": round(mcq_max, 2) if mcqs else None,
            "questions": mcq_items,
        },
        "essay": {
            "available": bool(essays),
            "score": float(submission.essay_score) if submission.essay_score is not None else None,
            "maxScore": round(essay_max, 2) if essays else None,
            "questions": essay_items,
        },
        "releasedAt": submission.released_at,
    }


@router.post("/exams/{exam_id}/upload")
async def upload_student_answer_sheet(
    exam_id: int,
    background_tasks: BackgroundTasks,
    page1: UploadFile | None = File(None),
    essay_pages: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload and process the student's own answer sheet.

    A student gets exactly one submission. Once the sheet has been accepted
    the record is locked and any further upload is rejected with 409; only
    the professor can replace it from the professor upload screen. This is
    what stops a student from re-scanning until they like the score.

    Grading (OMR/OCR/NLP) runs in the background after this request returns,
    so the student is not stuck watching a spinner while it completes.
    """
    _require_student(current_user)
    exam = _enrolled_exam(db, exam_id, current_user)
    essay_pages = [f for f in essay_pages if f is not None]

    submission = db.query(ExamSubmission).filter(
        ExamSubmission.exam_id == exam_id,
        ExamSubmission.student_id == current_user.user_id,
    ).first()

    if submission and submission.locked_for_student():
        raise HTTPException(
            status_code=409,
            detail=(
                "You have already submitted and processed your answer sheet for this "
                "examination. If something is wrong with it, please ask your professor "
                "to re-scan it for you."
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
            detail=f"This examination has more than {MAX_MCQ_PER_PAGE} multiple-choice questions and cannot be processed automatically. Please contact your professor.",
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

    student_base = student_file_base(current_user.first_name, current_user.last_name, current_user.user_id)
    saved_paths, essay_saved_paths = write_pages(
        UPLOAD_ROOT, exam_id, current_user.user_id, student_base, pages
    )

    if not submission:
        submission = ExamSubmission(exam_id=exam_id, student_id=current_user.user_id)
        db.add(submission)
        db.flush()

    # Locked immediately, before grading runs, so a second tap during
    # processing is rejected right away instead of racing the background
    # task. The heavy work (scanner, OMR, EasyOCR, Ollama, spaCy) runs in
    # the background — the student does not sit on a spinner while it
    # completes, and their result page shows "processing" until it does.
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

    # The response deliberately carries no scores: the student sees nothing
    # until their professor releases the result.
    return json_safe({
        "message": (
            "Answer sheet received and is being processed. Your score will be "
            "available once your professor releases it."
        ),
        "submissionId": submission.submission_id,
        "filename": submission.student_filename,
        "status": submission.submission_status.value,
        "locked": True,
        "processing": True,
        "scoresReleased": bool(submission.scores_released),
    })
