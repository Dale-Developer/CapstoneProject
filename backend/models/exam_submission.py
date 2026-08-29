import enum

from sqlalchemy import Boolean, Column, Integer, Enum, DECIMAL, ForeignKey, TIMESTAMP, String, Text
from sqlalchemy.orm import relationship

from database import Base


class SubmissionStatus(str, enum.Enum):
    Pending = "Pending"
    Uploaded = "Uploaded"
    OCR_Processing = "OCR_Processing"
    OCR_Completed = "OCR_Completed"
    NLP_Processing = "NLP_Processing"
    Graded = "Graded"
    Released = "Released"
    # Background processing (OMR/OCR/NLP) raised an exception. The sheet was
    # accepted and is locked, but never produced a score. A professor can
    # inspect processing_metadata_json for the error and re-scan with
    # allow_replace=True.
    Failed = "Failed"


# Once a sheet has reached one of these states it has been through the
# OMR/OCR/NLP pipeline. A student may not replace it; only the owning
# professor can, via an explicit re-scan.
PROCESSED_STATUSES = {
    SubmissionStatus.OCR_Completed,
    SubmissionStatus.NLP_Processing,
    SubmissionStatus.Graded,
    SubmissionStatus.Released,
}


class ExamSubmission(Base):
    __tablename__ = "exam_submissions"

    submission_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.exam_id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    submission_status = Column(Enum(SubmissionStatus), default=SubmissionStatus.Pending)
    final_score = Column(DECIMAL(6, 2), nullable=True)
    submitted_at = Column(TIMESTAMP, nullable=True)
    graded_at = Column(TIMESTAMP, nullable=True)
    mcq_score = Column(DECIMAL(6, 2), nullable=True)
    essay_score = Column(DECIMAL(6, 2), nullable=True)
    max_score = Column(DECIMAL(6, 2), nullable=True)

    # Scores stay invisible to the student until the professor releases them.
    scores_released = Column(Boolean, nullable=False, default=False)
    released_at = Column(TIMESTAMP, nullable=True)
    released_by = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Set once the pipeline has run. Blocks a second student upload.
    is_locked = Column(Boolean, nullable=False, default=False)
    processed_at = Column(TIMESTAMP, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    uploaded_by = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    page1_path = Column(String(500), nullable=True)
    page2_path = Column(String(500), nullable=True)
    student_filename = Column(String(255), nullable=True)

    # The essay portion of an answer sheet can span any number of pages
    # (2 essay answers per printed page), so essay pages are stored as an
    # ordered JSON list of relative paths rather than a single fixed column.
    essay_pages_json = Column(Text, nullable=True)

    # Raw AI/OCR/OMR outputs are retained for auditability and later grading.
    easyocr_text = Column(Text, nullable=True)
    ollama_text = Column(Text, nullable=True)
    page1_ocr_text = Column(Text, nullable=True)
    page2_ocr_text = Column(Text, nullable=True)
    # Per essay-page OCR text (same order as essay_pages_json), as a JSON list.
    essay_pages_ocr_json = Column(Text, nullable=True)
    combined_ocr_text = Column(Text, nullable=True)
    omr_result_json = Column(Text, nullable=True)
    processing_metadata_json = Column(Text, nullable=True)

    exam = relationship("Exam", back_populates="submissions")
    student = relationship("User", foreign_keys=[student_id])

    answers = relationship("SubmissionAnswer", back_populates="submission", cascade="all, delete-orphan")

    def locked_for_student(self) -> bool:
        """True when the student may no longer replace this submission."""
        return bool(self.is_locked) or self.submission_status in PROCESSED_STATUSES
