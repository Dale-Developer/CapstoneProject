from pydantic import BaseModel
from typing import List, Optional

class StudentQuestion(BaseModel):
    id: int
    number: int
    type: str
    question: str
    options: Optional[List[str]] = None

class StudentExamResponse(BaseModel):
    id: int
    classId: int
    title: str
    subject: str
    date: Optional[str] = None
    time: Optional[str] = None
    status: str
    totalItems: int
    questions: List[StudentQuestion]
