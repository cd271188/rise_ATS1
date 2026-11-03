"""Sign-up, login, refresh-token rotation and team management."""
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .. import rls, security
from ..fields import ADMIN_ROLES, ROLES
from ..models import Organization, OrgCounter, RefreshToken, User, utcnow
from . import audit, lists
from .common import Ctx, Forbidden, NotFound, ValidationError

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class AuthError(Exception):
    pass


def clean_email(v) -> str:
    v = str(v or "").strip().lower()
    if len(v) > 254 or not EMAIL_RE.fullmatch(v):
        raise ValidationError({"email": "not a valid email address"})
    return v


def clean_name(v, field="full_name") -> str:
    v = str(v or "").strip()
    if not v:
        raise ValidationError({field: "required"})
    if len(v) > 200:
        raise ValidationError({field: "too long"})
    return v


def clean_password(v, field="password") -> str:
    v = str(v or "")
    problem = security.password_problem(v)
    if problem:
        raise ValidationError({field: problem})
    return v


def user_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
            "last_login_at": u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else None}


def org_active(db, org: Organization | None) -> bool:
    """An organisation works only while it, and for a vendor also its client, is not suspended."""
    if not org or not org.is_active:
        return False
    if not org.parent_org_id:
        return True
    parent = db.get(Organization, org.parent_org_id)
    return bool(parent and parent.is_active)


def me(db, u: User) -> dict:
    org = db.get(Organization, u.org_id)
    parent = db.get(Organization, org.parent_org_id) if org.parent_org_id else None
    perms = []
    if u.platform_role:
        from .platform import permissions_of
        perms = permissions_of(u)
    return {**user_dict(u), "platform_role": u.platform_role, "platform_permissions": perms,
            "must_change_password": bool(u.must_change_password),
            "org": {"id": org.id, "name": org.name, "timezone": org.timezone, "team_edit": org.team_edit,
                    "is_platform": org.is_platform, "is_vendor": parent is not None, "ai_enabled": bool(org.ai_enabled),
                    "client_name": parent.name if parent else None}}


def org_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Organization))


