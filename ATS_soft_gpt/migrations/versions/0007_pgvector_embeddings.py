"""Add pgvector columns for candidate and job embeddings.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # The original baseline predates jobs, CV documents, offer structures, and profile indexes. Create
    # any missing current tables so a fresh `alembic upgrade head` results in a complete application schema.
    from app.models import Base
    Base.metadata.create_all(bind)
    inspector = inspect(bind)
    if "ai_enabled" not in {column["name"] for column in inspector.get_columns("organizations")}:
        op.add_column("organizations", sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "next_job" not in {column["name"] for column in inspector.get_columns("org_counters")}:
        op.add_column("org_counters", sa.Column("next_job", sa.Integer(), nullable=False, server_default="1"))
    inspector = inspect(bind)
    from app.vector_type import EmbeddingVector
    for table in ("candidate_profiles", "jobs"):
        if "embedding_vector" not in {column["name"] for column in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("embedding_vector", EmbeddingVector(384), nullable=True))
    if bind.dialect.name == "postgresql":
        # Existing releases stored normalized float32 bytes. Convert those in-place so rollout keeps CVs indexed.
        for table in ("candidate_profiles", "jobs"):
            rows = bind.execute(sa.text(f"SELECT id, embedding FROM {table} WHERE embedding IS NOT NULL")).all()
            for row_id, raw in rows:
                if raw is None or len(raw) != 384 * 4:
                    continue
                vals = __import__("numpy").frombuffer(raw, dtype="<f4")
                literal = "[" + ",".join(format(float(v), ".9g") for v in vals) + "]"
                bind.execute(sa.text(f"UPDATE {table} SET embedding_vector = CAST(:v AS vector) WHERE id = :id"),
                             {"v": literal, "id": row_id})
        # HNSW accelerates cosine distance scans. Keep NULL/unindexed rows out of the index.
        op.execute("CREATE INDEX IF NOT EXISTS ix_candidate_profiles_embedding_hnsw ON candidate_profiles USING hnsw (embedding_vector vector_cosine_ops) WHERE embedding_vector IS NOT NULL")
        op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_embedding_hnsw ON jobs USING hnsw (embedding_vector vector_cosine_ops) WHERE embedding_vector IS NOT NULL")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_candidate_profiles_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS ix_jobs_embedding_hnsw")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("embedding_vector")
    with op.batch_alter_table("candidate_profiles") as batch:
        batch.drop_column("embedding_vector")
    for table, column in (("org_counters", "next_job"), ("organizations", "ai_enabled")):
        if column in {item["name"] for item in inspect(bind).get_columns(table)}:
            op.drop_column(table, column)
