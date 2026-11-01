"""SQLAlchemy models. Every business table carries org_id (tenant isolation). Dates are ISO text, as in v1."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy import false, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from .vector_type import EmbeddingVector


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    team_edit: Mapped[bool] = mapped_column(Boolean, default=True)  # (parameter) server_default: _ServerDefaultArgument | None
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    is_platform: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    parent_org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))  # set -> a vendor of that client
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # opt-in: CVs/JDs go to OpenAI
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    platform_role: Mapped[str | None] = mapped_column(String(20))  # creator | rise_admin; set only for Rise staff
    platform_permissions: Mapped[list | None] = mapped_column(JSON)  # what a rise_admin may do; the creator may do all
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OrgCounter(Base):
    __tablename__ = "org_counters"

    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    next_candidate: Mapped[int] = mapped_column(Integer, default=1)
    next_job: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class ListValue(Base):
    __tablename__ = "list_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    list_name: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Candidate(Base):
    __tablename__ = "candidates"

    __table_args__ = (
        UniqueConstraint("org_id", "seq", name="uq_candidate_org_seq"),
        Index("ix_cand_org_added", "org_id", "date_added"),
        Index("ix_cand_org_status", "org_id", "current_status"),
        Index("ix_cand_org_recruiter", "org_id", "recruiter"),
        Index("ix_cand_org_client", "org_id", "client"),
        Index("ix_cand_dup_name", "org_id", "name_key"),
        Index("ix_cand_dup_email", "org_id", "email_key"),
        Index("ix_cand_dup_phone", "org_id", "phone_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    vendor_org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))  # null = added by the client's own team

    date_added: Mapped[str | None] = mapped_column(Text)
    recruiter: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    current_company: Mapped[str | None] = mapped_column(Text)
    current_location: Mapped[str | None] = mapped_column(Text)
    total_experience_years: Mapped[float | None] = mapped_column(Float)
    current_ctc_lakhs: Mapped[float | None] = mapped_column(Float)
    expected_ctc_lakhs: Mapped[float | None] = mapped_column(Float)
    official_notice_period: Mapped[str | None] = mapped_column(Text)
    earliest_joining_date: Mapped[str | None] = mapped_column(Text)
    how_soon_can_join: Mapped[str | None] = mapped_column(Text)
    existing_offer: Mapped[str | None] = mapped_column(Text)
    offer_details: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    primary_skill_role: Mapped[str | None] = mapped_column(Text)
    client: Mapped[str | None] = mapped_column(Text)
    job_req_id: Mapped[str | None] = mapped_column(Text)
    profile_submitted_to_client: Mapped[str | None] = mapped_column(Text)
    client_submission_date: Mapped[str | None] = mapped_column(Text)
    recruiter_notes: Mapped[str | None] = mapped_column(Text)

    current_status: Mapped[str] = mapped_column(String(40), default="To Be Scheduled")
    name_key: Mapped[str] = mapped_column(String(255), default="")
    email_key: Mapped[str | None] = mapped_column(String(255))
    phone_key: Mapped[str | None] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class Interview(Base):
    __tablename__ = "interviews"

    __table_args__ = (Index("ix_interview_org_cand", "org_id", "candidate_id"),
                      Index("ix_interview_candidate_id", "candidate_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    interview_stage: Mapped[str | None] = mapped_column(Text)
    interview_date: Mapped[str | None] = mapped_column(Text)
    interview_time: Mapped[str | None] = mapped_column(Text)
    interviewer_panel: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    next_followup_date: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    __table_args__ = (Index("ix_audit_org_at", "org_id", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    diff: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OfferStructure(Base):
    __tablename__ = "offer_structures"

    """A company's offer letter template plus the compensation components behind its pay placeholders. One row per version."""

    __table_args__ = (Index("ix_offer_struct_org", "org_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | in_review | changes_requested | active | superseded
    template_name: Mapped[str | None] = mapped_column(String(255))
    template_kind: Mapped[str | None] = mapped_column(String(8))  # docx | pdf
    template_file: Mapped[bytes | None] = mapped_column(LargeBinary)
    components: Mapped[list | None] = mapped_column(JSON)
    events: Mapped[list | None] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[int | None] = mapped_column(Integer)


class OfferLetter(Base):
    __tablename__ = "offer_letters"

    __table_args__ = (Index("ix_offer_letter_cand", "org_id", "candidate_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    structure_id: Mapped[int] = mapped_column(ForeignKey("offer_structures.id"))
    vendor_org_id: Mapped[int | None] = mapped_column(Integer)
    generated_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    values: Mapped[dict | None] = mapped_column(JSON)
    pdf: Mapped[bytes] = mapped_column(LargeBinary)
    pdf_engine: Mapped[str] = mapped_column(String(20), default="builtin")


class CvDocument(Base):
    __tablename__ = "cv_documents"

    """An uploaded CV. candidate_id is NULL while it is only a parse draft (not yet saved with a candidate)."""

    __table_args__ = (Index("ix_cv_org_cand", "org_id", "candidate_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    file: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)  # empty when the bytes live in the blob store
    storage_key: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    parsed: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    """Search index for one candidate: normalised skills plus an embedding. Rebuilt whenever text_hash changes."""

    __table_args__ = (Index("ix_profile_org", "org_id"),)

    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    summary: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[list | None] = mapped_column(JSON)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_vector: Mapped[object | None] = mapped_column(EmbeddingVector(384))
    model: Mapped[str | None] = mapped_column(String(100))
    text_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    __table_args__ = (
        UniqueConstraint("org_id", "seq", name="uq_job_org_seq"),
        Index("ix_job_org_status", "org_id", "status"),
        Index("ix_job_org_received", "org_id", "received_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    client: Mapped[str | None] = mapped_column(Text)
    client_ref: Mapped[str | None] = mapped_column(String(100))
    received_on: Mapped[str | None] = mapped_column(String(10))
    jd_filename: Mapped[str | None] = mapped_column(String(255))
    jd_mime: Mapped[str | None] = mapped_column(String(100))
    jd_size: Mapped[int | None] = mapped_column(Integer)
    jd_text: Mapped[str | None] = mapped_column(Text)
    jd_file: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    jd_storage_key: Mapped[str | None] = mapped_column(String(200))
    requirements: Mapped[dict | None] = mapped_column(JSON)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_vector: Mapped[object | None] = mapped_column(EmbeddingVector(384))
    status: Mapped[str] = mapped_column(String(20), default="Open")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class AIUsage(Base):
    __tablename__ = "ai_usage"

    __table_args__ = (Index("ix_ai_usage_org_at", "org_id", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StaffAccessGrant(Base):
    __tablename__ = "staff_access_grants"

    """A time-limited read-only database login handed to an operator (see services/breakglass.py). Operator tooling only."""

    id: Mapped[int] = mapped_column(primary_key=True)
    pg_role: Mapped[str] = mapped_column(String(63))
    operator: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    ticket: Mapped[str | None] = mapped_column(String(100))
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
