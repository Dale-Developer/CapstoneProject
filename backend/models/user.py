import enum

from sqlalchemy import Column, Integer, String, Enum, TIMESTAMP, func

from database import Base


class UserRole(str, enum.Enum):
    Professor = "Professor"
    Student = "Student"
    # System administrator. Manages accounts and inspects service health; is
    # NOT a professor and owns no classes, so it can never see student work
    # through the normal teaching routes. Added in migration 011 -- the
    # database column is a MySQL ENUM, so the column must be altered before
    # this value can be stored.
    Admin = "Admin"


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    profile_picture = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
