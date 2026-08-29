import enum

from sqlalchemy import Column, Integer, String, Date, Time, Enum, DECIMAL, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import relationship

from database import Base


class ExamStatus(str, enum.Enum):
    Draft = "Draft"
    Published = "Published"
    Closed = "Closed"


class Exam(Base):
    __tablename__ = "exams"

    exam_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    class_id = Column(Integer, ForeignKey("classes.class_id", ondelete="CASCADE"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    exam_title = Column(String(200), nullable=False)
    exam_subject = Column(String(150), nullable=False)
    exam_date = Column(Date, nullable=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    status = Column(Enum(ExamStatus), default=ExamStatus.Draft)
    total_items = Column(Integer, default=0)
    total_points = Column(DECIMAL(6, 2), default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    class_ = relationship("Class", back_populates="exams")
    submissions = relationship("ExamSubmission", back_populates="exam", cascade="all, delete-orphan")
    questions = relationship("ExamQuestion", back_populates="exam", cascade="all, delete-orphan", order_by="ExamQuestion.question_number")
    rubrics = relationship("ExamRubric", back_populates="exam", cascade="all, delete-orphan", order_by="ExamRubric.criterion_order")
