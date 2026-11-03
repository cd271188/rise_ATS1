"""Time-limited, read-only database access for an operator, for when a support case really needs a look at client data.
Run by the person holding the owner database credential (the CLI uses ATS_MIGRATION_DATABASE_URL, or ATS_DATABASE_URL), never
by the web app. Each grant is a throw-away PostgreSQL role that can SELECT but not write, cannot read password hashes or
refresh tokens, logs every statement, expires by itself, and is recorded both in staff_access_grants and in the Rise
activity log. PostgreSQL only: creating a role that bypasses row-level security needs a superuser owner."""

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, text

from .. import rls
from ..db import make_sessionmaker
from ..models import AuditLog, Organization, StaffAccessGrant, utcnow

MAX_HOURS = 8
PREFIX = "ats_bg_"
HIDDEN = {"users": ("password_hash",)}  # columns never readable
UNREADABLE = ("refresh_tokens", "staff_access_grants")  # tables never readable


class BreakglassError(Exception):
    pass


def _need_postgres(engine):
    if engine.dialect.name != "postgresql":
        raise BreakglassError("break-glass access needs PostgreSQL")


def _platform_org(db) -> int:
    org_id = db.scalar(select(Organization.id).where(Organization.is_platform.is_(True)))
    if not org_id:
        raise BreakglassError("create the creator account first (there is no Rise Consulting organisation yet)")
    return org_id


def _log(db, org_id: int, action: str, role: str, diff: dict):
    db.add(AuditLog(org_id=org_id, user_id=None, action=action, entity="db_role", entity_id=role, diff=diff))


def _drop_role(db, role: str):
    """Lock the role out, end its sessions and remove it."""
    if not db.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}):
        return
    db.execute(text(f"ALTER ROLE {role} NOLOGIN"))
    db.execute(text(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = :r"), {"r": role})
    db.execute(text(f"DROP OWNED BY {role}"))
    db.execute(text(f"DROP ROLE {role}"))


def grant(engine, reason: str, hours: float, ticket: str = "", operator: str = "") -> dict:
    _need_postgres(engine)
    reason = str(reason or "").strip()
    if len(reason) < 10:
        raise BreakglassError("give a reason of at least 10 characters (it is written to the audit log)")
    if not 0 < hours <= MAX_HOURS:
        raise BreakglassError(f"hours must be above 0 and at most {MAX_HOURS}")
    role, password = PREFIX + secrets.token_hex(4) + secrets.token_urlsafe(24)
    now = utcnow()
    expires = now + timedelta(hours=hours)
    with make_sessionmaker(engine)() as db:
        org_id = _platform_org(db)
        rls.grant(db, org_id)
        # only characters from [A-Za-z0-9_-] reach these statements, so inlining them is safe (DDL takes no bind parameters)
        db.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER BYPASSRLS CONNECTION LIMIT 3 "
                        f"VALID UNTIL '{expires:%Y-%m-%d %H:%M:%S+00}'"))
        db.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        db.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}"))
        for table in UNREADABLE:
            db.execute(text(f"REVOKE ALL ON {table} FROM {role}"))
        for table, hidden in HIDDEN.items():
            cols = [c for (c,) in db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"), {"t": table}) if c not in hidden]
            db.execute(text(f"REVOKE ALL ON {table} FROM {role}"))
            db.execute(text(f"GRANT SELECT ({', '.join(chr(34) + c + chr(34) for c in cols)}) ON {table} TO {role}"))
        db.execute(text(f"ALTER ROLE {role} SET default_transaction_read_only = on"))
        db.execute(text(f"ALTER ROLE {role} SET log_statement = 'all'"))
        who = operator or "unknown operator"
        db.add(StaffAccessGrant(pg_role=role, operator=who, reason=reason, ticket=ticket or None, granted_at=now,
                                expires_at=expires))
        _log(db, org_id, "breakglass.grant", role, {"operator": who, "reason": reason, "ticket": ticket or None,
                                                    "hours": hours, "expires_at": expires.strftime("%Y-%m-%d %H:%M UTC")})
        db.commit()
    return {"role": role, "password": password, "expires_at": expires}


def revoke(engine, role: str, operator: str = "") -> bool:
    _need_postgres(engine)
    with make_sessionmaker(engine)() as db:
        row = db.scalar(select(StaffAccessGrant).where(StaffAccessGrant.pg_role == role, StaffAccessGrant.revoked_at.is_(None)))
        if not row:
            return False
        org_id = _platform_org(db)
        rls.grant(db, org_id)
        _drop_role(db, role)
        row.revoked_at = utcnow()
        _log(db, org_id, "breakglass.revoke", role, {"operator": operator or "unknown operator"})
        db.commit()
    return True


def reap(engine) -> list[str]:
    """Remove every role whose grant has expired, and any break-glass role that has no live grant behind it."""
    _need_postgres(engine)
    gone = []
    with make_sessionmaker(engine)() as db:
        org_id = _platform_org(db)
        rls.grant(db, org_id)
        now = utcnow()
        live = {r.pg_role: r for r in db.scalars(select(StaffAccessGrant).where(StaffAccessGrant.revoked_at.is_(None)))}
        for role, row in live.items():
            if row.expires_at <= now:
                _drop_role(db, role)
                row.revoked_at = now
                _log(db, org_id, "breakglass.expired", role, {})
                gone.append(role)
        for (role,) in db.execute(text("SELECT rolname FROM pg_roles WHERE rolname LIKE :p"), {"p": PREFIX.replace("_", "\\_") + "%"}).all():
            if role not in live:
                _drop_role(db, role)
                _log(db, org_id, "breakglass.orphan_removed", role, {})
                gone.append(role)
        db.commit()
    return gone


def listing(engine) -> list[dict]:
    with make_sessionmaker(engine)() as db:
        rows = db.scalars(select(StaffAccessGrant).order_by(StaffAccessGrant.id.desc()).limit(100))
        now = utcnow()
        return [{"role": r.pg_role, "operator": r.operator, "reason": r.reason, "ticket": r.ticket,
                 "granted_at": r.granted_at, "expires_at": r.expires_at, "revoked_at": r.revoked_at,
                 "state": "revoked" if r.revoked_at else ("expired (not yet removed)" if r.expires_at <= now else "active")}
                for r in rows]