from datetime import datetime
from datetime import time as time_of_day
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


# The default professor-facing rubric. Sourced from services.rubric so the
# API, the grading engine and the UI can never drift apart again.
# Keyword/Terminology is deliberately NOT a default criterion: keywords are
# supporting evidence for Key Ideas rather than a separate slice of the score.
from services.rubric import default_rubric_payload

DEFAULT_ESSAY_RUBRIC = default_rubric_payload()

# Every response format the grading engine understands. Previously this field
# was pinned to Literal["one_paragraph"], which silently discarded whatever
# the professor chose.
RESPONSE_FORMATS = (
    "one_word",
    "one_sentence",
    "few_sentences",
    "one_paragraph",
    "multi_paragraph",
    "essay",
)


class MCQQuestionCreate(BaseModel):
    question: str = Field(..., min_length=1)
    options: List[str] = Field(..., min_length=5, max_length=5)
    correctAnswer: int | str | None = None
    points: float = Field(1, gt=0, le=1000)


class RubricCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    weight: float = Field(..., ge=0, le=100)


class EssayQuestionCreate(BaseModel):
    question: str = Field(..., min_length=1)
    answerKey: str = ""
    keyConcepts: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list)
    points: float = Field(1, gt=0, le=1000)
    expectedResponseFormat: Literal[
        "one_word", "one_sentence", "few_sentences",
        "one_paragraph", "multi_paragraph", "essay",
    ] = "one_paragraph"
    rubric: List[RubricCreate] = Field(
        default_factory=lambda: [RubricCreate(**item) for item in DEFAULT_ESSAY_RUBRIC]
    )


class ExamCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(..., min_length=1, max_length=150)
    classIds: List[int] = Field(..., min_length=1)
    mcqQuestions: List[MCQQuestionCreate] = Field(default_factory=list)
    essayQuestions: List[EssayQuestionCreate] = Field(default_factory=list)
    # Kept optional for backward compatibility with older clients/data.
    rubric: List[RubricCreate] = Field(default_factory=list)
    status: str = "Draft"


class ExamUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    subject: Optional[str] = Field(None, min_length=1, max_length=150)
    classIds: Optional[List[int]] = None
    mcqQuestions: Optional[List[MCQQuestionCreate]] = None
    essayQuestions: Optional[List[EssayQuestionCreate]] = None
    rubric: Optional[List[RubricCreate]] = None
    status: Optional[str] = None


class MCQQuestionResponse(BaseModel):
    id: int
    question: str
    options: List[str]
    correctAnswer: Optional[int] = None
    points: float


class RubricResponse(BaseModel):
    id: int
    name: str
    weight: float
    questionId: Optional[int] = None


class EssayQuestionResponse(BaseModel):
    id: int
    question: str
    answerKey: Optional[str] = None
    keyConcepts: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list)
    points: float
    expectedResponseFormat: str = "one_paragraph"
    rubric: List[RubricResponse] = Field(default_factory=list)


class ExamResponse(BaseModel):
    id: int
    classId: int
    className: str
    section: Optional[str] = None
    title: str
    subject: str
    # Retained in the response for compatibility with older screens/data.
    date: Optional[str] = None
    dueDate: Optional[str] = None
    time: Optional[str] = None
    status: str
    totalItems: int
    totalPoints: float
    students: int = 0
    submissions: int = 0
    mcqQuestions: List[MCQQuestionResponse] = Field(default_factory=list)
    essayQuestions: List[EssayQuestionResponse] = Field(default_factory=list)
    # Legacy/unassigned rubric records, if any. New exams store rubrics per essay.
    rubric: List[RubricResponse] = Field(default_factory=list)


class ExamCreateResponse(BaseModel):
    exam: ExamResponse
    createdExamIds: List[int]


class SubmissionResponse(BaseModel):
    id: int
    studentId: int
    studentName: str
    status: str
    score: Optional[float] = None
    submittedAt: Optional[datetime] = None
    maxScore: Optional[float] = None
    mcqScore: Optional[float] = None
    essayScore: Optional[float] = None
    # Whether the student can currently see this score.
    scoresReleased: bool = False
    releasedAt: Optional[datetime] = None
    # True once the pipeline has run, i.e. the student can no longer re-upload.
    locked: bool = False
    # Number of essay answers the professor has manually adjusted.
    overriddenCount: int = 0


class EssayScoreOverride(BaseModel):
    """A professor's manual score for one essay answer.

    ``score`` of None clears the override and restores the AI score, so an
    adjustment is always reversible.
    """
    score: Optional[float] = None
    reason: Optional[str] = None


class ReleaseRequest(BaseModel):
    """Release or un-release scores for a set of students.

    An empty ``studentIds`` means every processed submission for the exam.
    """
    studentIds: Optional[List[int]] = None
    released: bool = True
