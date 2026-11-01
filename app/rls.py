"""PostgreSQL row-level security: every business table only shows rows whose org_id is listed in the transaction-local
setting app.org_ids. Code says which companies a request may touch with grant(); the hook re-applies it at the start of
every transaction, so mid-request commits need no care. With nothing granted the setting is empty and no rows are visible.
On SQLite (tests, small installs) everything here is a no-op and the hand-written org_id filters are the only guard."""
from sqlalchemy import event, text

PROTECTED_TABLES = ("candidates", "interviews", "cv_documents", "candidate_profiles", "jobs", "offer_structures",
                    "offer_letters", "list_values", "org_counters", "audit_log", "ai_usage")

_SET = text("SELECT set_config('app.org_ids', :v, true)")

def _csv(db) -> str:
    return ",".join(str(i) for i in sorted(db.info.get("rls_orgs", ())))

def _apply(connection, csv: str):
    if connection.dialect.name == "postgresql":
        connection.execute(_SET, {"v": csv})

def role_problem(engine) -> str | None:
    """Why this database login cannot be trusted with row-level security, or None. A superuser or BYPASSRLS role ignores
    every policy, so the app refuses to start as one."""
    if engine.dialect.name != "postgresql":
        return "ATS_RLS_ENABLED needs PostgreSQL"
    with engine.connect() as conn:
        row = conn.execute(text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).first()
        if row is None:
            return "could not read the database role"
        rolsuper, rolbypassrls = row.rolsuper, row.rolbypassrls
        if rolsuper or rolbypassrls:
            return (f"database role '{row.rolname}' is a superuser or has BYPASSRLS, so row-level security would not apply; "
                    "connect the app as a plain role (see deploy/postgres-init/01-roles.sh)")
        missing = conn.execute(text("""
            SELECT t.table_name
            FROM unnest(CAST(:tables AS text[])) AS t(table_name)
            LEFT JOIN pg_class c ON c.relname = t.table_name AND c.relnamespace = 'public'::regnamespace
            LEFT JOIN pg_policies p ON p.tablename = t.table_name AND p.schemaname = 'public'
                                  AND p.policyname = 'tenant_isolation'
            WHERE c.oid IS NULL OR NOT c.relrowsecurity OR p.policyname IS NULL
            ORDER BY t.table_name LIMIT 1
        """)).scalar(params={"tables": list(PROTECTED_TABLES)})
        if missing:
            return (f"row-level security is missing or disabled for table '{missing}'; "
                    "run 'alembic upgrade head' as the schema owner")
    return None

def install(factory):
    """Attach the hook to a sessionmaker."""
    @event.listens_for(factory, "after_begin")
    def _after_begin(session, transaction, connection):
        _apply(connection, _csv(session))

def only(db, *org_ids):
    """Replace the session's grants, for background jobs that handle one company at a time."""
    db.info["rls_orgs"] = set()
    grant(db, *org_ids)

def grant(db, *org_ids):
    dialect = db.get_bind().dialect.name
    ids = {int(i) for i in org_ids if i is not None}
    if not ids:
        if dialect == "postgresql":
            _apply(db.connection(), _csv(db))
        return

    db.info.setdefault("rls_orgs", set()).update(ids)
    if dialect == "postgresql":
        _apply(db.connection(), _csv(db))

def grant_all(db):
    """Every company, for housekeeping that sweeps the whole database (expired uploads). Background jobs only."""
    from .models import Organization
    from sqlalchemy import select
    only(db, *db.scalars(select(Organization.id)).all())
