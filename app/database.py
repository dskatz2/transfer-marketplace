import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


def _resolve_database_url() -> str:
    # Vercel's native Postgres integration (Neon-backed) sets POSTGRES_URL.
    # A generic DATABASE_URL covers Neon/Supabase/etc used standalone.
    # Falls back to a local SQLite file when neither is set (local dev).
    url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
    if not url:
        return "sqlite:///./h2a_matcher.db"
    # SQLAlchemy 2.x dropped the bare "postgres://" scheme some providers use.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _resolve_database_url()

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
