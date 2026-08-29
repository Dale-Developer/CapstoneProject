import enum

from sqlalchemy import Column, Integer, Enum, DECIMAL, ForeignKey, TIMESTAMP, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class AnswerProcessingStatus(str, enum.Enum):
    Pending = "Pending"
    Detected = "Detected"
    Confirmed = "Confirmed"
    Ambiguous = "Ambiguous"
    Blank = "Blank"
    Graded = "Graded"
    Overridden = "Overridden"


class SubmissionAnswer(Base):
    __tablename__ = "submission_answers"
    __table_args__ = (
        UniqueConstraint("submission_id", "question_id", name="uq_submission_question"),
    )

    answer_id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("exam_submissions.submission_id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("exam_questions.question_id", ondelete="CASCADE"), nullable=False, index=True)
    selected_option = Column(String(1), nullable=True)
    processing_status = Column(Enum(AnswerProcessingStatus), default=AnswerProcessingStatus.Pending, nullable=False)
    is_blank = Column(Integer, nullable=False, default=0)
    is_ambiguous = Column(Integer, nullable=False, default=0)
    confidence = Column(DECIMAL(6, 4), nullable=True)
    best_fill_ratio = Column(DECIMAL(7, 4), nullable=True)
    second_fill_ratio = Column(DECIMAL(7, 4), nullable=True)
    option_measurements = Column(Text, nullable=True)

    # ---- Essay answers -------------------------------------------------
    # OCR transcription of the handwritten answer for this question.
    answer_text = Column(Text, nullable=True)
    # Score produced by the spaCy/NLP grader.
    auto_score = Column(DECIMAL(6, 2), nullable=True)
    # Professor's manual override. NULL means "no override, use auto_score".
    # This is deliberately a separate column so the original AI score is
    # never destroyed and the override can be undone.
    override_score = Column(DECIMAL(6, 2), nullable=True)
    override_reason = Column(Text, nullable=True)
    overridden_by = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    overridden_at = Column(TIMESTAMP, nullable=True)
    max_score = Column(DECIMAL(6, 2), nullable=True)
    # Full criterion breakdown from essay_grader.grade_answer().
    feedback_json = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP, nullable=True)

    submission = relationship("ExamSubmission", back_populates="answers")
    question = relationship("ExamQuestion")

    @property
    def effective_score(self) -> float | None:
        """The score that actually counts: the override if set, else the AI score."""
        if self.override_score is not None:
            return float(self.override_score)
        if self.auto_score is not None:
            return float(self.auto_score)
        return None

    @property
    def is_overridden(self) -> bool:
        return self.override_score is not None
