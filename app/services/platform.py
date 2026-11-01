"""Rise Consulting's platform tier: client companies, their user accounts, and the Rise staff accounts.
Platform users manage accounts only; nothing here reads candidates, interviews or reports of a client."""
import secrets

from sqlalchemy import func, select

from .. import rls, security
from ..models import AuditLog, Organization, OrgCounter, User, utcnow
from . import audit, lists, vendors
from .auth import clean_email, clean_name, clean_password, revoke_all, user_dict
from .common import Ctx, Forbidden, NotFound, ValidationError

PERMISSIONS = {
    "create_companies": "Create client companies",
    "manage_companies": "Rename, suspend and reactivate companies",
    "manage_client_users": "Add client users, change roles, disable, reset passwords",
    "manage_compensation": "Build offer letter compensation structures and send them to companies",
    "manage_ai": "Turn AI features on or off for companies",
    "create_job_requirements": "Create client job requirements",
    "view_audit": "See the Rise activity log (who did what to which company)",
}
CLIENT_ROLES = ("admin", "recruiter", "viewer")
BY = "Rise Consulting"


def permissions_of(u: User) -> list[str]:
    if u.platform_role == "creator":
        return list(PERMISSIONS)
    return [p for p in (u.platform_permissions or []) if p in PERMISSIONS]


def _need_platform(ctx: Ctx):
    if not ctx.user.platform_role or not ctx.org.is_platform:
        raise Forbidden("Rise Consulting staff only")


def _need(ctx: Ctx, perm: str):
    _need_platform(ctx)
    if perm not in permissions_of(ctx.user):
        raise Forbidden("you have not been given this permission: " + PERMISSIONS[perm].lower())


def _need_creator(ctx: Ctx):
    _need_platform(ctx)
    if ctx.user.platform_role != "creator":
        raise Forbidden("only the creator can do this")


def _need_jobs(ctx: Ctx):
    _need_platform(ctx)
    if ctx.user.platform_role != "creator" and "create_job_requirements" not in permissions_of(ctx.user):
        raise Forbidden("you have not been given permission to create client job requirements")


def create_job_description(ctx: Ctx, rt, org_id: int, data: dict) -> dict:
    _need_jobs(ctx)
    org = _client(ctx, org_id)
    rls.grant(ctx.db, org.id)
    from . import jobs
    client_ctx = Ctx(ctx.db, ctx.user, ctx.ip, data_org_id_override=org.id)
    result = jobs.create_job(client_ctx, rt, data)
    result.pop("warning", None)
    ctx.db.commit()
    return result


def list_jobs_for_platform(ctx: Ctx, org_id: int):
    _need_jobs(ctx)
    org = _client(ctx, org_id)
    from .. import rls as rls_service
    rls_service.grant(ctx.db, org.id)
    from . import jobs
    client_ctx = Ctx(ctx.db, ctx.user, ctx.ip, data_org_id_override=org.id)
    return {"items": jobs.list_jobs(client_ctx)["items"], "company": company_dict(ctx.db, org)}


def read_job_for_platform(ctx: Ctx, org_id: int, ref: str) -> dict:
    _need_jobs(ctx)
    org = _client(ctx, org_id)
    from .. import rls as rls_service
    rls_service.grant(ctx.db, org.id)
    from . import jobs
    client_ctx = Ctx(ctx.db, ctx.user, ctx.ip, data_org_id_override=org.id)
    return jobs.get_job(client_ctx, ref)


def _client(ctx: Ctx, org_id: int) -> Organization:
    org = ctx.db.get(Organization, org_id)
    if not org or org.is_platform or org.parent_org_id is not None:
        raise NotFound("company not found")
    rls.grant(ctx.db, org_id)
    return org


def _temp() -> str:
    return secrets.token_urlsafe(12)


def audit_company(ctx: Ctx, action: str, org: Organization, entity: str | None = None, entity_id=None,
                  diff: dict | None = None) -> None:
    """A row in the Rise activity log that always the company acted on."""
    audit.record(ctx, action, entity, entity_id, {"company": org.name, "company_id": org.id, **(diff or {})})


def _guard_account(ctx: Ctx, target: User) -> bool:
    """Owner and admin accounts of a client are the keys to its data, so only the creator may touch them.
    True when the target is such an account(the caller then logs it as an admin-account change)."""
    if target.role in ("owner", "admin"):
        _need_creator(ctx)
        return True
    return False


def staff_dict(u: User) -> dict:
    return {**user_dict(u), "platform_role": u.platform_role, "permissions": permissions_of(u)}


