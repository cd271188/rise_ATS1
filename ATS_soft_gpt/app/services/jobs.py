"""Jobs (a pasted JD plus extracted requirements) and candidate ranking against them. Ranking is local: no LLM call."""
import logging
import re
from collections import defaultdict
from datetime import date

import numpy as np
from sqlalchemy import or_, select, update

from ..models import Candidate, CandidateProfile, CvDocument, Job, OrgCounter, utcnow
from . import audit, candidates, embeddings, jd_file, lists, matching, profiles
from .common import Conflict, Ctx, Forbidden, NotFound, ValidationError
from .llm import LlmError
from .runtime import Runtime, ai_unavailable, check_cap, record_usage

log = logging.getLogger("ats.jobs")
STATUSES = ("Open", "Closed")
MAX_JD_CHARS = 30000
SHORT_QUERY = 300
EMPTY_REQ = {
    "primary_skill": "", "must_have_skills": [], "nice_to_have_skills": [], "min_experience_years": None,
    "max_experience_years": None, "locations": [], "max_notice_days": None, "max_ctc_lakhs": None, "summary": ""}

def public_id(seq: int) -> str:
    return f"JOB-%04d" % seq


def parse_ref(text) -> int | None:
    m = re.fullmatch(r"\s*(?:JOB-)?(\d+)\s*", str(text or ""), re.I)
    return int(m.group(1)) if m else None


def _need_client(ctx: Ctx):
    # Platform staff need an explicit client-scoped route before accessing data.
    if ctx.user.platform_role and ctx.data_org_id_override is None:
        raise Forbidden("select a client company before opening requirements")
    return ctx.data_org_id


def _need_write(ctx: Ctx):
    _need_client(ctx)
    if not ctx.can_write and ctx.user.platform_role != "creator":
        raise Forbidden("your role is read-only")


def _list(v, key, strict, limit=40, width=60):
    if v is None or v == "":
        return []
    if isinstance(v, str):
        v = re.split(r"[,;\n]+", v)
    if not isinstance(v, list):
        if strict:
            raise ValidationError({key: "must be a list"})
        return []
    out, seen = [], set()
    for x in v:
        s = " ".join(str(x or "").split())
        if s and len(s) <= width and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:limit]


def _num(v, key, strict, integer=False):
    if v is None or str(v).strip() == "":
        return None
    try:
        n = float(v)
        if n != n or n < 0 or n > 100000:
            raise ValueError
    except (TypeError, ValueError):
        if strict:
            raise ValidationError({key: "must be a positive number"})
        return None
    return int(n) if integer else n


def clean_requirements(raw, strict=True) -> dict:
    """User-edited (strict: raise on bad input) or model-produced (lenient: drop what is unusable) requirements."""
    raw = raw if isinstance(raw, dict) else {}
    primary = " ".join(str(raw.get("primary_skill") or "").split())
    if strict:
        if not primary:
            raise ValidationError({"primary_skill": "required"})
        if len(primary) > 60:
            raise ValidationError({"primary_skill": "too long (max 60 characters)"})
    out = {
        "primary_skill": primary,
        "must_have_skills": _list(raw.get("must_have_skills"), "must_have_skills", strict),
        "nice_to_have_skills": _list(raw.get("nice_to_have_skills"), "nice_to_have_skills", strict),
        "min_experience_years": _num(raw.get("min_experience_years"), "min_experience_years", strict),
        "max_experience_years": _num(raw.get("max_experience_years"), "max_experience_years", strict),
        "locations": _list(raw.get("locations"), "locations", strict, limit=20),
        "max_notice_days": _num(raw.get("max_notice_days"), "max_notice_days", strict, integer=True),
        "max_ctc_lakhs": _num(raw.get("max_ctc_lakhs"), "max_ctc_lakhs", strict),
        "summary": " ".join(str(raw.get("summary") or "").split())[:800],
    }
    lo, hi = out["min_experience_years"], out["max_experience_years"]
    if lo is not None and hi is not None and lo > hi:
        if strict:
            raise ValidationError({"max_experience_years": "must not be less than the minimum"})
        out["max_experience_years"] = None
    return out


