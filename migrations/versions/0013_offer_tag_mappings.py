"""Store custom offer placeholder to component mappings.

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("offer_structures") as batch:
        batch.add_column(sa.Column("tag_mappings", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("offer_structures") as batch:
        batch.drop_column("tag_mappings")
