"""Per-candidate search index (skills + embedding), built lazily and rebuilt when the underlying text changes."""
import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..models import Candidate, CandidateProfile, CvDocument, utcnow
from . import embeddings, matching
from .common import Ctx
from .runtime import Runtime

log = logging.getLogger("ats.profiles")
BATCH = 64


def profile_text(c: Candidate, skills: list[str], summary: str | None) -> str:
    """What gets embedded: role, skills, experience, location and the CV summary. Never contact details, notes or DOB."""
    parts = [c.primary_skill_role or ""]
    if skills:
        parts.append(f"Skills: " + ", ".join(skills))
    if c.total_experience_years is not None:
        parts.append(f"{c.total_experience_years:g} years of experience")
    if c.current_location:
        parts.append(f"Based in {c.current_location}")
    if summary:
        parts.append(summary)
    return " ".join(p for p in parts if p)


def _parsed_by_candidate(ctx: Ctx, ids: list[int]) -> dict[int, dict]:
    out = {}
    if not ids:
        return out
    rows = ctx.db.execute(select(CvDocument.candidate_id, CvDocument.parsed).where(
        CvDocument.org_id == ctx.data_org_id, CvDocument.candidate_id.in_(ids), CvDocument.parsed.is_not(None))
        .order_by(CvDocument.id)).all()  
    for cid, parsed in rows:   # ascending id, so the newest CV wins
        out[cid] = parsed or {}
    return out


def ensure(ctx: Ctx, rt: Runtime, rows: list[Candidate], cap: int = 300) -> tuple[dict[int, dict], int]:
    """Profiles for these candidates as {candidate_id: {skills, summary, vec}}. Embeds up to 'cap' missing or changed
    ones. Returns (profiles, number still waiting to be embedded). 'vec' is None when there is no usable embedding."""
    ids = [c.id for c in rows]
    existing = {p.candidate_id: p for p in ctx.db.scalars(select(CandidateProfile).where(CandidateProfile.candidate_id.in_(ids)))} if ids else {}
    parsed = _parsed_by_candidate(ctx, ids)
    embedder = rt.embedder
    model = getattr(embedder, "model_name", None) or rt.settings.embedding_model
    out, todo, available = {}, [], {}
    for c in rows:
        p = parsed.get(c.id) or {}
        skills = [s for s in p.get("skills") or []] or matching.split_skills(c.primary_skill_role)
        skills = list(dict.fromkeys(matching.norm_skill(s) for s in skills if matching.norm_skill(s)))
        summary = p.get("summary")
        text = profile_text(c, skills, summary)
        digest = hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()
        row = existing.get(c.id)
        stored_vec = embeddings.read_row(row, ctx.db) if row is not None else None
        fresh = row is not None and row.text_hash == digest and stored_vec is not None
        available[c.id] = fresh
        out[c.id] = {"skills": skills, "summary": summary,
                     "vec": stored_vec if fresh and ctx.db.get_bind().dialect.name != "postgresql" else None}
        if fresh and ctx.db.get_bind().dialect.name == "postgresql" and row.embedding_vector is None:
            # One-time lazy conversion for SQLite-to-PostgreSQL imports not backfilled by the migration.
            embeddings.write_row(row, stored_vec, ctx.db)
        if not fresh and embedder is not None and text:
            todo.append((c, skills, summary, text, digest, row))
    batch = todo[:cap]
    for i in range(0, len(batch), BATCH):
        chunk = batch[i: i + BATCH]
        try:
            vecs = embedder.embed([t[3] for t in chunk])
        except embeddings.EmbeddingError as e:
            log.warning("embedding failed: %s", e)
            break
        for (c, skills, summary, text, digest, row), vec in zip(chunk, vecs):
            if row is None:
                row = CandidateProfile(candidate_id=c.id, org_id=ctx.data_org_id)
                ctx.db.add(row)
            row.skills, row.summary, row.model = skills, summary, model
            embeddings.write_row(row, vec, ctx.db)
            row.text_hash, row.updated_at = digest, utcnow()
            out[c.id]["vec"] = vec if ctx.db.get_bind().dialect.name != "postgresql" else None
            available[c.id] = True
    try:
        ctx.db.commit()
    except IntegrityError:  # the background indexer saved the same profile first; the vectors in 'out' are still right
        ctx.db.rollback()
    return out, sum(1 for c in rows if not available[c.id])