def to_dict(j: Job) -> dict:
    return {"job_id": public_id(j.seq), "title": j.title, "client": j.client, "client_ref": j.client_ref or "",
            "received_on": received_on(j), "jd_text": j.jd_text or "",
            "jd_file": {"filename": j.jd_filename, "size": j.jd_size, "mime": j.jd_mime} if j.jd_filename else None,
            "requirements": {**EMPTY_REQ, **(j.requirements or {})}, "status": j.status, "version": j.version,
            "created_by": j.created_by, "indexed": j.embedding is not None or j.embedding_vector is not None,
            "created_at": j.created_at.strftime("%Y-%m-%d %H:%M") if j.created_at else None,
            "last_updated": j.last_updated.strftime("%Y-%m-%d %H:%M") if j.last_updated else None}


def received_on(j: Job) -> str | None:
    return j.received_on or (j.created_at.date().isoformat() if j.created_at else None)


def _day(v, key, default=None):
    v = str(v or "").strip()
    if not v:
        return default
    try:
        d = date.fromisoformat(v)
    except ValueError:
        raise ValidationError({key: "use the format YYYY-MM-DD"})
    if not 2000 <= d.year <= 2100:
        raise ValidationError({key: "not a valid date"})
    return d.isoformat()


def _short(v, width):
    return " ".join(str(v or "").split())[:width] or None


def validate_job_fields(title: str, client: str | None, client_ref: str | None, req: dict) -> None:
    errors = {}
    if not client:
        errors["client"] = "required"
    if not client_ref:
        errors["client_ref"] = "required"
    if not title:
        errors["title"] = "required"
    if not req.get("primary_skill"):
        errors["primary_skill"] = "required"
    if not req.get("locations"):
        errors["locations"] = "required"
    if req.get("min_experience_years") is None:
        errors["min_experience_years"] = "required"
    if req.get("max_experience_years") is None:
        errors["max_experience_years"] = "required"
    if req.get("max_ctc_lakhs") is None:
        errors["max_ctc_lakhs"] = "required"
    if req.get("max_notice_days") is None:
        errors["max_notice_days"] = "required"
    if errors:
        raise ValidationError(errors)


def effective(req: dict | None) -> dict:
    """Requirements as used for matching: the primary skill always counts as a must-have."""
    r = {**EMPTY_REQ, **(req or {})}
    p = r.get("primary_skill")
    if p and p.lower() not in [s.lower() for s in r["must_have_skills"]]:
        r["must_have_skills"] = [p, *r["must_have_skills"]]
    return r


def _filled(v) -> bool:
    return v not in (None, "", [])


def merge_requirements(manual: dict | None, ai: dict | None) -> dict:
    """What the recruiter typed wins; the job description fills the gaps."""
    manual, ai = manual or {},  ai or {}
    return clean_requirements({k: manual.get(k) if _filled(manual.get(k)) else ai.get(k) for k in EMPTY_REQ}, strict=False)


def get_row(ctx: Ctx, ref) -> Job:
    org_id = _need_client(ctx)
    seq = parse_ref(ref)
    j = ctx.db.scalar(select(Job).where(Job.org_id == org_id, Job.deleted_at.is_(None), Job.seq == seq)) if seq else None
    if not j:
        raise NotFound("job not found")
    return j


def _next_seq(ctx: Ctx) -> int:
    n = ctx.db.execute(update(OrgCounter).where(OrgCounter.org_id == _need_client(ctx))
                       .values(next_job=OrgCounter.next_job + 1).returning(OrgCounter.next_job)).scalar_one()
    return n - 1


def job_text(title: str, req: dict) -> str:
    req = effective(req)
    parts = [title or ""]
    skills = [*(req.get("must_have_skills") or []), *(req.get("nice_to_have_skills") or [])]
    if skills:
        parts.append(f"Skills: " + ", ".join(skills))
    if req.get("summary"):
        parts.append(req["summary"])
    return ". ".join(p for p in parts if p)


