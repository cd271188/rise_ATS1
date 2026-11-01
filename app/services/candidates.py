"""Candidate rules: tenant scoping, duplicate detection, optimistic concurrency, soft delete."""
import re
from collections import Counter

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import aliased

from ..fields import CANDIDATE_FIELDS, DATES, DEFAULT_STATUS, FIELD_KEYS, NUMERIC, SENSITIVE
from ..models import Candidate, CvDocument, Organization, OrgCounter, utcnow
from . import audit
from .common import Conflict, Ctx, Forbidden, NotFound, ValidationError
from .validation import clean_candidate, parse_ref

SORTABLE = set(FIELD_KEYS) | {"current_status", "last_updated", "candidate_id"}
SEARCH_COLUMNS = ("full_name", "current_company", "current_location", "email", "phone", "primary_skill_role", "job_req_id")


def public_id(seq: int) -> str:
    return "CND-%04d" % seq


def norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def digits(s) -> str:
    d = re.sub(r"\D", "", str(s or ""))
    return d[-10:] if len(d) >= 7 else ""


def key_values(full_name, email, phone) -> dict:
    return {"name_key": norm(full_name), "email_key": norm(email) or None, "phone_key": digits(phone) or None}


def scope(ctx: Ctx) -> list:
    """Live candidates this user may see: the whole pipeline for a client, only its own submissions for a vendor."""
    conds = [Candidate.org_id == ctx.data_org_id, Candidate.deleted_at.is_(None)]
    if ctx.vendor_id:
        conds.append(Candidate.vendor_org_id == ctx.vendor_id)
    return conds


def vendor_names(ctx: Ctx, rows) -> dict[int, str]:
    ids = {r.vendor_org_id for r in rows if r.vendor_org_id}
    if not ids:
        return {}
    return dict(ctx.db.execute(select(Organization.id, Organization.name).where(Organization.id.in_(ids))).all())


def to_dict(c: Candidate, role: str, reasons=None, vendors=None) -> dict:
    d = {k: getattr(c, k) for k in FIELD_KEYS if role in ("owner", "admin") or k not in SENSITIVE}
    d.update(candidate_id=public_id(c.seq), current_status=c.current_status, version=c.version,
             vendor=(vendors or {}).get(c.vendor_org_id), vendor_id=c.vendor_org_id,
             last_updated=c.last_updated.strftime("%Y-%m-%d %H:%M:%S") if c.last_updated else None,
             created_by=c.created_by, duplicate_check="Duplicate - check" if reasons else "OK",
             duplicate_reasons=reasons or [])
    return d


def dup_reasons(ctx: Ctx, rows: list[Candidate]) -> dict[int, list[str]]:
    """Each row looks like a duplicate of another live record in the same organisation."""
    if not rows:
        return {}
    names = {r.name_key for r in rows if r.name_key}
    emails = {r.email_key for r in rows if r.email_key}
    phones = {r.phone_key for r in rows if r.phone_key}
    conds = [Candidate.name_key.in_(names)]
    if emails:
        conds.append(Candidate.email_key.in_(emails))
    if phones:
        conds.append(Candidate.phone_key.in_(phones))
    peers = ctx.db.execute(select(Candidate.name_key, Candidate.email_key, Candidate.phone_key).where
                           (Candidate.org_id == ctx.data_org_id, Candidate.deleted_at.is_(None), or_(*conds))).all()
    n, e, p = Counter(x[0] for x in peers), Counter(x[1] for x in peers if x[1]), Counter(x[2] for x in peers if x[2])
    out = {}
    for r in rows:
        why = []
        if n[r.name_key] > 1:
            why.append("name")
        if r.email_key and e[r.email_key] > 1:
            why.append("email")
        if r.phone_key and p[r.phone_key] > 1:
            why.append("phone")
        out[r.id] = why
    return out


def find_matches(ctx: Ctx, name="", email="", phone="", exclude_ref=None) -> list[dict]:
    conds = []
    if norm(name):
        conds.append(Candidate.name_key == norm(name))
    if norm(email):
        conds.append(Candidate.email_key == norm(email))
    if digits(phone):
        conds.append(Candidate.phone_key == digits(phone))
    if not conds:
        return []
    stmt = select(Candidate).where(Candidate.org_id == ctx.data_org_id, Candidate.deleted_at.is_(None), or_(*conds))
    ex = parse_ref(exclude_ref)
    if ex:
        stmt = stmt.where(Candidate.seq != ex)
    out = []
    for r in ctx.db.scalars(stmt):
        why = [w for w, hit in(("name", norm(name) and r.name_key == norm(name)),
                               ("email", norm(email) and r.email_key == norm(email)),
                               ("phone", digits(phone) and r.phone_key == digits(phone))) if hit]
        if ctx.vendor_id and r.vendor_org_id != ctx.vendor_id:
            out.append({"candidate_id": public_id(r.seq), "full_name": "", "match": why, "recruiter": "", "client": "", "other_source": True})
        else:
            out.append({"candidate_id": public_id(r.seq), "full_name": r.full_name, "match": why,
                        "recruiter": r.recruiter, "client": r.client})
    return out


