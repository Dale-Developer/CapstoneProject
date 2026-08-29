from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ClassCreate(BaseModel):
    """Matches CreateClassModal.jsx's onCreate payload."""

    class_name: str = Field(..., alias="className", min_length=1, max_length=150)
    section: Optional[str] = Field(None, max_length=100)
    subject: str = Field(..., min_length=1, max_length=150)
    color: Optional[str] = Field(None, max_length=20)

    model_config = {"populate_by_name": True}


class ClassUpdate(BaseModel):
    class_name: Optional[str] = Field(None, alias="className", max_length=150)
    section: Optional[str] = Field(None, max_length=100)
    subject: Optional[str] = Field(None, max_length=150)
    color: Optional[str] = Field(None, max_length=20)

    model_config = {"populate_by_name": True}


class ExamSummary(BaseModel):
    """Field names here already match what exam-list consumers expect."""

    id: int
    title: str
    date: Optional[str] = None
    submissions: int = 0

    model_config = {"from_attributes": True}


class ClassResponse(BaseModel):
    """Field names here are the frontend-facing shape (Dashboard/index.jsx, ClassView.jsx)."""

    id: int
    title: str  # class_name
    subject: str
    section: Optional[str] = None
    class_code: str = Field(..., alias="classCode")
    color: Optional[str] = None  # cover_color
    students: int = 0
    exams: int = 0
    created_at: datetime

    model_config = {"populate_by_name": True}


class ClassDetailResponse(ClassResponse):
    exam_list: List[ExamSummary] = Field(default_factory=list, alias="examList")

    model_config = {"populate_by_name": True}


class StudentSummary(BaseModel):
    id: int
    name: str
    email: str


class JoinClassRequest(BaseModel):
    class_code: str = Field(..., alias="classCode", min_length=1)

    model_config = {"populate_by_name": True}