def _embed_one(rt: Runtime, text: str) -> np.ndarray | None:
    if rt.embedder is None or not text.strip():
        return None
    try:
        return rt.embedder.embed([text])[0]
    except embeddings.EmbeddingError as e:
        log.warning("job embedding failed: %s", e)
        return None


def _extract(ctx: Ctx, rt: Runtime, text: str) -> dict:
    why = ai_unavailable(ctx, rt)
    if why:
        raise LlmError(why)
    check_cap(ctx, rt)
    data, usage = rt.llm.extract_requirements(text)
    record_usage(ctx, "jd_extract", usage)
    return data


def _from_jd(ctx: Ctx, rt: Runtime, jd: str) -> tuple[dict | None, str | None, str | None]:
    """(requirements, title, warning) from a pasted JD."""
    if not jd:
        return None, None, None
    why = ai_unavailable(ctx, rt)
    if why:
        return None, None, f"{why}; add the requirements by hand."
    try:
        raw = _extract(ctx, rt, jd)
    except LlmError as e:
        return None, None, f"{e}. Add the requirements by hand."
    return clean_requirements(raw, strict=False), " ".join(str(raw.get("title") or "").split())[:200] or None, None


def create_job(ctx: Ctx, rt: Runtime, data: dict) -> dict:
    _need_write(ctx)
    org_id = _need_client(ctx)
    title = " ".join(str(data.get("title") or "").split())[:200]
    client = " ".join(str(data.get("client") or "").split())[:200] or None
    client_ref = _short(data.get("client_ref"), 100)
    received = _day(data.get("received_on"), "received_on", ctx.today().isoformat())
    jd = str(data.get("jd_text") or "").strip()
    if len(jd) > MAX_JD_CHARS:
        raise ValidationError({"jd_text": f"too long (max {MAX_JD_CHARS} characters)"})
    req = clean_requirements(data.get("requirements"), True)
    validate_job_fields(title, client, client_ref, req)
    warning = None
    vec = _embed_one(rt, job_text(title, req))
    j = Job(org_id=org_id, seq=_next_seq(ctx), title=title, client=client, client_ref=client_ref, received_on=received,
            jd_text=jd or None, requirements=req, created_by=ctx.user.id)
    embeddings.write_row(j, vec, ctx.db)
    ctx.db.add(j)
    if client and len(client) <= 100:
        from .. import rls
        rls.grant(ctx.db, org_id)
        lists.add_value(ctx.db, org_id, "clients", client)
    ctx.db.flush()
    if ctx.user.platform_role and ctx.data_org_id_override is None:
        audit.record_raw(ctx.db, org_id, ctx.user.id, "job.create_by_platform", ctx.ip, {"title": title, "client": client})
    else:
        audit_ctx = Ctx(ctx.db, ctx.user, ctx.ip)
        audit.record(audit_ctx, "job.create", "job", public_id(j.seq), {"title": title, "client": client})
    ctx.db.commit()
    return {**to_dict(j), "warning": warning}