def check_can_edit(ctx: Ctx, c: Candidate):
    if not ctx.can_write:
        raise Forbidden("your role is read-only")
    if ctx.is_admin or ctx.org.team_edit or c.created_by == ctx.user.id:
        return
    raise Forbidden("you can only edit candidates you added")


def find_row(ctx: Ctx, ref) -> Candidate | None:
    seq = parse_ref(ref)
    if seq is None:
        return None
    return ctx.db.scalar(select(Candidate).where(*scope(ctx), Candidate.seq == seq))

def get_row(ctx: Ctx, ref) -> Candidate:
    c = find_row(ctx, ref)
    if not c:
        raise NotFound("candidate not found")
    return c


def get_candidate(ctx: Ctx, ref: str) -> dict:
    c = get_row(ctx, ref)
    if not c:
        raise NotFound("candidate not found")
    return to_dict(c, ctx.role, dup_reasons(ctx, [c]).get(c.id), vendor_names(ctx, [c]))


def _like(col, value: str) -> str:
    esc = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return col.ilike(f"%{esc}%", escape="\\")


def _column_filters(ctx: Ctx, stmt, col):
    """Per-column filters given as 'key:value' strings. Unknown keys and unusable values are ignored."""
    kinds = {f[0]: f[2] for f in CANDIDATE_FIELDS}
    for item in col or []:
        key, _, value = str(item).partition(":")
        value = value.strip()[:200]
        if not value or (key in SENSITIVE and not ctx.is_admin):
            continue
        if key == "candidate_id":
            seq = parse_ref(value)
            if seq is not None:
                stmt = stmt.where(Candidate.seq == seq)
        elif key == "current_status":
            stmt = stmt.where(Candidate.current_status == value)
        elif key in NUMERIC:
            try:
                stmt = stmt.where(getattr(Candidate, key) >= Float(value))
            except ValueError:
                pass
        elif kinds.get(key) == "select":
            stmt = stmt.where(getattr(Candidate, key) == value)
        elif key in kinds:
            stmt = stmt.where(_like(getattr(Candidate, key), value))
    return stmt


def _filters(ctx, q, recruiter, client, status, duplicate, date_from, date_to, col=(), vendor_id=None):
    stmt = select(Candidate).where(*scope(ctx))
    if vendor_id is not None and not ctx.vendor_id:
        stmt = stmt.where(Candidate.vendor_org_id.is_(None) if vendor_id == 0 else Candidate.vendor_org_id == vendor_id)
    if recruiter:
        stmt = stmt.where(Candidate.recruiter == recruiter)
    if client:
        stmt = stmt.where(Candidate.client == client)
    if status:
        stmt = stmt.where(Candidate.current_status == status)
    if date_from:
        stmt = stmt.where(Candidate.date_added >= date_from)
    if date_to:
        stmt = stmt.where(Candidate.date_added <= date_to)
    if duplicate == "yes":
        other = aliased(Candidate)
        stmt = stmt.where(exists().where(
            other.org_id == Candidate.org_id, other.id != Candidate.id, other.deleted_at.is_(None),
            or_(other.name_key == Candidate.name_key,
                and_(Candidate.email_key.is_not(None), other.email_key == Candidate.email_key),
                and_(Candidate.phone_key.is_not(None), other.phone_key == Candidate.phone_key))))
    if q:
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses = [getattr(Candidate, col).ilike(f"%{esc}%", escape="\\") for col in SEARCH_COLUMNS]
        m = re.fullmatch(r"cnd-(\d+)", q)
        if m:
            clauses.append(Candidate.seq == int(m.group(1)))
        stmt = stmt.where(or_(*clauses))
    return _column_filters(ctx, stmt, col)


