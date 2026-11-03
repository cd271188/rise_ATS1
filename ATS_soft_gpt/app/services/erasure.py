"""Permanent removal of one candidate (a data-subject erasure request). Ordinary delete only hides the record."""
from sqlalchemy import delete, select, update

from .. import rls
from ..models import AuditLog, Candidate, CandidateProfile, CvDocument, Interview, OfferLetter, Organization
from . import audit, candidates, cv
from .common import Ctx, Forbidden, NotFound
from .runtime import Runtime
from .validation import parse_ref


def purge_candidate(ctx: Ctx, rt: Runtime, ref) -> None:
    """Admin only. Works on live and already-deleted candidates. Removes the record, interviews, offer letters, CV files
    and search index; blanks the personal details kept in earlier audit entries; leaves an audit entry with the ID only."""
    if not ctx.is_admin or ctx.vendor_id:
        raise Forbidden("only a client administrator can permanently delete a candidate")
    seq = parse_ref(ref)
    c = ctx.db.scalar(select(Candidate).where(Candidate.org_id == ctx.data_org_id, Candidate.seq == seq)) if seq else None
    if not c:
        raise NotFound("candidate not found")
    pid = candidates.public_id(c.seq)
    keys = ctx.db.scalars(select(CvDocument.storage_key).where(CvDocument.candidate_id == c.id,
                                                               CvDocument.storage_key.is_not(None))).all()
    orgs = [ctx.data_org_id, *ctx.db.scalars(select(Organization.id).where(Organization.parent_org_id == ctx.data_org_id))]
    rls.grant(ctx.db, *orgs)
    ctx.db.execute(update(AuditLog).where(AuditLog.entity == "candidate", AuditLog.entity_id == pid,
                                          AuditLog.org_id.in_(orgs)).values(diff={"erased": True}))
    for model in (OfferLetter, Interview, CvDocument, CandidateProfile):
        ctx.db.execute(delete(model).where(model.candidate_id == c.id))
    ctx.db.delete(c)
    audit.record(ctx, "candidate.purge", "candidate", pid)
    ctx.db.commit()
    cv.drop_files(rt, keys)