def update_job(ctx: Ctx, rt: Runtime, ref, data: dict) -> dict:
    _need_write(ctx)
    j = get_row(ctx, ref)
    if ctx.user.platform_role and ctx.data_org_id_override is None:
        raise Forbidden("platform staff can create requirements but cannot edit them")
    try:
        version = int(data.get("version"))
    except (TypeError, ValueError):
        raise ValidationError({"version": "required"})
    vals, warning = {}, None
    if "title" in data:
        t = " ".join(str(data["title"] or "").split())[:200]
        if not t:
            raise ValidationError({"title": "required"})
        vals["title"] = t
    if "client" in data:
        vals["client"] = " ".join(str(data["client"] or "").split())[:200] or None
        if vals["client"] and len(vals["client"]) <= 100:
            from .. import rls
            rls.grant(ctx.db, j.org_id)
            ctx.db.info.setdefault("rls_orgs", set()).add(j.org_id)
            lists.add_value(ctx.db, j.org_id, "clients", vals["client"])
    if "client_ref" in data:
        vals["client_ref"] = _short(data["client_ref"], 100)
    if "received_on" in data:
        vals["received_on"] = _day(data["received_on"], "received_on", received_on(j))
    if "status" in data:
        if data["status"] not in STATUSES:
            raise ValidationError({"status": "not a valid status"})
        vals["status"] = data["status"]
    if "jd_text" in data:
        jd = str(data["jd_text"] or "").strip()
        if len(jd) > MAX_JD_CHARS:
            raise ValidationError({"jd_text": f"too long (max {MAX_JD_CHARS} characters)"})
        vals["jd_text"] = jd or None
    req = j.requirements or dict(EMPTY_REQ)
    if "requirements" in data:
        req = clean_requirements(data["requirements"], True)
        vals["requirements"] = req
    elif data.get("reextract"):
        new, title, warning = _from_jd(ctx, rt, vals.get("jd_text", j.jd_text) or "") 
        if new:
            req = vals["requirements"] = {**new, "primary_skill": req.get("primary_skill", "")}
        if title and not j.title:
            vals["title"] = title
    if any(k in data for k in ("title", "client", "client_ref", "requirements", "reextract")):
        validate_job_fields(vals.get("title", j.title), vals.get("client", j.client),
                            vals.get("client_ref", j.client_ref), req)
    if not vals:
        return {**to_dict(j), "warning": warning}
    if "title" in vals or "requirements" in vals:
        vec = _embed_one(rt, job_text(vals.get("title", j.title), req))
        vals.update(embeddings.storage_values(vec, ctx.db))
    diff = {k: [getattr(j, k), v] for k, v in vals.items()
            if k not in ("embedding", "embedding_vector", "jd_text", "requirements") and getattr(j, k) != v}
    if "requirements" in vals:
        diff["requirements"] = "changed"
    res = ctx.db.execute(update(Job).where(Job.id == j.id, Job.version == version, Job.deleted_at.is_(None))
                         .values(**vals, version=version + 1, last_updated=utcnow()))
    if res.rowcount == 0:
        ctx.db.rollback()
        ctx.db.refresh(j)
        raise Conflict("this record was changed by someone else", to_dict(j))
    audit_ctx = Ctx(ctx.db, ctx.user, ctx.ip)
    audit.record(audit_ctx, "job.update", "job", public_id(j.seq), diff)
    ctx.db.commit()
    ctx.db.refresh(j)
    return {**to_dict(j), "warning": warning}


def upload_jd(ctx: Ctx, rt: Runtime, ref, data: bytes, filename: str) -> dict:
    """Attach (or replace) the job description file. Its text becomes the job's JD text; AI reads it only if the job has no skills yet."""
    _need_write(ctx)
    j = get_row(ctx, ref)
    if ctx.user.platform_role and ctx.data_org_id_override is None:
        raise Forbidden("platform staff can create requirements but cannot edit them")
    mime, text = jd_file.read(rt, data)
    text = text[:MAX_JD_CHARS]
    value, key = jd_file.keep(ctx, rt, data, mime)
    old_key = j.jd_storage_key
    warning = None
    req = j.requirements or dict(EMPTY_REQ)
    try:
        if not (req.get("must_have_skills") or req.get("primary_skill")):
            why = ai_unavailable(ctx, rt)
            if not why:
                try:
                    req = merge_requirements(req, clean_requirements(_extract(ctx, rt, text), strict=False))
                except LlmError as e:
                    warning = f"{e}. Add the requirements by hand."
            else:
                warning = f"{why}; add the requirements by hand. "
        vec = _embed_one(rt, job_text(j.title, req))
        j.jd_filename, j.jd_mime, j.jd_size = jd_file.clean_name(filename), mime, len(data)
        j.jd_file, j.jd_storage_key, j.jd_text = value, key, text
        j.requirements = dict(req)
        if vec is not None:
            embeddings.write_row(j, vec, ctx.db)
        j.version += 1
        j.last_updated = utcnow()
        audit_ctx = Ctx(ctx.db, ctx.user, ctx.ip)
        audit.record(audit_ctx, "job.jd_upload", "job", public_id(j.seq), {"filename": j.jd_filename, "size": len(data)})
        ctx.db.commit()
    except Exception:
        ctx.db.rollback()
        jd_file.drop(rt, key)
        raise
    if old_key and old_key != key:
        jd_file.drop(rt, old_key)
    return {**to_dict(j), "warning": warning}


