from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from schemas.profile_schema import PasswordUpdate, ProfileUpdate
from schemas.user import UserResponse
from services.auth_service import get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/profile", tags=["profile"])

@router.get("", response_model=UserResponse)
def get_profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)

@router.put("", response_model=UserResponse)
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = db.query(User).filter(User.email == payload.email, User.user_id != current_user.user_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="That email address is already in use.")
    current_user.first_name = payload.firstName.strip()
    current_user.last_name = payload.lastName.strip()
    current_user.email = payload.email
    db.commit()
    db.refresh(current_user)
    return UserResponse.model_validate(current_user)

@router.put("/password")
def update_password(payload: PasswordUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not verify_password(payload.currentPassword, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    current_user.password_hash = hash_password(payload.newPassword)
    db.commit()
    return {"message": "Password updated successfully."}
