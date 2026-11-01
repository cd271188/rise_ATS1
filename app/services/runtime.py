"""The pieces AI features need, held on app.state.ai so tests can swap in fakes: settings, LLM client, embedder."""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..config import Settings
from ..models import AIUsage, Organization
from .common import Ctx, QuotaExceeded


@dataclass
class Runtime:
    settings: Settings
    llm: object | None = None
    embedder: object | None = None
    blobs: object | None = None  # blobstore.BlobStore; None = CV files stay in the database

    @property
    def ai_enabled(self) -> bool:
        return self.llm is not None

    @property
    def ai_where(self) -> str:
        """Where company text goes when AI is on, in words for the settings page."""
        s = self.settings
        if s.llm_label:
            return s.llm_label
        return f"the AI server this service is set up with ({s.llm_label})" if s.llm_base_url else f"OpenAI (United States)"


def build(settings: Settings) -> Runtime:
    from .embeddings import FastEmbedder
    llm = None
    if settings.llm_base_url or settings.openai_api_key or settings.llm_api_key:
        from .llm import ChatLLm
        llm = ChatLLm(settings.llm_api_key or settings.openai_api_key, settings.llm_model, settings.llm_base_url,
                      settings.llm_json_mode, settings.llm_max_tokens, settings.llm_timeout_seconds)
    from . import blobstore
    return Runtime(settings, llm, FastEmbedder(settings.embedding_model, settings.embedding_cache_dir), blobstore.build(settings))


def ai_unavailable(ctx: Ctx, rt: Runtime) -> str | None:
    """Why AI cannot be used right now, or None when it can. The server needs a key AND the company (the client, for a
    vendor user) must have switched AI on: anything sent to the AI model is the company's decision."""
    if not rt.ai_enabled:
        return "AI is not set up for this server"
    org_id = ctx.data_org_id if not ctx.user.platform_role else ctx.data_org_id_override
    org = ctx.db.get(Organization, org_id) if org_id else None
    if not org or not org.ai_enabled:
        return "AI is switched off for your company"
    return None


def ai_on(ctx: Ctx, rt: Runtime) -> bool:
    return ai_unavailable(ctx, rt) is None


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1)


def check_cap(ctx: Ctx, rt: Runtime):
    org_id = ctx.data_org_id if not ctx.user.platform_role else ctx.data_org_id_override
    if org_id is None:
        raise QuotaExceeded("select a client company before using AI")
    used = ctx.db.scalar(select(func.count()).select_from(AIUsage).where(
        AIUsage.org_id == org_id, AIUsage.at >= _month_start()))
    if used >= rt.settings.ai_monthly_cap:
        raise QuotaExceeded("this month's AI usage limit for your company has been reached")


def record_usage(ctx: Ctx, kind: str, usage: tuple[int, int]):
    org_id = ctx.data_org_id if not ctx.user.platform_role else ctx.data_org_id_override
    if org_id is None:
        raise QuotaExceeded("select a client company before using AI")
    ctx.db.add(AIUsage(org_id=org_id, user_id=ctx.user.id, kind=kind,
                       input_tokens=int(usage[0] or 0), output_tokens=int(usage[1] or 0)))
