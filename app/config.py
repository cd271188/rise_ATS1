"""Settings come from environment variables prefixed ATS_ (or a .env file)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ATS_", extra="ignore")

    database_url: str = "sqlite:///./ats_platform.db"
    secret_key: str = ""                        # empty: generated once and kept in ats_secret.key
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    # platform: only Rise Consulting staff create client companies (default)
    # open: anyone may create a company; closed: first-run setup only (single self-hosted company)
    signup_mode: str = "platform"
    cookie_secure: bool = False                 # set true behind HTTPS
    trust_proxy: bool = False                  # honour X-Forwarded-For for client IP (only behind your proxy)
    access_minutes: int = 15
    refresh_days: int = 14
    rate_limit_enabled: bool = True
    # Used by `alembic` and operator commands (grant/reap staff access): the owner role that may change the schema.
    # Empty = use database_url. The running app should use a restricted role instead (see README, "Rise staff access").
    migration_database_url: str = ""
    # Postgres row-level security. true = refuse to start unless the database login can neither be superuser nor bypass RLS.
    rls_enabled: bool = False
    auto_create_tables: bool = True             # create_all on start; use Alembic for Postgres
    max_json_bytes: int = 1 * 1024 * 1024
    max_upload_bytes: int = 15 * 1024 * 1024
    import_row_cap: int = 5000
    # AI features. No key = CV parsing and JD requirement extraction are off; jobs and matching still work by hand.
    # Any OpenAI-compatible endpoint works: OpenAI itself (key only), or a self-hosted model served by ollama, vLLM,
    # LM Studio, llama.cpp or a gateway such as OpenRouter (set llm_base_url, e.g. http://localhost:11434/v1).
    # To switch model, change llm_model / llm_base_url and restart.
    openai_api_key: str = ""
    llm_api_key: str = ""                      # key for llm_base_url; falls back to openai_api_key; local servers need none
    llm_base_url: str = ""
    llm_model: str = "gpt-4o-mini"             # e.g. gpt-oss:20b (Ollama), openai/gpt-oss-20b (vLLM), qwen3:14b
    llm_json_mode: str = "auto"                # auto | schema (strict json_schema) | object (plain JSON, schema in the prompt)
    llm_max_tokens: int = 4000                 # reasoning models (gpt-oss, qwen3) spend tokens thinking before they answer
    llm_timeout_seconds: int = 120
    llm_label: str = ""                        # shown to users as where text is sent; default depends on llm_base_url
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = "./models_cache"
    max_cv_bytes: int = 5 * 1024 * 1024
    libreoffice_path: str = ""
    ai_monthly_cap: int = 5000                  # LLM calls per company per calendar month
    # Deployment. environment=production refuses to start with unsafe settings (see check_production).
    environment: str = "development"
    workers: int = 1                            # uvicorn worker processes for 'python -m app'
    redis_url: str = ""                         # shared rate limits across workers; empty = per-process memory
    # Where CV files live. db = in the database (fine for small installs); disk = a directory; s3 = S3-compatible bucket.
    storage_backend: str = "db"
    storage_dir: str = "./cv_files"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""                   # MinIO / other S3-compatible services; empty = AWS
    s3_region: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    index_interval_seconds: int = 30           # background indexer (python -m app.worker) polling interval


def check_production(s: Settings) -> list[str]:
    """Problems that make a multi-company deployment unsafe. Empty when environment is not production."""
    if s.environment.lower() != "production":
        return []
    bad = []
    if not s.database_url.startswith(("postgresql+psycopg://", "postgresql://")):
        bad.append("ATS_DATABASE_URL must use PostgreSQL with the psycopg driver")
    if not s.secret_key:
        bad.append("ATS_SECRET_KEY must be set (all workers must share it)")
    if not s.cookie_secure:
        bad.append("ATS_COOKIE_SECURE must be true (serve over HTTPS)")
    if s.auto_create_tables:
        bad.append("ATS_AUTO_CREATE_TABLES must be false (use 'alembic upgrade head')")
    if not s.rls_enabled:
        bad.append("ATS_RLS_ENABLED must be true (row-level security: the app must connect as a non-superuser role)")
    if s.rate_limit_enabled and s.workers > 1 and not s.redis_url:
        bad.append("ATS_REDIS_URL must be set when running more than one worker (rate limits are per process otherwise)")
    if s.storage_backend == "db":
        bad.append("ATS_STORAGE_BACKEND must be s3 or disk in production (CV files would bloat the database)")
    return bad