def clean_permissions(v) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or any(p not in PERMISSIONS for p in v):
        raise ValidationError({"permissions": "unknown permission"})
    return [p for p in PERMISSIONS if p in v]


def company_dict(db, org: Organization) -> dict:
    users = db.scalar(select(func.count()).select_from(User).where(User.org_id == org.id))
    owner = db.scalar(select(User).where(User.org_id == org.id, User.role == "owner").order_by(User.id))
    return {"id": org.id, "name": org.name, "is_active": org.is_active, "ai_enabled": bool(org.ai_enabled), "users": users,
            "owner_email": owner.email if owner else None, "owner_name": owner.full_name if owner else None,
            "created_at": org.created_at.strftime("%Y-%m-%d")}


def list_companies(ctx: Ctx) -> list[dict]:
    """Every client company with its people and its vendors (and their people). Accounts only; no candidate data."""
    _need_platform(ctx)
    orgs = list(ctx.db.scalars(select(Organization).where(Organization.is_platform.is_(False)).order_by(Organization.id)))
    people: dict[int, list[dict]] = {}
    for u in ctx.db.scalars(select(User).order_by(User.id)):
        people.setdefault(u.org_id, []).append(user_dict(u))
    out = []
    for o in orgs:
        if o.parent_org_id is not None:
            continue
        vendor_list = [{"id": v.id, "name": v.name, "is_active": v.is_active, "people": people.get(v.id, [])}
                        for v in orgs if v.parent_org_id == o.id]
        out.append({**company_dict(ctx.db, o), "people": people.get(o.id, []), "vendors": vendor_list})
    return out


def create_company(ctx: Ctx, data: dict) -> dict:
    _need(ctx, "create_companies")
    name = clean_name(data.get("company"), "company")
    owner_name = clean_name(data.get("owner_name"), "owner_name")
    email = clean_email(data.get("owner_email"))
    if ctx.db.scalar(select(User.id).where(User.email == email)):
        raise ValidationError({"owner_email": "already registered"})
    org = Organization(name=name)
    ctx.db.add(org)
    ctx.db.flush()
    rls.grant(ctx.db, org.id)
    ctx.db.add(OrgCounter(org_id=org.id, next_candidate=1, next_job=1))
    lists.seed_lists(ctx.db, org.id, [owner_name])
    temp = _temp()
    owner = User(org_id=org.id, email=email, password_hash=security.hash_password(temp), full_name=owner_name,
                 role="owner", must_change_password=True)
    ctx.db.add(owner)
    ctx.db.flush()
    audit_company(ctx, "company.create", "org", org.id, {"owner": email})
    audit.record_raw(ctx.db, org.id, None, "org.created", ctx.ip, {"by": BY})
    ctx.db.commit()
    return {**company_dict(ctx.db, org), "temporary_password": temp}


def update_company(ctx: Ctx, org_id: int, data: dict) -> dict:
    _need_platform(ctx)
    if "name" in data or "is_active" in data:
        _need(ctx, "manage_companies")
    if "ai_enabled" in data:
        _need(ctx, "manage_ai")
    org = _client(ctx, org_id)
    diff = {}
    if "ai_enabled" in data:
        on = bool(data["ai_enabled"])
        diff["ai_enabled"] = [bool(org.ai_enabled), on]
        org.ai_enabled = on
    if "name" in data:
        new = clean_name(data["name"], "name")
        diff["name"] = [org.name, new]
        org.name = new
    if "is_active" in data:
        active = bool(data["is_active"])
        diff["is_active"] = [org.is_active, active]
        org.is_active = active
        if not active:
            vendor_ids = select(Organization.id).where(Organization.parent_org_id == org.id)
            for uid in ctx.db.scalars(select(User.id).where((User.org_id == org.id) | (User.org_id.in_(vendor_ids)))):
                revoke_all(ctx.db, uid)
    audit_company(ctx, "company.update", org, "org", org.id, diff)
    audit.record_raw(ctx.db, org.id, None, "org.updated_by_platform", ctx.ip, {"by": BY, **diff})
    ctx.db.commit()
    return company_dict(ctx.db, org)


def create_company_vendor(ctx: Ctx, org_id: int, data: dict) -> dict:
    """The creator adds a vendor company under a client, exactly as the client's own admin could."""
    _need_creator(ctx)
    client = _client(ctx, org_id)
    org, temp = vendors.build_vendor(ctx, client, data)
    audit_company(ctx, "vendor.create", "org", org.id, {"client": client.name, "vendor": org.name})
    audit.record_raw(ctx.db, client.id, None, "vendor.created_by_platform", ctx.ip, {"by": BY, "vendor_id": org.id})
    audit.record_raw(ctx.db, org.id, None, "org.created_as_vendor", ctx.ip, {"by": BY, "client": client.name})
    ctx.db.commit()
    return {**vendors.vendor_dict(ctx.db, org), "temporary_password": temp}


