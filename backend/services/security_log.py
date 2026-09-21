"""Writing to the security log.

``record_event`` uses its own database session on purpose. A logging problem
must never break the action being logged (a full disk should not stop someone
signing in), and a failed sign-in has to be recorded even though the request
itself ends in an error.
"""
from __future__ import annotations

import logging

from fastapi import Request

from database import SessionLocal
from models.security_log import SecurityLog

logger = logging.getLogger("esscan.security")

# Event types the admin Security page has labels for.
LOGIN_SUCCESS = "login_success"
LOGIN_FAILED = "login_failed"
USER_CREATED = "user_created"
USER_DELETED = "user_deleted"
ROLE_CHANGED = "role_changed"
PASSWORD_RESET = "password_reset"


def _clip(value, limit: int):
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def client_ip(request: Request | None) -> str | None:
    """The address the connection came from.

    Deliberately ignores X-Forwarded-For: any client can send that header, so
    trusting it would let someone write whatever address they like into the
    log. If this is ever put behind a reverse proxy, configure uvicorn
    --forwarded-allow-ips so request.client is corrected safely instead.
    """
    if request is None or request.client is None:
        return None
    return request.client.host


def record_event(
    event_type: str,
    *,
    request: Request | None = None,
    success: bool = True,
    user_id: int | None = None,
    email: str | None = None,
    detail: str | None = None,
) -> None:
    try:
        agent = request.headers.get("user-agent") if request is not None else None
        db = SessionLocal()
        try:
            db.add(SecurityLog(
                event_type=event_type,
                success=success,
                user_id=user_id,
                actor_email=_clip(email, 150),
                ip_address=_clip(client_ip(request), 45),
                user_agent=_clip(agent, 255),
                detail=_clip(detail, 500),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - logging must never break the request
        logger.exception("Could not write security log entry %r", event_type)