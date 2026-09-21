import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models.user import User

logger = logging.getLogger(__name__)

# Values that have shipped in .env or as a code default, and are therefore
# public knowledge. A token signed with any of them can be forged by anyone who
# has read this repository: the payload carries the user id and role, so a
# forged admin token is a few lines of script.
_PUBLIC_PLACEHOLDERS = {
    "CHANGE_ME_IN_PRODUCTION",
    "REPLACE_ME_WITH_A_NEW_RANDOM_SECRET",
    "changeme",
    "secret",
    "",
}


def _load_secret_key() -> str:
    """The HS256 signing key, or a random one if none was configured.

    Falling back to a random key rather than a fixed placeholder is the whole
    point. Sessions do not survive a restart, which is a visible nuisance in
    development and exactly the kind that gets fixed; a guessable key is
    invisible and gets deployed.

    Generate a real one with:

        python -c "import secrets; print(secrets.token_urlsafe(48))"

    and set JWT_SECRET_KEY in backend/.env.
    """
    configured = (os.getenv("JWT_SECRET_KEY") or "").strip()
    if configured and configured not in _PUBLIC_PLACEHOLDERS:
        return configured

    logger.warning(
        "JWT_SECRET_KEY is unset or still a placeholder. Signing with a random "
        "key generated for this process: everyone will be logged out whenever "
        "the backend restarts. Set JWT_SECRET_KEY in backend/.env before "
        "hosting this anywhere reachable."
    )
    return secrets.token_urlsafe(48)


SECRET_KEY = _load_secret_key()
SECRET_KEY_IS_CONFIGURED = (
    (os.getenv("JWT_SECRET_KEY") or "").strip() not in _PUBLIC_PLACEHOLDERS
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jose.JWTError if the token is invalid or expired."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# The frontend never actually calls a token endpoint with this scheme (it sends
# JSON, not form data) — we only reuse OAuth2PasswordBearer here so Swagger UI
# gets an "Authorize" button and so requests are checked for a Bearer header.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.user_id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    return user


# ---------------------------------------------------------------------------
# Role guards
# ---------------------------------------------------------------------------
# Every router previously re-implemented its own role check inline. These
# dependencies make the requirement declarative and, more importantly, make
# it impossible to forget: a route that omits the guard is visibly missing
# it, rather than looking identical to a route that happens to check inside
# the body.


def require_role(*allowed: str):
    """Dependency factory: allow only the named DB roles.

    Compares against ``UserRole`` values ("Professor", "Student", "Admin"),
    not the frontend's lowercase aliases.
    """

    def guard(current_user: User = Depends(get_current_user)) -> User:
        role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if role not in allowed:
            # 403, not 404: the caller is authenticated, they simply are not
            # permitted. Hiding that behind a 404 would make legitimate
            # permission problems very hard to debug.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action requires a different role.",
            )
        return current_user

    return guard


require_admin = require_role("Admin")
