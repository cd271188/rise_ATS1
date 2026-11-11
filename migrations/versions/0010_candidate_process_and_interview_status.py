"""Separate candidate process stage from interview outcome status.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

INTERVIEW_STATUSES = [
    "Selected", "Rejected", "Scheduled", "Re-Scheduled", "To be scheduled",
    "Feedback Pending", "Yet to Offer", "Yet to join", "Joined", "Drop",
]
PROCESSES = ["Screening", "L1 Interview", "L2 Interview", "L3 Interview", "HR Discussion"]
OLD_STATUSES = ["L1 Interview", "L2 Interview", "L3 Interview", "Offer", "Drop",
                "Feedback Pending", "To Be Scheduled", "Scheduled", "Yet to Join"]


def _replace_org_list(bind, name, values):
    bind.execute(sa.text("DELETE FROM list_values WHERE list_name = :name"), {"name": name})
    org_ids = bind.execute(sa.text("SELECT id FROM organizations")).scalars().all()
    for org_id in org_ids:
        bind.execute(
            sa.text("INSERT INTO list_values (org_id, list_name, value, sort_order) VALUES (:org, :name, :value, :order)"),
            [{"org": org_id, "name": name, "value": value, "order": i} for i, value in enumerate(values)],
        )


def upgrade():
    op.add_column("candidates", sa.Column("process", sa.String(length=40), nullable=False,
                                           server_default="Screening"))
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE candidates
        SET process = CASE current_status
            WHEN 'L1 Interview' THEN 'L1 Interview'
            WHEN 'L2 Interview' THEN 'L2 Interview'
            WHEN 'L3 Interview' THEN 'L3 Interview'
            ELSE 'Screening'
        END
    """))
    bind.execute(sa.text("""
        UPDATE interviews
        SET status = CASE status
            WHEN 'L1 Interview' THEN 'To be scheduled'
            WHEN 'L2 Interview' THEN 'To be scheduled'
            WHEN 'L3 Interview' THEN 'To be scheduled'
            WHEN 'Offer' THEN 'Yet to Offer'
            WHEN 'To Be Scheduled' THEN 'To be scheduled'
            WHEN 'Yet to Join' THEN 'Yet to join'
            ELSE status
        END
    """))
    bind.execute(sa.text("""
        UPDATE candidates
        SET current_status = CASE current_status
            WHEN 'L1 Interview' THEN 'To be scheduled'
            WHEN 'L2 Interview' THEN 'To be scheduled'
            WHEN 'L3 Interview' THEN 'To be scheduled'
            WHEN 'Offer' THEN 'Yet to Offer'
            WHEN 'To Be Scheduled' THEN 'To be scheduled'
            WHEN 'Yet to Join' THEN 'Yet to join'
            ELSE current_status
        END
    """))
    bind.execute(sa.text("""
        UPDATE candidates AS c
        SET current_status = (
            SELECT i.status FROM interviews AS i
            WHERE i.candidate_id = c.id AND i.status IS NOT NULL
            ORDER BY i.id DESC LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1 FROM interviews AS i
            WHERE i.candidate_id = c.id AND i.status IS NOT NULL
        )
    """))
    _replace_org_list(bind, "status", INTERVIEW_STATUSES)
    _replace_org_list(bind, "process", PROCESSES)


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE interviews SET status = CASE status "
                         "WHEN 'Yet to Offer' THEN 'Offer' WHEN 'Yet to join' THEN 'Yet to Join' "
                         "WHEN 'Re-Scheduled' THEN 'Scheduled' WHEN 'Selected' THEN 'Scheduled' "
                         "WHEN 'Rejected' THEN 'Drop' WHEN 'Joined' THEN 'Yet to Join' "
                         "ELSE status END"))
    bind.execute(sa.text("UPDATE candidates SET current_status = CASE current_status "
                         "WHEN 'Yet to Offer' THEN 'Offer' WHEN 'Yet to join' THEN 'Yet to Join' "
                         "WHEN 'Re-Scheduled' THEN 'Scheduled' WHEN 'Selected' THEN 'Scheduled' "
                         "WHEN 'Rejected' THEN 'Drop' WHEN 'Joined' THEN 'Yet to Join' "
                         "ELSE current_status END"))
    _replace_org_list(bind, "status", OLD_STATUSES)
    bind.execute(sa.text("DELETE FROM list_values WHERE list_name = 'process'"))
    op.drop_column("candidates", "process")
