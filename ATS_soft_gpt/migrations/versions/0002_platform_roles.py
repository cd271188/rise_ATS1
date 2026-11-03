"""platform roles and company suspension

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('is_platform', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('platform_role', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('platform_permissions', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('platform_permissions')
        batch_op.drop_column('platform_role')
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_column('is_platform')
        batch_op.drop_column('is_active')