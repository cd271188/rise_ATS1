"""Interview entries. The newest entry's status becomes the candidate's current status (feedback loop)."""
from sqlalchemy import select

from ..fields import DEFAULT_STATUS
from ..models import Candidate, Interview, utcnow
from . import audit
from .candidates import check_can_edit, find_row, parse_ref, public_id, scope
from .common import Ctx, Forbidden, NotFound, ValidationError
from .validation import clean_interview

COLS = ("interview_stage", "interview_date", "interview_time", "interviewer_panel", "feedback", "status",
        "next_action", "next_followup_date")


def _dict(i: Interview, c: Candidate) -> dict:
    d = {k: getattr(i, k) for k in COLS}
    d.update(id=i.id, candidate_id=public_id(c.seq), full_name=c.full_name, client=c.client,
             job_req_id=c.job_req_id, recruiter=c.recruiter,
             created_at=i.created_at.strftime("%Y-%m-%d %H:%M") if i.created_at else None)
    return d


def sync_status(ctx: Ctx, cand: Candidate):
    latest = ctx.db.scalar(select(Interview.status).where(
        Interview.candidate_id == cand.id, Interview.status.is_not(None)).order_by(Interview.id.desc()).limit(1))
    cand.current_status = latest or DEFAULT_STATUS
    cand.version += 1
    cand.last_updated = utcnow()


def _row(ctx: Ctx, iid: int) -> tuple[Interview, Candidate]:
    r = ctx.db.execute(select(Interview, Candidate).join(Candidate, Candidate.id == Interview.candidate_id).where(
        Interview.id == iid, Interview.org_id == ctx.data_org_id, *scope(ctx))).first()
    if not r:
        raise NotFound("interview entry not found")
    return r[0], r[1]


def list_interviews(ctx: Ctx, candidate_ref=None) -> list[dict]:
    stmt = select(Interview, Candidate).join(Candidate, Candidate.id == Interview.candidate_id).where(
        Interview.org_id == ctx.data_org_id, *scope(ctx)).order_by(Interview.id)
    if candidate_ref:
        stmt = stmt.where(Candidate.seq == (parse_ref(candidate_ref) or 0))
    return [_dict(i, c) for i, c in ctx.db.execute(stmt)]


def _target(ctx: Ctx, ref) -> Candidate:
    cand = find_row(ctx, ref)
    if not cand:
        raise ValidationError({"candidate_id": "candidate does not exist"})
    check_can_edit(ctx, cand)
    return cand


def create_interview(ctx: Ctx, data: dict, commit: bool = True) -> dict:
    ref, vals = clean_interview(data)
    cand = _target(ctx, ref)
    # Interview history belongs to the client pipeline; vendor users still see only interviews for their own candidates.
    i = Interview(org_id=ctx.data_org_id, candidate_id=cand.id, created_by=ctx.user.id, **vals)
    ctx.db.add(i)
    ctx.db.flush()
    sync_status(ctx, cand)
    audit.record(ctx, "interview.create", "interview", i.id, {"candidate": public_id(cand.seq), "status": vals["status"]})
    if commit:
        ctx.db.commit()
    return _dict(i, cand)


def update_interview(ctx: Ctx, iid: int, data: dict) -> dict:
    i, old = _row(ctx, iid)
    check_can_edit(ctx, old)
    ref, vals = clean_interview(data)
    new = _target(ctx, ref)
    i.candidate_id = new.id
    for k, v in vals.items():
        setattr(i, k, v)
    ctx.db.flush()
    for c in {old.id: old, new.id: new}.values():
        sync_status(ctx, c)
    audit.record(ctx, "interview.update", "interview", i.id, {"candidate": public_id(new.seq), "status": vals["status"]})
    ctx.db.commit()
    return _dict(i, new)


def delete_interview(ctx: Ctx, iid: int):
    if not ctx.is_admin:
        raise Forbidden("only administrators can delete interview entries")
    i, cand = _row(ctx, iid)
    ctx.db.delete(i)
    ctx.db.flush()
    sync_status(ctx, cand)
    audit.record(ctx, "interview.delete", "interview", i.id, {"candidate": public_id(cand.seq)})
    ctx.db.commit()