def download_jd(ctx: Ctx, rt: Runtime, ref) -> tuple[str, str, bytes]:
    _need_client(ctx)
    j = get_row(ctx, ref)
    if not j.jd_filename:
        raise NotFound("this job has no job description file")
    return j.jd_filename, j.jd_mime or "application/octet-stream", jd_file.fetch(rt, j)


def delete_job(ctx: Ctx, ref):
    _need_client(ctx)
    if ctx.user.platform_role and ctx.data_org_id_override is None:
        raise Forbidden("platform staff cannot delete company jobs")
    if ctx.vendor_id and not ctx.is_admin:
        raise Forbidden("only administrators can delete jobs")
    j = get_row(ctx, ref)
    j.deleted_at = utcnow()
    j.version += 1
    audit_ctx = Ctx(ctx.db, ctx.user, ctx.ip)
    audit.record(audit_ctx, "job.delete", "job", public_id(j.seq), {"title": j.title})
    ctx.db.commit()


def get_job(ctx: Ctx, ref) -> dict:
    _need_client(ctx)
    return to_dict(get_row(ctx, ref))


def list_jobs(ctx: Ctx, status="", q="") -> dict:
    org_id = _need_client(ctx)
    stmt = select(Job).where(Job.org_id == org_id, Job.deleted_at.is_(None))
    if status in STATUSES:
        stmt = stmt.where(Job.status == status)
    q = str(q or "").strip()[:100]
    if q:
        stmt = stmt.where(or_(candidates._like(Job.title, q), candidates._like(Job.client, q), candidates._like(Job.client_ref, q)))
    items = [to_dict(j) for j in ctx.db.scalars(stmt.order_by(Job.seq.desc()).limit(200))]
    for it in items:
        it.pop("jd_text")
    return {"items": items}


def _text_hits(ctx: Ctx, terms: list[str]) -> dict[int, set[str]]:
    """Which requirement terms occur (as whole words/phrases) in each candidate's full stored CV text."""
    out = defaultdict(set)
    if not terms:
        return out
    rows = ctx.db.execute(select(CvDocument.candidate_id, CvDocument.text).where(
        CvDocument.org_id == ctx.data_org_id,
        CvDocument.candidate_id.in_(select(Candidate.id).where(*candidates.scope(ctx))),
      or_(*[candidates._like(CvDocument.text, t) for t in terms]))).all()
    for cid, text in rows:
        low = (text or "").lower()
        for t in terms:
            if matching.contains_term(low, t):
                out[cid].add(t)
    return out


