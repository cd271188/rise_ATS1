"""Application factory: middleware, error shape, routers and the static front end."""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import rls, security
from .config import Settings, check_production
from .db import create_tables, make_engine, make_sessionmaker
from .import ratelimit
from .ratelimit import RateLimited
from .routers import admin, ai, auth, data, health, offer, platform, vendors
from .services import offer_docs, runtime
from .services.common import Conflict, Forbidden, NotFound, QuotaExceeded, ValidationError

log = logging.getLogger("ats")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def _secret(settings: Settings) -> str:
    if settings.secret_key:
        return settings.secret_key
    path = Path("ats_secret.key")
    if path.exists():
        return path.read_text().strip()
    key = security.new_secret()
    path.write_text(key)
    return key


def _error(status: int, message: str, errors: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse({"error": message, "errors": errors or {}, **extra}, status_code=status)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    problems = check_production(settings)
    if problems:
        raise RuntimeError("unsafe production configuration:\n - " + "\n - ".join(problems))
    app = FastAPI(title="ATS Platform by Rise Consulting", version="2.0", docs_url="/docs", redoc_url=None)

    engine = make_engine(settings.database_url)
    if settings.auto_create_tables:
        create_tables(engine)
    if settings.rls_enabled:
        problem = rls.role_problem(engine)
        if problem:
            raise RuntimeError("row-level security: " + problem)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.secret = _secret(settings)
    app.state.limiter = ratelimit.build(settings)
    app.state.ai = runtime.build(settings)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        api = path.startswith("/api/")
        if api and request.method not in SAFE_METHODS:
            if not request.headers.get("x-requested-with"):
                return _error(403, "missing X-Requested-With header")
            length = request.headers.get("content-length")
            if "chunked" in request.headers.get("transfer-encoding", "").lower():
                return _error(411, "Content-Length required")
            size = int(length) if length and length.isdigit() else 0
            cv_upload = (path.endswith("/cv/parse") or (path.endswith("/cv") and path.startswith("/api/v1/candidates/"))
                         or (path.endswith("/jd") and path.startswith("/api/v1/jobs/")))
            upload = cv_upload or path.endswith(("/import", "/template"))
            if cv_upload:
                cap = settings.max_cv_bytes + 4096
            else:
                cap = settings.max_upload_bytes if path.endswith("/import") else offer_docs.MAX_TEMPLATE_BYTES + 4096
            if size > (cap if upload else settings.max_json_bytes):
                return _error(413, "request body too large")
            ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if size and ctype != ("application/octet-stream" if upload else "application/json"):
                return _error(415, "unsupported content type")
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        if not path.startswith("/docs") and path != "/openapi.json":
            h["Content-Security-Policy"] = CSP
        if api:
            h["Cache-Control"] = "no-store"
        elif "cache-control" not in h:
            h["Cache-Control"] = "no-cache"
        if settings.cookie_secure:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.exception_handler(ValidationError)
    async def _validation(_, e: ValidationError):
        return _error(400, "validation failed", e.errors)

    @app.exception_handler(NotFound)
    async def _not_found(_, e):
        return _error(404, str(e) or "not found")

    @app.exception_handler(Forbidden)
    async def _forbidden(_, e):
        return _error(403, str(e) or "forbidden")

    @app.exception_handler(Conflict)
    async def _conflict(_, e: Conflict):
        return _error(409, str(e), current=e.current)

    @app.exception_handler(QuotaExceeded)
    async def _quota(_, e: QuotaExceeded):
        return _error(429, str(e))

    @app.exception_handler(RateLimited)
    async def _limited(_, e: RateLimited):
        r = _error(429, "too many requests; try again later")
        r.headers["Retry-After"] = str(e.retry_after)
        return r

    @app.exception_handler(ValueError)
    async def _value(_, e: ValueError):
        return _error(400, str(e))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_, e: StarletteHTTPException):
        return _error(e.status_code, str(e.detail)) if e.status_code != 404 else "not found"

    @app.exception_handler(RequestValidationError)
    async def _request(_, e: RequestValidationError):
        errors = {".".join(str(p) for p in x["loc"][1:]) or "request": x["msg"] for x in e.errors()}
        return _error(400, "invalid request", errors)

    @app.exception_handler(Exception)
    async def _crash(request: Request, e: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "internal error")

    api = "/api/v1"
    app.include_router(health.router)
    app.include_router(auth.router, prefix=api)
    app.include_router(data.router, prefix=api)
    app.include_router(admin.router, prefix=api)
    app.include_router(platform.router, prefix=api)
    app.include_router(vendors.router, prefix=api)
    app.include_router(offer.router, prefix=api)
    app.include_router(ai.router, prefix=api)

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app