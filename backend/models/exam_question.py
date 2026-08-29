import enum

from sqlalchemy import Column, Integer, String, Text, DECIMAL, ForeignKey, TIMESTAMP, func, Enum
from sqlalchemy.orm import relationship

from database import Base


class QuestionType(str, enum.Enum):
    MCQ = "MCQ"
    Essay = "Essay"


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    question_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.exam_id", ondelete="CASCADE"), nullable=False, index=True)
    question_number = Column(Integer, nullable=False)
    question_type = Column(Enum(QuestionType), nullable=False)
    question_text = Column(Text, nullable=False)
    option_a = Column(Text, nullable=True)
    option_b = Column(Text, nullable=True)
    option_c = Column(Text, nullable=True)
    option_d = Column(Text, nullable=True)
    option_e = Column(Text, nullable=True)
    correct_option = Column(String(1), nullable=True)
    answer_key = Column(Text, nullable=True)
    points = Column(DECIMAL(6, 2), nullable=False, default=1)

    # Stored as JSON text so the database remains compatible with the
    # existing MariaDB/MySQL schema while supporting multiple values.
    key_concepts = Column(Text, nullable=True)
    keywords = Column(Text, nullable=True)
    requirements = Column(Text, nullable=True)
    expected_response_format = Column(String(50), nullable=False, default="one_paragraph")

    created_at = Column(TIMESTAMP, server_default=func.now())

    exam = relationship("Exam", back_populates="questions")
    rubrics = relationship(
        "ExamRubric",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="ExamRubric.criterion_order",
    )
