"""store the pasted job description text

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    if "jobs" not in inspect(op.get_bind()).get_table_names():
        # Jobs is introduced in a later schema snapshot; revision 0007 creates it on fresh installs.
        return
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("jd_text", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("jd_text")