def list_candidates(ctx: Ctx, q="", recruiter="", client="", status="", duplicate="", date_from="", date_to="",
                    sort="candidate_id", direction="asc", limit=50, offset=0, col=(), vendor_id=None) -> dict:
    stmt = _filters(ctx, q, recruiter, client, status, duplicate, date_from, date_to, col, vendor_id)
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    if sort not in SORTABLE or (sort in SENSITIVE and not ctx.is_admin):
        sort = "candidate_id"
    col = Candidate.seq if sort == "candidate_id" else getattr(Candidate, sort)
    order = col.desc() if direction == "desc" else col.asc()
    stmt = stmt.order_by(order, Candidate.id)
    stmt = stmt.limit(max(1, min(limit, 200))).offset(max(0, int(offset)))
    rows = list(ctx.db.scalars(stmt))
    reasons = dup_reasons(ctx, rows)
    vendors = vendor_names(ctx, rows)
    return {"items": [to_dict(r, ctx.role, reasons.get(r.id), vendors) for r in rows], "total": total,
            "limit": limit, "offset": offset}


def _next_seq(ctx: Ctx) -> int:
    n = ctx.db.execute(update(OrgCounter).where(OrgCounter.org_id == ctx.data_org_id)
                       .values(next_candidate=OrgCounter.next_candidate + 1)
                       .returning(OrgCounter.next_candidate)).scalar_one()
    return n - 1


def insert_cleaned(ctx: Ctx, vals: dict) -> Candidate:
    """Insert already-validated values. Does not commit."""
    status = vals.pop("current_status", None) or DEFAULT_STATUS
    c = Candidate(org_id=ctx.data_org_id, vendor_org_id=ctx.vendor_id, seq=_next_seq(ctx), current_status=status,
                  created_by=ctx.user.id,
                  **vals, **key_values(vals.get("full_name"), vals.get("email"), vals.get("phone")))
    ctx.db.add(c)
    ctx.db.flush()
    return c


def create_candidate(ctx: Ctx, data: dict) -> dict:
    if not ctx.can_write:
        raise Forbidden("your role is read-only")
    from . import cv  # cv imports this module
    data = dict(data)
    cv_id = data.pop("cv_id", None)
    if not str(data.get("date_added") or "").strip():
        data["date_added"] = ctx.today().isoformat()
    vals = clean_candidate(data)
    matches = find_matches(ctx, vals.get("full_name"), vals.get("email"), vals.get("phone"))
    doc = cv.claim(ctx, cv_id) if cv_id else None
    c = insert_cleaned(ctx, vals)
    if doc:
        cv.attach(doc, c.id)
    audit.record(ctx, "candidate.create", "candidate", public_id(c.seq), {"name": c.full_name})
    ctx.db.commit()
    out = to_dict(c, ctx.role, dup_reasons(ctx, [c]).get(c.id), vendor_names(ctx, [c]))
    out["duplicate_matches"] = matches
    return out


def update_candidate(ctx: Ctx, ref, data: dict) -> dict:
    c = get_row(ctx, ref)
    check_can_edit(ctx, c)
    try:
        version = int(data.get("version"))
    except (TypeError, ValueError):
        raise ValidationError({"version": "required"})
    vals = clean_candidate({k: v for k, v in data.items() if k in FIELD_KEYS or k == "current_status"}, partial=True)
    if not vals:
        return to_dict(c, ctx.role, dup_reasons(ctx, [c]).get(c.id), vendor_names(ctx, [c]))
    changes = dict(vals)
    changes.update(key_values(vals.get("full_name", c.full_name), vals.get("email", c.email),
                   vals.get("phone", c.phone)))
    changes.update(version=version + 1, last_updated=utcnow())
    res = ctx.db.execute(update(Candidate).where(Candidate.id == c.id, Candidate.version == version).values(**changes))
    if res.rowcount == 0:
        ctx.db.rollback()
        ctx.db.refresh(c)
        raise Conflict("this record was changed by someone else", to_dict(c, ctx.role, None, vendor_names(ctx, [c])))
    ctx.db.commit()
    audit.record(ctx, "candidate.update", "candidate", public_id(c.seq), diff)
    ctx.db.refresh(c)
    return to_dict(c, ctx.role, dup_reasons(ctx, [c]).get(c.id), vendor_names(ctx, [c]))


def delete_candidate(ctx: Ctx, ref):
    if not ctx.is_admin:
        raise Forbidden("only administrators can delete candidates")
    c = get_row(ctx, ref)
    c.deleted_at = utcnow()
    c.version += 1
    audit.record(ctx, "candidate.delete", "candidate", public_id(c.seq), {"name": c.full_name})
    ctx.db.commit()


def get_candidate(ctx: Ctx, ref) -> dict:
    c = get_row(ctx, ref)
    return to_dict(c, ctx.role, dup_reasons(ctx, [c]).get(c.id), vendor_names(ctx, [c]))
