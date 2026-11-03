"""Engine and session factory. SQLite today; any SQLAlchemy URL (e.g. postgresql+psycopg://) works."""
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from . import rls


def make_engine(url: str):
    kwargs = {}
    sqlite = url.startswith("sqlite")
    if sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    else:
        kwargs.update(pool_size=10, max_overflow=10, pool_pre_ping=True)
    engine = create_engine(url, **kwargs)
    if sqlite:
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.close()
    return engine


def create_tables(engine):
    """create_all for a fresh database, plus columns added since an existing database was created (auto-create mode only;
    Alembic installs use the migrations instead)."""
    from .models import Base
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    added = (
        ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("organizations", "parent_org_id", "INTEGER REFERENCES organizations(id)"),
        ("organizations", "ai_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("candidates", "vendor_org_id", "INTEGER REFERENCES organizations(id)"),
        ("org_counters", "next_job", "INTEGER NOT NULL DEFAULT 1"),
        ("cv_documents", "storage_key", "VARCHAR(200)"),
        ("jobs", "client_ref", "VARCHAR(100)"),
        ("jobs", "received_on", "VARCHAR(10)"),
        ("jobs", "jd_filename", "VARCHAR(255)"),
        ("jobs", "jd_mime", "VARCHAR(100)"),
        ("jobs", "jd_size", "INTEGER"),
        ("jobs", "jd_text", "TEXT"),
        ("jobs", "jd_file", "BLOB"),
        ("jobs", "jd_storage_key", "VARCHAR(200)"),
        ("offer_structures", "events", "JSON"),
        ("candidate_profiles", "embedding_vector", "BLOB"),
        ("jobs", "embedding_vector", "BLOB"),
    )
    for table, column, ddl in added:
        if column not in [c["name"] for c in inspect(engine).get_columns(table)]:
            with engine.begin() as conn:
                if engine.dialect.name == "postgresql":
                    ddl = "vector(384)" if column == "embedding_vector" else ddl.replace("BLOB", "BYTEA")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def make_sessionmaker(engine):
    factory = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)
    rls.install(factory)
    return factory
