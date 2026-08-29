from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# The frontend (SignupForm/LoginForm) sends "student" / "teacher".
# The DB enum is "Student" / "Professor". This maps one to the other.
FRONTEND_TO_DB_ROLE = {
    "student": "Student",
    "teacher": "Professor",
}
DB_TO_FRONTEND_ROLE = {v: k for k, v in FRONTEND_TO_DB_ROLE.items()}


class UserRegister(BaseModel):
    """Matches SignupForm.jsx's formData shape."""

    first_name: str = Field(..., alias="firstName", min_length=1, max_length=100)
    last_name: str = Field(..., alias="lastName", min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6)
    confirm_password: str = Field(..., alias="confirmPassword")
    role: str  # "student" | "teacher"

    model_config = {"populate_by_name": True}

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in FRONTEND_TO_DB_ROLE:
            raise ValueError("role must be 'student' or 'teacher'")
        return v

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("passwords do not match")
        return self


class UserLogin(BaseModel):
    """Matches LoginForm.jsx's formData shape."""

    email: EmailStr
    password: str
    role: Optional[str] = None  # optional cross-check against the account's actual role

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v):
        if v in (None, ""):
            return None
        if v not in FRONTEND_TO_DB_ROLE:
            raise ValueError("role must be 'student' or 'teacher'")
        return v


class UserResponse(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    email: EmailStr
    role: str  # returned as "student" / "teacher" to stay consistent with the frontend
    profile_picture: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("role", mode="before")
    @classmethod
    def db_role_to_frontend(cls, v):
        if hasattr(v, "value"):
            v = v.value
        return DB_TO_FRONTEND_ROLE.get(v, v)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