def _rank(ctx: Ctx, rt: Runtime, req: dict, qvec, require_hit=False, min_score=0, exclude_flagged=False, limit=50) -> dict:
    rows = list(ctx.db.scalars(select(Candidate).where(*candidates.scope(ctx))))
    profs, pending = profiles.ensure(ctx, rt, rows)
    terms = req["must"] + req["nice"]
    hits = _text_hits(ctx, terms)
    cos = {}
    if qvec is not None:
        if ctx.db.get_bind().dialect.name == "postgresql":
            # Scope first; vector SQL is only used to score profiles visible to this company.
            distance = CandidateProfile.embedding_vector.op("<=>")(qvec.tolist())
            stmt = (select(CandidateProfile.candidate_id, (1.0 - distance).label("similarity"))
                    .join(Candidate, Candidate.id == CandidateProfile.candidate_id)
                    .where(CandidateProfile.org_id == ctx.data_org_id,
                           CandidateProfile.embedding_vector.is_not(None), *candidates.scope(ctx)))
            cos = {cid: float(sim) for cid, sim in ctx.db.execute(stmt)}
        else:
            usable = [c for c in rows if profs[c.id]["vec"] is not None and profs[c.id]["vec"].shape == qvec.shape]
            if usable:
                sims = np.vstack([profs[c.id]["vec"] for c in usable]) @ qvec
                cos = {c.id: float(s) for c, s in zip(usable, sims)}
    out = []
    for c in rows:
        p = profs[c.id]
        cand = {"skills": set(p["skills"]), "experience": c.total_experience_years, "location": c.current_location,
                "notice": c.official_notice_period, "expected_ctc": c.expected_ctc_lakhs,
                "blob": " ".join([c.primary_skill_role or "", p["summary"] or "", *p["skills"]]).lower()}
        r = matching.score(req, cand, cos.get(c.id), hits.get(c.id, frozenset()))
        if (require_hit and not r["matched"]) or r["score"] < min_score or (exclude_flagged and r["flags"]):
            continue
        out.append({"candidate_id": candidates.public_id(c.seq), "full_name": c.full_name,
                    "current_company": c.current_company, "current_location": c.current_location,
                    "total_experience_years": c.total_experience_years, "official_notice_period": c.official_notice_period,
                    "primary_skill_role": c.primary_skill_role, "current_status": c.current_status, **r,
                    "in_cv_text": sorted(hits.get(c.id, ()))})
    out.sort(key=lambda x: (-x["score"], x["full_name"].lower(), x["candidate_id"]))
    limit = max(1, min(int(limit or 50), 200))
    return {"items": out[:limit], "total": len(out), "candidates_searched": len(rows), "pending_index": pending}


def _filters(data: dict) -> dict:
    try:
        return {"min_score": max(0, min(int(data.get("min_score") or 0), 100)),
                "exclude_flagged": str(data.get("exclude_flagged") or "").lower() in ("1", "true", "yes"),
                "limit": int(data.get("limit") or 50)}
    except (TypeError, ValueError):
        raise ValidationError({"min_score": "must be a number"})


def matches(ctx: Ctx, rt: Runtime, ref, params: dict | None = None) -> dict:
    _need_client(ctx)
    j = get_row(ctx, ref)
    req = matching.prep_requirements(effective(j.requirements))
    qvec = embeddings.read_row(j, ctx.db)
    if qvec is None:
        qvec = _embed_one(rt, job_text(j.title, j.requirements or {}))
        if qvec is not None:
            embeddings.write_row(j, qvec, ctx.db)
            ctx.db.commit()
    return {"job": to_dict(j), **_rank(ctx, rt, req, qvec, **_filters(params or {}))}


def search(ctx: Ctx, rt: Runtime, data: dict) -> dict:
    """Ad-hoc CV search. A short query is keywords ("quoted phrases" kept whole); a long one is a pasted JD."""
    _need_client(ctx)
    q = str(data.get("q") or "").strip()
    if not q:
        raise ValidationError({"q": "enter keywords or paste a job description"})
    if len(q) > MAX_JD_CHARS:
        raise ValidationError({"q": f"too long (max {MAX_JD_CHARS} characters)"})
    f = _filters(data)
    if len(q) < SHORT_QUERY:
        terms = matching.parse_query(q)
        if not terms:
            raise ValidationError({"q": "enter keywords or paste a job description"})
        req = matching.prep_requirements({"must_have_skills": terms})
        return {"mode": "keywords", "terms": terms, **_rank(ctx, rt, req, _embed_one(rt, q), require_hit=True, **f)}
    if not ctx.can_write:
        raise Forbidden("your role cannot run AI searches")
    why = ai_unavailable(ctx, rt)
    if why:
        raise ValidationError({"q": f"pasting a job description needs AI ({why[0].lower() + why[1:]}); search with keywords instead"})
    try:
        raw = _extract(ctx, rt, q)
    except LlmError as e:
        raise ValidationError({"q": str(e)})
    clean = clean_requirements(raw, strict=False)
    ctx.db.commit()  # keep the usage record
    title = " ".join(str(raw.get("title") or "").split())
    return {"mode": "jd", "requirements": {**clean, "title": title},
            **_rank(ctx, rt, matching.prep_requirements(clean), _embed_one(rt, job_text(title, clean)), **f)}
