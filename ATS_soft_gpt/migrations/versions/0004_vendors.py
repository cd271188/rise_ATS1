"""vendors: a company can have vendor companies that submit candidates into its pipeline

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_org_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_org_parent', 'organizations', ['parent_org_id'], ['id'])
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vendor_org_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_cand_vendor', 'organizations', ['vendor_org_id'], ['id'])


def downgrade():
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cand_vendor', type_='foreignkey')
        batch_op.drop_column('vendor_org_id')
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_org_parent', type_='foreignkey')
        batch_op.drop_column('parent_org_id')