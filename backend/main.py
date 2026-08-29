from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from sqlalchemy import inspect, text
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from services.runtime import configure_threads, start_warmup, warmup_state

from models import (
    User,
    Class,
    Enrollment,
    Exam,
    ExamQuestion,
    ExamRubric,
    ExamSubmission,
    SubmissionAnswer,
)

from routers import (
    auth,
    classes,
    exams,
    ranking,
    uploads,
    profile,
    student,
)


# ============================================================
# DATABASE
# ============================================================

# Create any missing tables based on the current SQLAlchemy
# models.
#
# The database should already have the corrected schema from
# the SQL script. This only creates tables that do not exist.
Base.metadata.create_all(bind=engine)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the heavy models once, at startup, instead of mid-request.

    EasyOCR V5.2, spaCy and the Ollama vision model together take tens of
    seconds to become ready. Previously that cost landed on whoever happened
    to upload first after a restart. Warmup runs in a background thread so
    the API starts accepting requests immediately and simply gets faster a
    few seconds later.
    """
    configure_threads()
    start_warmup(background=True)
    yield


app = FastAPI(
    title="ESSCAN API",
    version="7.9.0",
    lifespan=lifespan,
)


# ============================================================
# CORS
# ============================================================

# Origins come from CORS_ALLOWED_ORIGINS (comma-separated) so dev, staging
# and production never require a code change — only a different .env value.
# The three dev defaults below only apply if that variable is unset, so
# nothing breaks for existing local setups.
_default_dev_origins = "http://localhost:5173,http://127.0.0.1:5173,http://192.168.1.20:5173"
origins = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", _default_dev_origins).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTERS
# ============================================================

app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(exams.router)
app.include_router(ranking.router)
app.include_router(uploads.router)
app.include_router(profile.router)
app.include_router(student.router)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "ESSCAN API",
        "version": "7.9.0",
    }


@app.get("/api/health/ai")
def ai_health():
    """Readiness of every AI component, including model warmup progress.

    Useful when a first upload feels slow: it shows whether EasyOCR, spaCy
    and Ollama have finished loading or are still warming up.
    """
    from services.nlp_spacy import status as nlp_status
    from services.ocr_hybrid import easyocr_available, easyocr_error, ollama_available, ollama_error
    from services.omr import available as omr_available

    return {
        "warmup": warmup_state(),
        "easyocr": {"available": easyocr_available(), "error": easyocr_error()},
        "ollama": {"available": ollama_available(), "error": ollama_error()},
        "omr": {"available": omr_available()},
        **nlp_status(),
    }