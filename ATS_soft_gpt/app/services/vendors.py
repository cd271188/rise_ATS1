"""Vendors: companies a client hires to source candidates into the client's own pipeline."""
import secrets

from sqlalchemy import func, select

from .. import rls, security
from ..models import Candidate, Organization, OrgCounter, User
from . import audit, lists
from .auth import clean_email, clean_name, revoke_all, user_dict
from .common import Ctx, Forbidden, NotFound, ValidationError


def _need_client_admin(ctx: Ctx):
    if not ctx.is_admin or ctx.org.is_platform or ctx.org.parent_org_id is not None:
        raise Forbidden("only a client company's owner or administrators can manage vendors")


def _vendor(ctx: Ctx, vendor_id: int) -> Organization:
    org = ctx.db.get(Organization, vendor_id)
    if not org or org.parent_org_id != ctx.org_id:
        raise NotFound("vendor not found")
    return org


def vendor_dict(db, org: Organization) -> dict:
    users = db.scalar(select(func.count()).select_from(User).where(User.org_id == org.id))
    owner = db.scalar(select(User).where(User.org_id == org.id, User.role == "owner").order_by(User.id))
    cands = db.scalar(select(func.count()).select_from(Candidate).where(
        Candidate.vendor_org_id == org.id, Candidate.deleted_at.is_(None)))
    return {"id": org.id, "name": org.name, "is_active": org.is_active, "users": users, "candidates": cands,
            "owner_email": owner.email if owner else None, "owner_name": owner.full_name if owner else None,
            "created_at": org.created_at.strftime("%Y-%m-%d")}


def options(ctx: Ctx) -> list[dict]:
    """Vendor choices for the candidate filter. Only a client company has any."""
    if ctx.org.is_platform or ctx.org.parent_org_id is not None:
        return []
    rows = ctx.db.execute(select(Organization.id, Organization.name).where(
        Organization.parent_org_id == ctx.org_id).order_by(Organization.name)).all()
    return [{"id": i, "name": n} for i, n in rows]


def list_vendors(ctx: Ctx) -> list[dict]:
    _need_client_admin(ctx)
    rows = ctx.db.scalars(select(Organization).where(Organization.parent_org_id == ctx.org_id).order_by(Organization.id))
    return [vendor_dict(ctx.db, o) for o in rows]


def build_vendor(ctx: Ctx, client: Organization, data: dict) -> tuple[Organization, str]:
    """Add a vendor company and its owner under client. Does not commit or audit"""
    name = clean_name(data.get("company"), "company")
    owner_name = clean_name(data.get("owner_name"), "owner_name")
    email = clean_email(data.get("owner_email"))
    if ctx.db.scalar(select(User.id).where(User.email == email)):
        raise ValidationError({"owner_email": "already registered"})
    org = Organization(name=name, parent_org_id=client.id)
    ctx.db.add(org)
    ctx.db.flush()
    rls.grant(ctx.db, org.id)
    ctx.db.add(OrgCounter(org_id=org.id, next_candidate=1, next_job=1))
    lists.seed_lists(ctx.db, org.id, [owner_name])
    temp = secrets.token_urlsafe(12)
    ctx.db.add(User(org_id=org.id, email=email, password_hash=security.hash_password(temp), full_name=owner_name,
                 role="owner", must_change_password=True))
    ctx.db.flush()
    return org, temp


def create_vendor(ctx: Ctx, data: dict) -> dict:
    _need_client_admin(ctx)
    org, temp = build_vendor(ctx, ctx.org, data)
    audit.record(ctx, "vendor.create", "org", org.id, {"vendor": org.name, "owner": data.get("owner_email")})
    audit.record_raw(ctx.db, org.id, ctx.user.id, "org.created_as_vendor", ctx.ip, {"client": ctx.org.name})
    ctx.db.commit()
    return {**vendor_dict(ctx.db, org), "temporary_password": temp}


def update_vendor(ctx: Ctx, vendor_id: int, data: dict) -> dict:
    _need_client_admin(ctx)
    org = _vendor(ctx, vendor_id)
    diff = {}
    if "name" in data:
        new = clean_name(data["name"], "name")
        diff["name"] = [org.name, new]
        org.name = new
    if "is_active" in data:
        active = bool(data["is_active"])
        diff["is_active"] = [org.is_active, active]
        org.is_active = active
        if not active:
            for uid in ctx.db.scalars(select(User.id).where(User.org_id == org.id)):
                revoke_all(ctx.db, uid)
    audit.record(ctx, "vendor.update", "org", org.id, diff)
    ctx.db.commit()
    return vendor_dict(ctx.db, org)


def list_vendor_users(ctx: Ctx, vendor_id: int) -> list[dict]:
    _need_client_admin(ctx)
    org = _vendor(ctx, vendor_id)
    return [user_dict(u) for u in ctx.db.scalars(select(User).where(User.org_id == org.id).order_by(User.id))]


def reset_vendor_user_password(ctx: Ctx, vendor_id: int, uid: int) -> dict:
    _need_client_admin(ctx)
    org = _vendor(ctx, vendor_id)
    u = ctx.db.scalar(select(User).where(User.id == uid, User.org_id == org.id))
    if not u:
        raise NotFound("user not found")
    temp = secrets.token_urlsafe(12)
    u.password_hash = security.hash_password(temp)
    u.must_change_password = True
    revoke_all(ctx.db, u.id)
    audit.record(ctx, "vendor.reset_password", "user", u.id, {"vendor": org.name, "email": u.email})
    audit.record_raw(ctx.db, org.id, u.id, "user.reset_password_by_client", ctx.ip, {"by": ctx.user.email})
    ctx.db.commit()
    return {"temporary_password": temp}
