"""CV upload: extract text, one LLM call for the fields, sanitise, keep the original file, flag duplicates."""
import logging
import os
import re
from datetime import timedelta

from sqlalchemy import delete, select

from .. import rls
from ..fields import FIELD_KEYS, REQUIRED
from ..models import CvDocument, utcnow
from . import audit, blobstore, candidates, cv_text, matching
from .common import Ctx, Forbidden, NotFound, ValidationError
from .llm import LlmError
from .runtime import Runtime, ai_unavailable, check_cap, record_usage
from .validation import clean_candidate

log = logging.getLogger("ats.cv")
DRAFT_HOURS = 24
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().\-]{8,18}\d(?![\w])")
# fields a CV can supply. Recruiter, client dates and status are the recruiter's to fill.
FROM_LLM = {"full_name": "Full Name", "current_company": "current_company", "current_location": "current_location",
            "total_experience_years": "total_experience_years", "current_ctc_lakhs": "current_ctc_lakhs",
            "expected_ctc_lakhs": "expected_ctc_lakhs", "notice_period": "official_notice_period",
            "email": "email", "phone": "phone", "primary_skill_role": "primary_skill_role"}
LIMITS = {"total_experience_years": 60, "current_ctc_lakhs": 1000, "expected_ctc_lakhs": 1000}
NOTICE_DAYS = {15: "15 Days", 30: "30 Days", 45: "45 Days", 60: "60 Days", 90: "90 Days"}


def regex_contacts(text: str) -> dict:
    """Email and phone straight from the CV header, without the LLM."""
    head = text[:3000]
    out = {}
    m = _EMAIL.search(head)
    if m:
        out["email"] = m.group(0)
    for m in _PHONE.finditer(head):
        raw = m.group(0).strip()
        d = re.sub(r"\D", "", raw)
        if (len(d) == 10 and d[0] in "6789") or (raw.startswith("+") and 10 <= len(d) <= 13) \
           or (len(d) in (11, 12, 13) and d.startswith(("0", "91"))):
            out["phone"] = raw
            break
    return out


def normalize_notice(value) -> str | None:
    """Free text ('2 months', 'Immediate', 'serving') -> one of the notice values in Settings, else 'other'."""
    t = str(value or "").strip().lower()
    if not t:
        return None
    if "immediate" in t or t in ("0", "nil", "none"):
        return "Immediate"
    if "serving" in t:
        return "Serving Notice"
    days = matching.notice_days(t)
    if days == 14:
        days = 15
    return NOTICE_DAYS.get(days, "Other")


def _in_text(field: str, value: str, text: str) -> bool:
    """A contact detail the model returned must really appear in the CV; otherwise it was invented."""
    if field == "email":
        return value.lower() in text.lower()
    return re.sub(r"\D", "", value)[-10:] in re.sub(r"\D", "", text)


def sanitize_parsed(raw: dict, text: str = "") -> dict:
    """Model output -> values that pass the same validation as the candidate form. Anything unusable stays blank."""
    raw = raw or {}
    fields = {}
    for src, key in FROM_LLM.items():
        v = raw.get(src)
        if v is None or str(v).strip() == "":
            continue
        if src == "notice_period":
            v = normalize_notice(v)
        elif key in ("email", "phone") and text and not _in_text(key, str(v), text):
            continue
        try:
            got = clean_candidate({key: v}, partial=True)[key]
        except ValidationError:
            continue
        if got is None or (key in LIMITS and got > LIMITS[key]):
            continue
        fields[key] = got
    for key, v in regex_contacts(text).items():
        if key not in fields:
            try:
                fields[key] = clean_candidate({key: v}, partial=True)[key]
            except ValidationError:
                pass
    skills, seen = [], set()
    for s in raw.get("skills") or []:
        s = "".join(str(s or "").split())
        k = matching.norm_skill(s)
        if s and len(s) <= 60 and k not in seen:
            seen.add(k)
            skills.append(s)
    summary = "".join(str(raw.get("summary") or "").split())[:600] or None
    return {"fields": fields, "skills": skills[:30], "summary": summary,
            "missing_required": [k for k in FIELD_KEYS if k in REQUIRED and k != "date_added" and k not in fields]}