def signup(db, mode: str, company: str, full_name: str, email: str, password: str, ip: str = "") -> User:
    if mode == "platform":
        raise Forbidden("sign-up is not available; Rise Consulting creates your company account")
    if mode == "closed" and org_count(db) > 0:
        raise Forbidden("sign-up is closed; ask your administrator for an invitation")
    company = clean_name(company)
    full_name = clean_name(full_name)
    email = clean_email(email)
    password = clean_password(password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise ValidationError({"email": "already registered"})
    org = Organization(name=company)
    db.add(org)
    db.flush()
    rls.grant(db, org.id)
    db.add(OrgCounter(org_id=org.id, next_candidate=1, next_job=1))
    lists.seed_lists(db, org.id, full_name)
    user = User(org_id=org.id, email=email, password_hash=security.hash_password(password), full_name=full_name,
                role="owner", last_login_at=utcnow())
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValidationError({"email": "already registered"})
    db.rollback()
    audit.record_raw(db, org.id, user.id, "org.signup", ip, {"company": company})
    return user


def issue_refresh(db, user: User, days: int, family: str | None = None) -> str:
    token = security.new_refresh_token()
    db.add(RefreshToken(user_id=user.id, family=family or secrets.token_hex(16), token_hash=security.hash_token(token),
                          expires_at=utcnow() + timedelta(days=days)))
    return token


def _rise_issued(db, user: User) -> bool:
    """True while the user is still on a temporary password that Rise Consulting (not their own admin) handed out."""
    if not user.must_change_password:
        return False
    from ..models import AuditLog
    mine = ("user.created_by_platform", "user.reset_password_by_platform", "user.invite", "user.reset_password",
            "org.created")
    for a in db.scalars(select(AuditLog).where(AuditLog.org_id == user.org_id, AuditLog.action.in_(mine))
                          .order_by(AuditLog.id.desc()).limit(300)):
        if a.action == "org.created":
            return False
        if a.action.endswith("_by_platform") and (a.diff or {}).get("user_id") == user.id:
            return True
        if not a.action.endswith("_by_platform") and a.entity_id == str(user.id):
            return False
    return False


def login(db, email: str, password: str, days: int, ip: str = "") -> tuple[User, str]:
    email = str(email or "").strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    ok = security.verify_password(str(password or ""), user.password_hash if user else None)
    if not user or not ok or not user.is_active:
        if user:
            audit.record_raw(db, user.org_id, user.id, "login.failed", ip)
            db.commit()
        raise AuthError("invalid email or password")
    if not org_active(db, db.get(Organization, user.org_id)):
        raise Forbidden("this company's account is suspended; contact Rise Consulting")
    token = issue_refresh(db, user, days)
    user.last_login_at = utcnow()
    rls.grant(db, user.org_id)
    audit.record_raw(db, user.org_id, user.id, "login", ip, {"rise_issued": True if _rise_issued(db, user) else None})
    db.commit()
    return user, token


def rotate_refresh(db, token: str, days: int, ip: str = "") -> tuple[User, str]:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(token or "")))
    if not row:
        raise AuthError("session expired")
    user = db.get(User, row.user_id)
    if row.revoked:
        db.execute(update(RefreshToken).where(RefreshToken.family == row.family).values(revoked=True))
        if user:
            db.execute(update(RefreshToken).where(RefreshToken.family == row.family).values(revoked=True))
            if user:
                audit.record_raw(db, user.org_id, user.id, "refresh.reuse_detected", ip)
                db.commit()
        raise AuthError("a used token came back: assume theft and kill the whole family")
    if row.expires_at < utcnow() or not user or not user.is_active or not org_active(db, db.get(Organization, user.org_id)):
        raise AuthError("session expired")
    res = db.execute(update(RefreshToken).where(RefreshToken.id == row.id, RefreshToken.revoked.is_(False))
                     .values(revoked=True))
    if res.rowcount == 0:
        db.rollback()
        raise AuthError("session expired")
    new = issue_refresh(db, user, days, row.family)
    db.commit()
    return user, new


def logout(db, token: str):
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(token or "")))
    if row:
        db.execute(update(RefreshToken).where(RefreshToken.family == row.family).values(revoked=True))
        db.commit()


def revoke_all(db, user_id: int):
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked=True))


def change_password(ctx: Ctx, current: str, new: str):
    if not security.verify_password(str(current or ""), ctx.user.password_hash):
        raise ValidationError({"current_password": "incorrect"})
    new = clean_password(new, "new_password")
    if new == current:
        raise ValidationError({"new_password": "must be different from the current password"})
    ctx.user.password_hash = security.hash_password(new)
    ctx.user.must_change_password = False
    revoke_all(ctx.db, ctx.user.id)
    audit.record(ctx, "password.change", "user", ctx.user.id)
    ctx.db.commit()


def _assignable(ctx: Ctx) -> set[str]:
    return set(ROLES) - {"owner"} if ctx.role == "owner" else {"recruiter", "viewer"}


def _member(ctx: Ctx, uid: int) -> User:
    u = ctx.db.scalar(select(User).where(User.id == uid, User.org_id == ctx.org_id))
    if not u:
        raise NotFound("user not found")
    return u


def _need_admin(ctx: Ctx):
    if not ctx.is_admin:
        raise Forbidden("administrators only")


def list_users(ctx: Ctx) -> list[dict]:
    _need_admin(ctx)
    return [user_dict(u) for u in ctx.db.scalars(select(User).where(User.org_id == ctx.org_id).order_by(User.id))]


