import random
import string

from sqlalchemy.orm import Session

from models.class_model import Class

_ALPHABET = string.ascii_uppercase + string.digits


def _random_code(length: int = 8) -> str:
    return "".join(random.choices(_ALPHABET, k=length))


def generate_unique_class_code(db: Session) -> str:
    """Generates an 8-char alphanumeric code, retrying on the rare collision."""
    for _ in range(10):
        code = _random_code()
        exists = db.query(Class).filter(Class.class_code == code).first()
        if not exists:
            return code
    # Extremely unlikely fallback: widen the code.
    return _random_code(12)
