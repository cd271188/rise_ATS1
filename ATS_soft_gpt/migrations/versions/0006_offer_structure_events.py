"""store offer structure workflow history

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    if "offer_structures" not in inspect(op.get_bind()).get_table_names():
        # The full offer workflow tables are introduced by the schema snapshot in revision 0007.
        return
    with op.batch_alter_table("offer_structures", schema=None) as batch_op:
        batch_op.add_column(sa.Column("events", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("offer_structures", schema=None) as batch_op:
        batch_op.drop_column("events")
