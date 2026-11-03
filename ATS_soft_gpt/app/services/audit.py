"""Append-only audit trail. There is deliberately no update or delete function."""
from .. import rls
from ..models import AuditLog
from .common import Ctx


def record(ctx: Ctx, action: str, entity: str | None = None, entity_id=None, diff: dict | None = None):
    ctx.db.add(AuditLog(org_id=ctx.org_id, user_id=ctx.user.id, action=action, entity=entity,
                        entity_id=None if entity_id is None else str(entity_id), diff=diff, ip=ctx.ip[:64] or None))


def record_raw(db, org_id: int, user_id: int | None, action: str, ip: str = "", diff: dict | None = None):
    rls.grant(db, org_id)
    db.add(AuditLog(org_id=org_id, user_id=user_id, action=action, diff=diff, ip=ip[:64] or None))