# --------------------------------------------- client user accounts
def _client_user(ctx: Ctx, org: Organization, uid: int) -> User:
    u = ctx.db.scalar(select(User).where(User.id == uid, User.org_id == org.id))
    if not u:
        raise NotFound("user not found")
    return u


def list_company_users(ctx: Ctx, org_id: int) -> list[dict]:
    _need_platform(ctx, "manage_client_users")
    org = _client(ctx, org_id)
    audit_company(ctx, "platform.view_users", org, "org", org.id)
    ctx.db.commit()
    return [user_dict(u) for u in ctx.db.scalars(select(User).where(User.org_id == org.id).order_by(User.id))]


def create_company_user(ctx: Ctx, org_id: int, data: dict) -> dict:
    _need(ctx, "manage_client_users")
    org = _client(ctx, org_id)
    email, name = clean_email(data.get("email")), clean_name(data.get("full_name"))
    role = str(data.get("role") or "recruiter")
    if role not in CLIENT_ROLES:
        raise ValidationError({"role": "choose admin, recruiter or viewer"})
    if role == "admin":
        _need_creator(ctx)
    if ctx.db.scalar(select(User.id).where(User.email == email)):
        raise ValidationError({"email": "already registered"})
    temp = _temp()
    u = User(org_id=org.id, email=email, password_hash=security.hash_password(temp), full_name=name, role=role,
             must_change_password=True)
    ctx.db.add(u)
    ctx.db.flush()
    if role in ("recruiter", "admin"):
        lists.add_value(ctx.db, org.id, "recruiters", name)
    audit_company(ctx, "company.admin_account_change" if role == "admin" else "company.user_create", org, "user", u.id,
                  {"email": email, "role": role})
    audit.record_raw(ctx.db, org.id, None, "user.created_by_platform", ctx.ip, {"by": BY, "user_id": u.id, "role": role})
    ctx.db.commit()
    return {**user_dict(u), "temporary_password": temp}


def update_company_user(ctx: Ctx, org_id: int, uid: int, data: dict) -> dict:
    _need(ctx, "manage_client_users")
    org = _client(ctx, org_id)
    u = _client_user(ctx, org, uid)
    sensitive = _guard_account(ctx, u)
    diff = {}
    if "role" in data:
        if u.role == "owner":
            raise Forbidden("the owner's role cannot be changed")
        role = str(data["role"])
        if role not in CLIENT_ROLES:
            raise ValidationError({"role": "choose admin, recruiter or viewer"})
        if role == "admin":
            _need_creator(ctx)
            sensitive = True
        diff["role"] = [u.role, role]
        u.role = role
    if "is_active" in data:
        active = bool(data["is_active"])
        diff["is_active"] = [u.is_active, active]
        u.is_active = active
        if not active:
            revoke_all(ctx.db, u.id)
    audit_company(ctx, "company.admin_account_change" if sensitive else "company.user_update", org, "user", u.id,
                  {"email": u.email, **diff})
    audit.record_raw(ctx.db, org.id, None, "user.updated_by_platform", ctx.ip, {"by": BY, "user_id": u.id, **diff})
    ctx.db.commit()
    return user_dict(u)


def reset_company_user_password(ctx: Ctx, org_id: int, uid: int) -> dict:
    _need(ctx, "manage_client_users")
    org = _client(ctx, org_id)
    u = _client_user(ctx, org, uid)
    sensitive = _guard_account(ctx, u)
    temp = _temp()
    u.password_hash = security.hash_password(temp)
    u.must_change_password = True
    revoke_all(ctx.db, u.id)
    audit_company(ctx, "company.admin_account_change" if sensitive else "company.reset_password", org, "user", u.id,
                  {"email": u.email, "role": u.role, "change": "password reset"})
    audit.record_raw(ctx.db, org.id, None, "user.reset_password_by_platform", ctx.ip, {"by": BY, "user_id": u.id})
    ctx.db.commit()
    return {"temporary_password": temp}


# --------------------------------------------- Rise staff
def _staff(ctx: Ctx, uid: int) -> User:
    u = ctx.db.scalar(select(User).where(User.id == uid, User.org_id == ctx.org_id, User.platform_role.is_not(None)))
    if not u:
        raise NotFound("user not found")
    return u


