"""Add company owner approval state to generated offer letters.

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("offer_letters") as batch:
        batch.add_column(sa.Column("approval_status", sa.String(length=24), nullable=False,
                                   server_default="approved"))
        batch.add_column(sa.Column("approved_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_offer_letters_approved_by_users", "users", ["approved_by"], ["id"],
                                 ondelete="SET NULL")
    with op.batch_alter_table("offer_letters") as batch:
        batch.alter_column("approval_status", server_default="pending_approval",
                           existing_type=sa.String(length=24), existing_nullable=False)


def downgrade():
    with op.batch_alter_table("offer_letters") as batch:
        batch.drop_constraint("fk_offer_letters_approved_by_users", type_="foreignkey")
        batch.drop_column("approved_at")
        batch.drop_column("approved_by")
        batch.drop_column("approval_status")
