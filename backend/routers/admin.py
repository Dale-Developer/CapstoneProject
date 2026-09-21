"""Administration API.

Every route here is behind ``require_admin``, applied once at the router
level rather than per-endpoint so a new route cannot accidentally ship
unguarded.

Deliberate limits, because an admin account is a standing risk and not just
a convenience:

* An admin cannot change their own role or delete themselves, so the system
  can never be locked out by one careless click.
* The last remaining admin cannot be demoted or deleted.
* Deleting a professor who still owns classes is refused, because it would
  orphan their exams and every submission attached to them.
* Nothing here returns a password hash, and nothing reads student answers.
  Administration is account management and service health; it is not a way
  to read exam content, and keeping that boundary visible in the code is
  what stops it eroding later.

Every mutation is written to the ``esscan.admin`` logger with the acting
account, and to the ``security_log`` table so it shows up on the admin
Security page.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import get_db
from models.class_model import Class
from models.enrollment import Enrollment
from models.exam import Exam
from models.exam_submission import ExamSubmission
from models.security_log import SecurityLog
from models.user import User, UserRole
from schemas.user import (
    DB_TO_FRONTEND_ROLE,
    FRONTEND_TO_DB_ROLE,
    AdminPasswordReset,
    AdminRoleChange,
    AdminUserCreate,
)
from services.auth_service import hash_password, require_admin
from services.security_log import (
    PASSWORD_RESET,
    ROLE_CHANGED,
    USER_CREATED,
    USER_DELETED,
    record_event,
)

logger = logging.getLogger("esscan.admin")

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _role_out(role) -> str:
    value = role.value if hasattr(role, "value") else str(role)
    return DB_TO_FRONTEND_ROLE.get(value, value)


def _user_out(user: User, db: Session | None = None) -> dict:
    out = {
        "id": user.user_id,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "name": f"{user.first_name} {user.last_name}".strip(),
        "email": user.email,
        "role": _role_out(user.role),
        "createdAt": user.created_at,
    }
    if db is not None:
        out["classesTaught"] = db.query(Class).filter(
            Class.teacher_id == user.user_id).count()
        out["classesEnrolled"] = db.query(Enrollment).filter(
            Enrollment.student_id == user.user_id).count()
        out["submissions"] = db.query(ExamSubmission).filter(
            ExamSubmission.student_id == user.user_id).count()
    return out


def _admin_count(db: Session) -> int:
    return db.query(User).filter(User.role == UserRole.Admin).count()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Counts and recent activity for the admin dashboard."""
    week_ago = datetime.now() - timedelta(days=7)
    by_role = dict(
        db.query(User.role, func.count(User.user_id)).group_by(User.role).all()
    )

    return {
        "users": {
            "total": sum(by_role.values()),
            "professors": by_role.get(UserRole.Professor, 0),
            "students": by_role.get(UserRole.Student, 0),
            "admins": by_role.get(UserRole.Admin, 0),
            "newThisWeek": db.query(User).filter(User.created_at >= week_ago).count(),
        },
        "content": {
            "classes": db.query(Class).count(),
            "exams": db.query(Exam).count(),
            "submissions": db.query(ExamSubmission).count(),
            "submissionsThisWeek": db.query(ExamSubmission).filter(
                ExamSubmission.submitted_at >= week_ago).count(),
        },
    }


