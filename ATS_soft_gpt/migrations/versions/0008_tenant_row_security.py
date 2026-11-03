"""Enforce company isolation in PostgreSQL.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TABLES = ("candidates", "interviews", "cv_documents", "candidate_profiles", "jobs", "offer_structures",
          "offer_letters", "list_values", "org_counters", "audit_log", "ai_usage")


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'''CREATE POLICY tenant_isolation ON "{table}"
            USING (org_id::text = ANY(string_to_array(current_setting('app.org_ids', true), ',')))
            WITH CHECK (org_id::text = ANY(string_to_array(current_setting('app.org_ids', true), ',')))''')
    # The owner role performs migrations; the app connects with ats_app and cannot bypass RLS.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ats_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ats_app;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ats_app;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ats_app;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ats_app;
            REVOKE ALL ON audit_log FROM ats_app;
            GRANT SELECT, INSERT ON audit_log TO ats_app;
            GRANT UPDATE (diff) ON audit_log TO ats_app;
          END IF;
        END $$
    """)


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
