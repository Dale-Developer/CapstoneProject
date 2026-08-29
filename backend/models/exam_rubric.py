from sqlalchemy import Column, Integer, String, DECIMAL, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import relationship

from database import Base


class ExamRubric(Base):
    __tablename__ = "exam_rubrics"

    rubric_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.exam_id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(
        Integer,
        ForeignKey("exam_questions.question_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    criterion_order = Column(Integer, nullable=False)
    criterion_name = Column(String(150), nullable=False)
    weight = Column(DECIMAL(6, 2), nullable=False, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())

    exam = relationship("Exam", back_populates="rubrics")
    question = relationship("ExamQuestion", back_populates="rubrics")