@router.get("/system")
def system_health(_: User = Depends(require_admin)):
    """Live status of every AI component and the settings driving OCR.

    The same data as /api/health/ai, plus the recognition configuration --
    which matters because a scan that reads badly is far more often a
    misconfigured threshold than a broken model, and this is where an
    administrator can see both at once.
    """
    from services.nlp_spacy import status as nlp_status
    from services.ocr_hybrid import (
        easyocr_available, easyocr_error, last_ollama_error,
        ollama_available, ollama_error,
    )
    from services.omr import available as omr_available
    from services.runtime import warmup_state

    from services.auth_service import SECRET_KEY_IS_CONFIGURED

    return {
        "warmup": warmup_state(),
        # Surfaced here because a placeholder signing key is invisible from
        # the outside: logins work, sessions work, and anyone who has read the
        # repository can mint an admin token.
        "security": {"jwtSecretConfigured": SECRET_KEY_IS_CONFIGURED},
        "easyocr": {
            "available": easyocr_available(),
            "error": easyocr_error(),
            "network": os.getenv("EASYOCR_RECOG_NETWORK", "handwriting_finetune_v5_2"),
            "gpu": os.getenv("EASYOCR_GPU", "0") not in ("0", "", "false"),
        },
        "ollama": {
            "available": ollama_available(),
            "error": ollama_error(),
            "model": os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b"),
            "baseUrl": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "verifyEnabled": os.getenv("OLLAMA_OCR_VERIFY", "true").lower()
            in ("1", "true", "yes", "on"),
            "lastError": last_ollama_error(),
        },
        "omr": {"available": omr_available()},
        "nlp": nlp_status(),
        "ocrSettings": {
            "decoder": os.getenv("OCR_DECODER", "beamsearch"),
            "targetWidth": os.getenv("OCR_TARGET_WIDTH", "2200"),
            "canvasSize": os.getenv("OCR_CANVAS_SIZE", "3200"),
            "variants": os.getenv("OCR_MULTIPASS_VARIANTS", "original,clahe"),
            "minPlausibility": os.getenv("OCR_MIN_PLAUSIBILITY", "0.80"),
            "essayVerifyBelow": os.getenv("OLLAMA_ESSAY_MIN_CONFIDENCE", "0.72"),
        },
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users")
def list_users(
    search: str | None = Query(None, description="Matches name or email."),
    role: str | None = Query(None, description="student | teacher | admin"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(User)
    if role:
        db_role = FRONTEND_TO_DB_ROLE.get(role)
        if db_role is None:
            raise HTTPException(status_code=422, detail="Unknown role filter.")
        query = query.filter(User.role == UserRole(db_role))
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(or_(
            User.first_name.like(like),
            User.last_name.like(like),
            User.email.like(like),
        ))
    users = query.order_by(User.role, User.last_name, User.first_name).all()
    return {"users": [_user_out(u, db) for u in users], "total": len(users)}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="That email is already registered.")

    user = User(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole(FRONTEND_TO_DB_ROLE[payload.role]),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.warning("admin %s created %s account %s", actor.email, payload.role, user.email)
    record_event(
        USER_CREATED, request=request, user_id=actor.user_id, email=actor.email,
        detail=f"Created {payload.role} account {user.email}",
    )
    return _user_out(user, db)


@router.put("/users/{user_id}/role")
def change_role(
    user_id: int,
    payload: AdminRoleChange,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No such user.")

    if user.user_id == actor.user_id:
        raise HTTPException(
            status_code=422,
            detail="You cannot change your own role. Ask another administrator.",
        )

    target = UserRole(FRONTEND_TO_DB_ROLE[payload.role])
    was = user.role.value if hasattr(user.role, "value") else str(user.role)

    if was == "Admin" and target != UserRole.Admin and _admin_count(db) <= 1:
        raise HTTPException(
            status_code=422,
            detail="This is the only administrator. Promote someone else first.",
        )

    if was == "Professor" and target != UserRole.Professor:
        taught = db.query(Class).filter(Class.teacher_id == user.user_id).count()
        if taught:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{user.email} still teaches {taught} class(es). Reassign or "
                    "delete those first, or their exams will be unreachable."
                ),
            )

    user.role = target
    db.commit()
    logger.warning("admin %s changed %s: %s -> %s", actor.email, user.email, was, target.value)
    record_event(
        ROLE_CHANGED, request=request, user_id=actor.user_id, email=actor.email,
        detail=f"{user.email}: {was} -> {target.value}",
    )
    return {
        **_user_out(user, db),
        "message": (
            f"{user.email} is now a {payload.role}. They must sign out and back "
            "in, because the role is carried in their access token."
        ),
    }


@router.put("/users/{user_id}/password")
def reset_password(
    user_id: int,
    payload: AdminPasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No such user.")
    user.password_hash = hash_password(payload.password)
    db.commit()
    logger.warning("admin %s reset the password for %s", actor.email, user.email)
    record_event(
        PASSWORD_RESET, request=request, user_id=actor.user_id, email=actor.email,
        detail=f"Reset password for {user.email}",
    )
    return {
        "id": user.user_id,
        "email": user.email,
        "message": (
            "Password reset. Give it to them over a channel they already "
            "trust, and have them change it after signing in."
        ),
    }


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No such user.")

    if user.user_id == actor.user_id:
        raise HTTPException(status_code=422, detail="You cannot delete your own account.")

    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "Admin" and _admin_count(db) <= 1:
        raise HTTPException(
            status_code=422,
            detail="This is the only administrator. Promote someone else first.",
        )

    taught = db.query(Class).filter(Class.teacher_id == user.user_id).count()
    if taught:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{user.email} still teaches {taught} class(es). Deleting them "
                "would orphan those exams and every submission in them."
            ),
        )

    submissions = db.query(ExamSubmission).filter(
        ExamSubmission.student_id == user.user_id).count()
    email = user.email
    db.delete(user)
    db.commit()
    logger.warning(
        "admin %s DELETED %s (%s, %d submission(s))", actor.email, email, role, submissions
    )
    record_event(
        USER_DELETED, request=request, user_id=actor.user_id, email=actor.email,
        detail=f"Deleted {role} account {email}"
        + (f" and {submissions} submission(s)" if submissions else ""),
    )
    return {
        "deleted": True,
        "email": email,
        "message": f"Deleted {email}."
        + (f" {submissions} submission(s) were removed with them." if submissions else ""),
    }


# ---------------------------------------------------------------------------
# Security log
# ---------------------------------------------------------------------------

def _iso_utc(value: datetime | None) -> str | None:
    """ISO 8601 with a trailing Z, so the browser knows the value is UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/security-log")
def security_log(
    search: str | None = Query(None, description="Matches email, IP address or details."),
    event_type: str | None = Query(None, alias="type", description="e.g. login_failed"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Security events, newest first."""
    query = db.query(SecurityLog)
    if event_type:
        query = query.filter(SecurityLog.event_type == event_type)
    if search and search.strip():
        term = search.strip()
        query = query.filter(or_(
            SecurityLog.actor_email.contains(term, autoescape=True),
            SecurityLog.ip_address.contains(term, autoescape=True),
            SecurityLog.detail.contains(term, autoescape=True),
        ))

    total = query.count()
    rows = (
        query.order_by(SecurityLog.created_at.desc(), SecurityLog.log_id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "events": [
            {
                "id": r.log_id,
                "timestamp": _iso_utc(r.created_at),
                "type": r.event_type,
                "success": bool(r.success),
                "actor": r.actor_email,
                "ip": r.ip_address,
                "detail": r.detail,
            }
            for r in rows
        ],
        "total": total,
    }