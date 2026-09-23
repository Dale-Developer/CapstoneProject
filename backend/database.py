"""
Database connection setup for the ESSCAN backend.

Uses SQLAlchemy with the PyMySQL driver to connect to the MariaDB/MySQL
database `automate_assessment_application`.

All DB credentials come from environment variables (see .env.example).
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
# from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base

# Explicitly the backend directory's .env, not "wherever this was launched
# from". python-dotenv's default search starts at the working directory, so
# starting uvicorn from the project root — which is what systemd units, Docker
# images and most process managers do — found no .env and fell back to every
# default in the codebase. Nothing crashes: the DB password becomes empty,
# SBERT_ENABLED defaults to false so Answer Relevance quietly drops to the
# lexical fallback, and the Ollama timeout reverts to 35s. A hosted instance
# would look like it was working and grade differently.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "automate_assessment_application")

# A full DATABASE_URL wins when it is set. MariaDB/MySQL remains the default
# for normal use; the override exists so the test suite can run against an
# in-memory SQLite database without a database server.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)
# SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL") or URL.create(
#     drivername="mysql+pymysql",
#     username=DB_USER,
#     password=DB_PASSWORD,
#     host=DB_HOST,
#     port=int(DB_PORT),
#     database=DB_NAME,
#     query={"charset": "utf8mb4"},
# )

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
# else:
#     engine = create_engine(
#         SQLALCHEMY_DATABASE_URL,
#         pool_pre_ping=True,  # avoids "MySQL server has gone away" on idle connections
#         pool_recycle=3600,
#     )
else:
    DB_SSL_CA = os.getenv("DB_SSL_CA")

    connect_args = {}

    if DB_SSL_CA:
        connect_args["ssl"] = {
            "ca": DB_SSL_CA
        }

    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=3600,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
