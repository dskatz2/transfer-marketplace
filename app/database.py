import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.schema import CreateColumn


def _resolve_database_url() -> str:
    # Vercel's native Postgres integration (Neon-backed) sets POSTGRES_URL.
    # A generic DATABASE_URL covers Neon/Supabase/etc used standalone.
    url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
    if not url:
        if os.environ.get("VERCEL"):
            # Vercel's filesystem is read-only outside /tmp, so a SQLite
            # fallback here can only fail - raise something legible instead
            # of letting it crash three layers deep inside SQLAlchemy.
            raise RuntimeError(
                "No POSTGRES_URL or DATABASE_URL environment variable is set. "
                "Add one in Vercel's Project Settings -> Environment Variables "
                "(scoped to this environment) and redeploy."
            )
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


def run_lightweight_migrations() -> None:
    """No Alembic here - this app's schema is small enough that a simple
    "add any column the model has but the live table doesn't" pass covers
    every change so far. Only ever ADDs nullable columns; never drops or
    alters existing ones. Safe to call on every startup."""
    inspector = inspect(engine)
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue  # brand-new table - create_all() already handles this
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))
