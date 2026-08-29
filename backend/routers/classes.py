from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.user import User, UserRole
from models.class_model import Class
from models.enrollment import Enrollment
from models.exam import Exam
from models.exam_submission import ExamSubmission
from schemas.class_schema import (
    ClassCreate,
    ClassUpdate,
    ClassResponse,
    ClassDetailResponse,
    ExamSummary,
    StudentSummary,
    JoinClassRequest,
)
from services.auth_service import get_current_user
from services.code_generator import generate_unique_class_code

router = APIRouter(prefix="/api/classes", tags=["classes"])


def _require_professor(user: User):
    if user.role != UserRole.Professor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only professors can perform this action.",
        )


def _class_counts(db: Session, class_id: int) -> dict:
    students = (
        db.query(func.count(Enrollment.enrollment_id))
        .filter(Enrollment.class_id == class_id)
        .scalar()
        or 0
    )
    exams = (
        db.query(func.count(Exam.exam_id)).filter(Exam.class_id == class_id).scalar() or 0
    )
    return {"students": students, "exams": exams}


def _to_class_response(db: Session, cls: Class) -> ClassResponse:
    counts = _class_counts(db, cls.class_id)
    return ClassResponse(
        id=cls.class_id,
        title=cls.class_name,
        subject=cls.subject,
        section=cls.section,
        classCode=cls.class_code,
        color=cls.cover_color,
        students=counts["students"],
        exams=counts["exams"],
        created_at=cls.created_at,
    )


def _get_owned_class_or_404(db: Session, class_id: int, user: User) -> Class:
    cls = db.query(Class).filter(Class.class_id == class_id).first()
    if not cls:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found.")
    if user.role == UserRole.Professor and cls.teacher_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this class."
        )
    if user.role == UserRole.Student:
        enrolled = (
            db.query(Enrollment)
            .filter(Enrollment.class_id == class_id, Enrollment.student_id == user.user_id)
            .first()
        )
        if not enrolled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="You are not enrolled in this class."
            )
    return cls


@router.get("", response_model=List[ClassResponse])
def list_classes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == UserRole.Professor:
        classes = db.query(Class).filter(Class.teacher_id == current_user.user_id).all()
    else:
        classes = (
            db.query(Class)
            .join(Enrollment, Enrollment.class_id == Class.class_id)
            .filter(Enrollment.student_id == current_user.user_id)
            .all()
        )
    return [_to_class_response(db, c) for c in classes]


@router.post("", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
def create_class(
    payload: ClassCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_professor(current_user)

    new_class = Class(
        teacher_id=current_user.user_id,
        class_name=payload.class_name,
        subject=payload.subject,
        section=payload.section,
        class_code=generate_unique_class_code(db),
        cover_color=payload.color or "#462776",
    )
    db.add(new_class)
    db.commit()
    db.refresh(new_class)
    return _to_class_response(db, new_class)


@router.get("/{class_id}", response_model=ClassDetailResponse)
def get_class(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cls = _get_owned_class_or_404(db, class_id, current_user)
    base = _to_class_response(db, cls)

    exams = db.query(Exam).filter(Exam.class_id == class_id).all()
    exam_summaries: List[ExamSummary] = []
    for exam in exams:
        submission_count = (
            db.query(func.count(ExamSubmission.submission_id))
            .filter(ExamSubmission.exam_id == exam.exam_id)
            .scalar()
            or 0
        )
        exam_summaries.append(
            ExamSummary(
                id=exam.exam_id,
                title=exam.exam_title,
                date=exam.exam_date.isoformat() if exam.exam_date else None,
                submissions=submission_count,
            )
        )

    return ClassDetailResponse(**base.model_dump(by_alias=True), examList=exam_summaries)


@router.put("/{class_id}", response_model=ClassResponse)
def update_class(
    class_id: int,
    payload: ClassUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_professor(current_user)
    cls = _get_owned_class_or_404(db, class_id, current_user)

    if payload.class_name is not None:
        cls.class_name = payload.class_name
    if payload.section is not None:
        cls.section = payload.section
    if payload.subject is not None:
        cls.subject = payload.subject
    if payload.color is not None:
        cls.cover_color = payload.color

    db.commit()
    db.refresh(cls)
    return _to_class_response(db, cls)


@router.get("/{class_id}/students", response_model=List[StudentSummary])
def list_students(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_professor(current_user)
    cls = _get_owned_class_or_404(db, class_id, current_user)

    rows = (
        db.query(User)
        .join(Enrollment, Enrollment.student_id == User.user_id)
        .filter(Enrollment.class_id == cls.class_id)
        .all()
    )
    return [
        StudentSummary(id=u.user_id, name=f"{u.first_name} {u.last_name}", email=u.email)
        for u in rows
    ]


@router.post("/join", response_model=ClassResponse)
def join_class(
    payload: JoinClassRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.Student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only students can join a class."
        )

    cls = db.query(Class).filter(Class.class_code == payload.class_code).first()
    if not cls:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid class code.")

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.class_id == cls.class_id, Enrollment.student_id == current_user.user_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You are already enrolled in this class."
        )

    db.add(Enrollment(class_id=cls.class_id, student_id=current_user.user_id))
    db.commit()
    return _to_class_response(db, cls)