def _clean_name(filename: str) -> str:
    name = os.path.basename(str(filename or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f]", "", name).strip()
    return name[:255] or "cv"


def drop_files(rt: Runtime, keys):
    """Remove stored files; a failure leaves an orphan object rather than blocking the caller."""
    for key in keys:
        if key and rt.blobs:
            try:
                rt.blobs.delete(key)
            except blobstore.StorageError as e:
                log.warning("could not delete %s: %s", key, e)


def _expired_drafts(org_id=None):
    cond = [CvDocument.candidate_id.is_(None), CvDocument.created_at < utcnow() - timedelta(hours=DRAFT_HOURS)]
    if org_id is not None:
        cond.append(CvDocument.org_id == org_id)
    return cond


def purge_drafts(ctx: Ctx, rt: Runtime):
    cond = _expired_drafts(ctx.data_org_id)
    keys = ctx.db.scalars(select(CvDocument.storage_key).where(*cond, CvDocument.storage_key.is_not(None))).all()
    ctx.db.execute(delete(CvDocument).where(*cond))
    drop_files(rt, keys)


def purge_all_drafts(db, rt: Runtime) -> int:
    """Housekeeping for the background worker: unsaved uploads older than a day, in every company."""
    rls.grant_all(db)
    cond = _expired_drafts()
    rows = db.execute(select(CvDocument.id, CvDocument.storage_key).where(*cond).limit(1000)).all()
    if rows:
        db.execute(delete(CvDocument).where(CvDocument.id.in_([r[0] for r in rows])))
        db.commit()
        drop_files(rt, [r[1] for r in rows])
    return len(rows)


def _keep_file(ctx: Ctx, rt: Runtime, data: bytes, mime: str) -> tuple[bytes, str | None]:
    """value for cv_documents.file, storage_key; with a blob store the row keeps only the key."""
    if rt.blobs is None:
        return data, None
    try:
        return b"", rt.blobs.put(ctx.data_org_id, data, mime)
    except blobstore.StorageError as e:
        log.error("%s", e)
        raise ValidationError({"file": "the CV could not be stored right now; please try again"})


def _check_size(rt: Runtime, data: bytes):
    if len(data) > rt.settings.max_cv_bytes:
        raise ValidationError({"file": f"the file is larger than {rt.settings.max_cv_bytes // (1024 * 1024)} MB"})


def parse_upload(ctx: Ctx, rt: Runtime, data: bytes, filename: str) -> dict:
    if not ctx.can_write:
        raise Forbidden("your role is read-only")
    why = ai_unavailable(ctx, rt)
    if why:
        raise ValidationError({"file": f"why - {why}; enter the details by hand"})
    _check_size(rt, data)
    kind, text = cv_text.extract(data)
    check_cap(ctx, rt)
    warning, raw = None, {}
    try:
        raw, usage = rt.llm.parse_cv(text)
        record_usage(ctx, "cv_parse", usage)
    except LlmError as e:
        warning = f"{e}. Only the contact details were read; fill in the rest by hand."
    parsed = sanitize_parsed(raw, text)
    purge_drafts(ctx, rt)
    blob, key = _keep_file(ctx, rt, data, MIME[kind])
    doc = CvDocument(org_id=ctx.data_org_id, candidate_id=None, filename=_clean_name(filename), mime=MIME[kind],
                     size=len(data), file=blob, storage_key=key, text=text, created_by=ctx.user.id,
                     parsed={"skills": parsed["skills"], "summary": parsed["summary"]})
    ctx.db.add(doc)
    try:
        ctx.db.commit()
    except Exception:
        ctx.db.rollback()
        drop_files(rt, [key])
        raise
    f = parsed["fields"]
    return {"cv_id": doc.id, "filename": doc.filename, "fields": f, "skills": parsed["skills"],
            "summary": parsed["summary"], "missing_required": parsed["missing_required"], "warning": warning,
            "duplicate_matches": candidates.find_matches(ctx, f.get("full_name", ""), f.get("email", ""), f.get("phone", ""))}


def claim(ctx: Ctx, cv_id) -> CvDocument:
    """The draft upload a new candidate is being saved with. Must be this user's, in this company, not yet used."""
    try:
        doc = ctx.db.get(CvDocument, int(cv_id))
    except (TypeError, ValueError):
        doc = None
    if not doc or doc.org_id != ctx.data_org_id or doc.candidate_id is not None or doc.created_by != ctx.user.id:
        raise ValidationError({"cv_id": "this CV upload is no longer available; upload it again"})
    return doc


def attach(doc: CvDocument, candidate_id: int):
    doc.candidate_id = candidate_id


def add_to_candidate(ctx: Ctx, rt: Runtime, ref, data: bytes, filename: str) -> dict:
    """Store a CV against an existing candidate. No LLM: the recruiter's saved fields are not overwritten."""
    c = candidates.get_row(ctx, ref)
    candidates.check_can_edit(ctx, c)
    _check_size(rt, data)
    kind, text = cv_text.extract(data)
    blob, key = _keep_file(ctx, rt, data, MIME[kind])
    doc = CvDocument(org_id=ctx.data_org_id, candidate_id=c.id, filename=_clean_name(filename), mime=MIME[kind],
                     size=len(data), file=blob, storage_key=key, text=text, created_by=ctx.user.id)
    ctx.db.add(doc)
    audit.record(ctx, "candidate.cv_upload", "candidate", candidates.public_id(c.seq), {"file": doc.filename})
    try:
        ctx.db.commit()
    except Exception:
        ctx.db.rollback()
        drop_files(rt, [key])
        raise
    return info(ctx, ref)


def _latest(ctx: Ctx, ref) -> CvDocument | None:
    c = candidates.get_row(ctx, ref)
    return ctx.db.scalar(select(CvDocument).where(CvDocument.candidate_id == c.id).order_by(CvDocument.id.desc()).limit(1))


def info(ctx: Ctx, ref) -> dict:
    doc = _latest(ctx, ref)
    if not doc:
        return {"has_cv": False}
    return {"has_cv": True, "filename": doc.filename, "size": doc.size, "mime": doc.mime,
            "uploaded_at": doc.created_at.strftime("%Y-%m-%d %H:%M") if doc.created_at else None}


def download(ctx: Ctx, rt: Runtime, ref) -> tuple[str, str, bytes]:
    doc = _latest(ctx, ref)
    if not doc:
        raise NotFound("no CV is stored for this candidate")
    if doc.storage_key:
        if rt.blobs is None:
            raise NotFound("this CV is in file storage that is not configured on this server")
        try:
            data = rt.blobs.get(doc.storage_key)
        except blobstore.StorageError as e:
            log.error("%s", e)
            raise NotFound("the stored CV file could not be read; try again shortly")
    else:
        data = doc.file
    audit.record(ctx, "candidate.cv_download", "candidate", candidates.public_id(candidates.get_row(ctx, ref).seq),
                 {"file": doc.filename})
    ctx.db.commit()
    return doc.filename, doc.mime, data
