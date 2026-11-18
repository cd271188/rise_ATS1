"""Store detected unmapped compensation placeholders on offer structures.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("offer_structures") as batch:
        batch.add_column(sa.Column("unmapped_custom_tags", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("offer_structures") as batch:
        batch.drop_column("unmapped_custom_tags")
