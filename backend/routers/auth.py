from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from schemas.user import (
    FRONTEND_TO_DB_ROLE,
    DB_TO_FRONTEND_ROLE,
    Token,
    UserLogin,
    UserRegister,
    UserResponse,
)
from services.auth_service import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from services.security_log import (
    LOGIN_FAILED,
    LOGIN_SUCCESS,
    USER_CREATED,
    record_event,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, request: Request, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    new_user = User(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=FRONTEND_TO_DB_ROLE[payload.role],  # "student"/"teacher" -> "Student"/"Professor"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    record_event(
        USER_CREATED,
        request=request,
        user_id=new_user.user_id,
        email=new_user.email,
        detail=f"Self-registered as {new_user.role.value}",
    )

    access_token = create_access_token(
        data={"sub": str(new_user.user_id), "role": new_user.role.value}
    )
    return Token(access_token=access_token, user=UserResponse.model_validate(new_user))


@router.post("/login", response_model=Token)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        # The response is the same either way so the login form can't be used
        # to discover which emails exist; the log says which it was, because an
        # administrator investigating needs to know.
        record_event(
            LOGIN_FAILED,
            request=request,
            success=False,
            user_id=user.user_id if user else None,
            email=str(payload.email),
            detail="Wrong password" if user else "No account with that email",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    # An administrator may sign in from either tab on the login form. The
    # frontend then routes them to /Admin based on the role in the response,
    # so no extra "Admin" option has to be exposed on a public page -- which
    # would advertise that admin accounts exist and where to attack them.
    if (
        payload.role
        and user.role.value != "Admin"
        and FRONTEND_TO_DB_ROLE[payload.role] != user.role.value
    ):
        record_event(
            LOGIN_FAILED,
            request=request,
            success=False,
            user_id=user.user_id,
            email=user.email,
            detail=f"Correct password, but not registered as {payload.role}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account is not registered under the selected role.",
        )

    record_event(
        LOGIN_SUCCESS, request=request, user_id=user.user_id, email=user.email
    )

    access_token = create_access_token(
        data={"sub": str(user.user_id), "role": user.role.value}
    )
    return Token(access_token=access_token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)