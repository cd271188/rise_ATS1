"""Keep vendor interview history in the candidate's client pipeline.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "ix_interview_candidate_id" not in {i["name"] for i in inspect(bind).get_indexes("interviews")}:
        op.create_index("ix_interview_candidate_id", "interviews", ["candidate_id"])
    if bind.dialect.name == "postgresql":
        # PostgreSQL permits this UPDATE FROM form; the portable per-row fallback handles SQLite.
        op.execute("UPDATE interviews AS i SET org_id = c.org_id FROM candidates AS c "
                   "WHERE c.id = i.candidate_id AND i.org_id <> c.org_id")
    else:
        rows = bind.execute(sa.text("SELECT i.id, c.org_id FROM interviews AS i "
                                    "JOIN candidates AS c ON c.id = i.candidate_id "
                                    "WHERE i.org_id <> c.org_id")).all()
        for interview_id, org_id in rows:
            bind.execute(sa.text("UPDATE interviews SET org_id = :org_id WHERE id = :id"),
                         {"org_id": org_id, "id": interview_id})


def downgrade():
    bind = op.get_bind()
    if "ix_interview_candidate_id" in {i["name"] for i in inspect(bind).get_indexes("interviews")}:
        op.drop_index("ix_interview_candidate_id", table_name="interviews")