def list_staff(ctx: Ctx) -> list[dict]:
    _need_creator(ctx)
    rows = ctx.db.scalars(select(User).where(User.org_id == ctx.org_id, User.platform_role.is_not(None)).order_by(User.id))
    return [staff_dict(u) for u in rows]


def create_staff(ctx: Ctx, data: dict) -> dict:
    _need_creator(ctx)
    email, name = clean_email(data.get("email")), clean_name(data.get("full_name"))
    perms = clean_permissions(data.get("permissions"))
    if ctx.db.scalar(select(User.id).where(User.email == email)):
        raise ValidationError({"email": "already registered"})
    temp = _temp()
    u = User(org_id=ctx.org_id, email=email, password_hash=security.hash_password(temp), full_name=name,
             role="viewer", platform_role="rise_admin", platform_permissions=perms,
             must_change_password=True)
    ctx.db.add(u)
    ctx.db.flush()
    audit.record(ctx, "staff.create", "user", u.id, {"email": email, "permissions": perms})
    ctx.db.commit()
    return {**staff_dict(u), "temporary_password": temp}


def update_staff(ctx: Ctx, uid: int, data: dict) -> dict:
    _need_creator(ctx)
    u = _staff(ctx, uid)
    if u.id == ctx.user.id or u.platform_role == "creator":
        raise Forbidden("you cannot change this account")
    diff = {}
    if "permissions" in data:
        perms = clean_permissions(data["permissions"])
        diff["permissions"] = [permissions_of(u), perms]
        u.platform_permissions = perms
    if "is_active" in data:
        active = bool(data["is_active"])
        diff["is_active"] = [u.is_active, active]
        u.is_active = active
        if not active:
            revoke_all(ctx.db, u.id)
    audit.record(ctx, "staff.update", "user", u.id, diff)
    ctx.db.commit()
    return staff_dict(u)


def reset_staff_password(ctx: Ctx, uid: int) -> dict:
    _need_creator(ctx)
    u = _staff(ctx, uid)
    if u.id == ctx.user.id or u.platform_role == "creator":
        raise Forbidden("you cannot reset this account")
    temp = _temp()
    u.password_hash = security.hash_password(temp)
    u.must_change_password = True
    revoke_all(ctx.db, u.id)
    audit.record(ctx, "staff.reset_password", "user", u.id)
    ctx.db.commit()
    return {"temporary_password": temp}


# ----------------------------------------------------------------------------- Rise activity log
def list_audit(ctx: Ctx, limit: int = 100, offset: int = 0, company_id: int | None = None) -> dict:
    """What Rise staff did, with the named actor, the company acted on, the address and the time."""
    _need_platform(ctx)
    if ctx.user.platform_role != "creator" and "view_audit" not in permissions_of(ctx.user):
        raise Forbidden("you have not been given this permission: " + PERMISSIONS["view_audit"].lower())
    base = select(AuditLog).where(AuditLog.org_id == ctx.org_id)
    if company_id is not None:
        base = base.where(AuditLog.diff["company_id"].as_integer() == company_id)
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500))).offset(max(0, offset)))
    people = {i: (n, e) for i, n, e in ctx.db.execute(select(User.id, User.full_name, User.email).where(User.org_id == ctx.org_id))}
    items = []
    for a in rows:
        name, email = people.get(a.user_id, (None, None))
        diff = a.diff or {}
        items.append({"id": a.id, "at": a.at.strftime("%Y-%m-%d %H:%M:%S"), "user": name, "email": email, "action": a.action,
                      "company": diff.get("company"), "company_id": diff.get("company_id"), "entity": a.entity,
                      "entity_id": a.entity_id, "diff": diff, "ip": a.ip})
    return {"total": total, "items": items}
    

# --------------------------------------------- bootstrap
def bootstrap_creator(db, email: str, full_name: str, password: str, company: str = "Rise Consulting") -> User:
    """Create the platform organisation (if missing) and the creator account. Used by the command line only."""
    email, name, password = clean_email(email), clean_name(full_name), clean_password(password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise ValidationError({"email": "already registered"})
    org = db.scalar(select(Organization).where(Organization.is_platform.is_(True)))
    if not org:
        org = Organization(name=company, is_platform=True)
        db.add(org)
        db.flush()
        db.add(OrgCounter(org_id=org.id, next_candidate=1, next_job=1))
    user = User(org_id=org.id, email=email, password_hash=security.hash_password(password), full_name=name,
                role="viewer", platform_role="creator", last_login_at=utcnow())
    db.add(user)
    db.flush()
    audit.record_raw(db, org.id, user.id, "creator.bootstrap")
    db.commit()
    return user
