"""Per-organisation dropdown lists."""
from sqlalchemy import delete, select

from ..fields import SEED_LISTS, STATUSES
from ..models import ListValue
from . import audit
from .common import Ctx, Forbidden, ValidationError


def seed_lists(db, org_id: int, recruiters: list[str] | None = None):
    for name, values in SEED_LISTS.items():
        values = list(recruiters or []) if name == "recruiters" else values
        db.add_all(ListValue(org_id=org_id, list_name=name, value=v, sort_order=i) for i, v in enumerate(values))


def get_lists(db, org_id: int) -> dict:
    out = {name: [] for name in SEED_LISTS}
    for r in db.scalars(select(ListValue).where(ListValue.org_id == org_id).order_by(ListValue.sort_order, ListValue.id)):
        out.setdefault(r.list_name, []).append(r.value)
    return out


def lists_for(ctx: Ctx) -> dict:
    """Dropdowns a user: a vendor gets its client's lists but picks recruiters from its own team."""
    out = get_lists(ctx.db, ctx.data_org_id)
    if ctx.vendor_id:
        out["recruiters"] = get_lists(ctx.db, ctx.org_id)["recruiters"]
    return out


def add_value(db, org_id: int, list_name: str, value: str):
    """Append a value if missing (used when a team member is added)."""
    current = get_lists(db, org_id)[list_name]
    if value.lower() not in [v.lower() for v in current]:
        db.add(ListValue(org_id=org_id, list_name=list_name, value=value, sort_order=len(current)))


def put_lists(ctx: Ctx, data: dict) -> dict:
    if not ctx.is_admin:
        raise Forbidden("only administrators can edit lists")
    if not isinstance(data, dict):
        raise ValidationError({"lists": "expected an object"})
    cleaned = {}
    for name, values in data.items():
        if name not in SEED_LISTS or not isinstance(values, list):
            raise ValidationError({name: "unknown list"})
        seen, vals = set(), []
        for v in values:
            v = str(v).strip()
            if v and v.lower() not in seen and len(v) <= 100:
                seen.add(v.lower())
                vals.append(v)
        if name == "status" and vals != STATUSES:
            raise ValidationError({"status": "the nine statuses are fixed"})
        cleaned[name] = vals
    for name, vals in cleaned.items():
        ctx.db.execute(delete(ListValue).where(ListValue.org_id == ctx.org_id, ListValue.list_name == name))
        ctx.db.add_all(ListValue(org_id=ctx.org_id, list_name=name, value=v, sort_order=i) for i, v in enumerate(vals))
    audit.record(ctx, "lists.update", "lists", None, {"lists": sorted(cleaned)})
    ctx.db.commit()
    return get_lists(ctx.db, ctx.org_id)