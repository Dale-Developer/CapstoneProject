from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String

from database import Base


def _utc_now() -> datetime:
    # Stored as naive UTC. The column is a DATETIME (no timezone conversion by
    # MySQL), so the value is the same whatever the server timezone is. The
    # API adds the trailing "Z" when it sends it to the browser.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SecurityLog(Base):
    """One security-relevant event: a sign-in, a failed sign-in, an admin action.

    Deliberately has no ForeignKey to ``users``. Deleting an account must not
    delete (or be blocked by) the record that it was deleted, so the actor email
    is copied into the row.
    """

    __tablename__ = "security_log"

    log_id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_type = Column(String(40), nullable=False)
    success = Column(Boolean, nullable=False, default=True)
    user_id = Column(Integer, nullable=True)
    actor_email = Column(String(150), nullable=True, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    detail = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utc_now, index=True)