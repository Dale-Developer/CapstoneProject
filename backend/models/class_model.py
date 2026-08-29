from sqlalchemy import Column, Integer, String, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import relationship

from database import Base


class Class(Base):
    __tablename__ = "classes"

    class_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    teacher_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    class_name = Column(String(150), nullable=False)
    subject = Column(String(150), nullable=False)
    section = Column(String(100), nullable=True)
    class_code = Column(String(20), nullable=False, unique=True, index=True)
    cover_color = Column(String(20), nullable=True, default="#462776")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    teacher = relationship("User")
    enrollments = relationship("Enrollment", back_populates="class_", cascade="all, delete-orphan")
    exams = relationship("Exam", back_populates="class_", cascade="all, delete-orphan")