def invite_user(ctx: Ctx, data: dict) -> dict:
    _need_admin(ctx)
    email = clean_email(data.get("email"))
    name = clean_name(data.get("full_name"))
    role = str(data.get("role") or "recruiter")
    if role not in _assignable(ctx):
        raise ValidationError({"role": "you cannot assign this role"})
    if ctx.db.scalar(select(User.id).where(User.email == email)):
        raise ValidationError({"email": "already registered"})
    temp = secrets.token_urlsafe(12)
    u = User(org_id=ctx.org_id, email=email, password_hash=security.hash_password(temp), full_name=name, role=role,
             must_change_password=True)
    ctx.db.add(u)
    ctx.db.flush()
    lists.add_value(ctx.db, ctx.org_id, "recruiters", name)
    audit.record(ctx, "user.invite", "user", u.id, {"email": email, "role": role})
    ctx.db.commit()
    return {**user_dict(u), "temporary_password": temp}


def update_user(ctx: Ctx, uid: int, data: dict) -> dict:
    _need_admin(ctx)
    u = _member(ctx, uid)
    diff = {}
    if "role" in data:
        role = str(data["role"])
        if role not in _assignable(ctx):
            raise ValidationError({"role": "you cannot assign this role"})
        if u.id == ctx.user.id:
            raise ValidationError("you cannot change your own role or access")
        if u.role == "owner" or (u.role == "admin" and ctx.role != "owner"):
            raise Forbidden("you cannot change this user")
        if u.role != role:
            diff["role"] = [u.role, role]
            u.role = role
    if "is_active" in data:
        active = bool(data["is_active"])
        if u.id == ctx.user.id and not active:
            raise ValidationError("you cannot deactivate yourself")
        if u.is_active != active:
            diff["is_active"] = [u.is_active, active]
            u.is_active = active
    if not diff:
        return user_dict(u)
    if "is_active" in diff and not active:
        revoke_all(ctx.db, u.id)
    audit.record(ctx, "user.update", "user", u.id, diff)
    ctx.db.commit()
    return user_dict(u)


def reset_password(ctx: Ctx, uid: int) -> dict:
    _need_admin(ctx)
    u = _member(ctx, uid)
    if u.role == "owner" or (u.role == "admin" and ctx.role != "owner") or u.id == ctx.user.id:
        raise Forbidden("you cannot reset this user's password")
    temp = secrets.token_urlsafe(12)
    u.password_hash = security.hash_password(temp)
    u.must_change_password = True
    revoke_all(ctx.db, u.id)
    audit.record(ctx, "user.reset_password", "user", u.id)
    ctx.db.commit()
    return {"temporary_password": temp}


def update_org(ctx: Ctx, data: dict) -> dict:
    _need_admin(ctx)
    org = ctx.org
    if "name" in data:
        org.name = clean_name(data["name"], "name")
    if "team_edit" in data:
        org.team_edit = bool(data["team_edit"])
    if "timezone" in data:
        tz = str(data["timezone"]).strip()
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)
        except Exception:
            raise ValidationError({"timezone": "unknown time zone"})
        org.timezone = tz
    if "ai_enabled" in data:
        if ctx.role != "owner":
            raise Forbidden("only the company owner can switch AI features on or off")
        org.ai_enabled = bool(data["ai_enabled"])
    audit.record(ctx, "org.update", "org", org.id,
                 {k: data[k] for k in ("name", "team_edit", "timezone", "ai_enabled") if k in data})
    ctx.db.commit()
    return me(ctx.db, ctx.user)


def list_audit(ctx: Ctx, limit: int = 100, offset: int = 0) -> dict:
    _need_admin(ctx)
    from ..models import AuditLog
    base = select(AuditLog).where(AuditLog.org_id == ctx.org_id)
    total = ctx.db.scalar(select(func.count()).select_from(base.subquery()))
    rows = ctx.db.scalars(base.order_by(AuditLog.id.desc()).limit(min(1, max(1, limit))).offset(max(0, offset)))
    emails = dict(ctx.db.execute(select(User.id, User.email).where(User.org_id == ctx.org_id)).all())
    return {"total": total, "items": [
        {"id": a.id, "at": a.at.strftime("%Y-%m-%d %H:%M:%S"), "user": emails.get(a.user_id), "action": a.action,
         "entity": a.entity, "entity_id": a.entity_id, "diff": a.diff,
         "ip": None if (a.diff or {}).get("by") == "Rise Consulting" else a.ip} for a in rows]}
