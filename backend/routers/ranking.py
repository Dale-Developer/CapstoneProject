from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.class_model import Class
from models.enrollment import Enrollment
from models.exam import Exam
from models.exam_submission import ExamSubmission, SubmissionStatus
from models.user import User
from services.auth_service import get_current_user

router = APIRouter(prefix="/api/ranking", tags=["ranking"])

@router.get("")
def get_ranking(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role.value != "Professor":
        return []

    class_rows = db.query(Class).filter(Class.teacher_id == current_user.user_id).all()
    class_ids = [c.class_id for c in class_rows]
    class_map = {c.class_id: c for c in class_rows}
    if not class_ids:
        return []

    enrollments = db.query(Enrollment).filter(Enrollment.class_id.in_(class_ids)).all()
    student_ids = sorted({e.student_id for e in enrollments})
    if not student_ids:
        return []

    exams = db.query(Exam).filter(Exam.teacher_id == current_user.user_id).all()
    exam_map = {e.exam_id: e for e in exams}

    submissions = (
        db.query(ExamSubmission)
        .filter(
            ExamSubmission.exam_id.in_(list(exam_map.keys()) or [-1]),
            ExamSubmission.student_id.in_(student_ids),
            ExamSubmission.submission_status == SubmissionStatus.Graded,
            ExamSubmission.final_score.isnot(None),
        )
        .all()
    )

    grouped = defaultdict(list)
    for s in submissions:
        grouped[s.student_id].append(float(s.final_score))

    users = db.query(User).filter(User.user_id.in_(student_ids)).all()
    user_map = {u.user_id: u for u in users}
    # Choose the student's first enrolled class for display.
    student_class = {}
    for e in enrollments:
        student_class.setdefault(e.student_id, e.class_id)

    rows = []
    for sid in student_ids:
        u = user_map.get(sid)
        if not u:
            continue
        scores = grouped.get(sid, [])
        avg = sum(scores) / len(scores) if scores else 0.0
        cid = student_class.get(sid)
        cls = class_map.get(cid)
        rows.append({
            "id": sid,
            "name": f"{u.first_name} {u.last_name}",
            "studentId": str(sid),
            "className": cls.class_name if cls else "—",
            "section": cls.section if cls and cls.section else "—",
            "examsCompleted": len(scores),
            "average": round(avg, 1),
            "trend": 0.0,
        })

    rows.sort(key=lambda x: (-x["average"], x["name"].lower()))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows
