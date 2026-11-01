"""Request-scoped dependencies: DB session, authenticated context, rate limiting."""
from typing import Any

import jwt
from fastapi import Body, Depends, HTTPException, Request

from . import rls, security
from .services.auth import org_active
from .models import Organization, User
from .ratelimit import RateLimited
from .services.common import Ctx

PASSWORD_CHANGE_PATHS = {"/api/v1/auth/me", "/api/v1/auth/password"}

def client_ip(request: Request) -> str:
    if request.app.state.settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()[:64]  # the address our own proxy appended
    return request.client.host if request.client else ""

def json_body(data: Any = Body(...)) -> dict:
    if not isinstance(data, dict):
        raise HTTPException(400, "expected a JSON object")
    return data

def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()

def limit(request: Request, key: str, count: int, window: int):
    ok, retry = request.app.state.limiter.hit(key, count, window)
    if not ok:
        raise RateLimited(retry)

def get_ctx(request: Request, db=Depends(get_db)) -> Ctx:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "not signed in")
    try:
        uid = security.decode_access_token(header[7:].strip(), request.app.state.secret)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "session expired")
    user = db.get(User, uid)
    if not user or not user.is_active:
        raise HTTPException(401, "not signed in")
    org = db.get(Organization, user.org_id)
    # Vendor recruiters share the parent client's requirement pipeline.
    rls.grant(db, user.org_id, org.parent_org_id)
    if not org_active(db, org):
        raise HTTPException(401, "this company's account is suspended")
    limit(request, f"user:{user.id}", 120, 60)
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(403, "you must set a new password before continuing")
    return Ctx(db=db, user=user, ip=client_ip(request))
