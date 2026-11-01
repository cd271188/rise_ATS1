"""Authentication endpoints. The refresh token lives in an HttpOnly cookie; the access token is returned in JSON."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .. import security
from ..deps import client_ip, get_ctx, get_db, limit
from ..deps import json_body as _body
from ..services import auth as svc
from ..services.common import Ctx

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "ats_refresh"


def _session(request: Request, response: Response, user, refresh: str, db) -> dict:
    s = request.app.state.settings
    response.set_cookie(COOKIE, refresh, max_age=s.refresh_days * 86400, httponly=True, samesite="lax",
                        secure=s.cookie_secure, path="/api/v1/auth")
    token = security.create_access_token(user.id, request.app.state.secret, s.access_minutes)
    return {"access_token": token, "expires_in": s.access_minutes * 60, "user": svc.me(db, user)}


@router.get("/config")
def config(request: Request, db=Depends(get_db)):
    mode = request.app.state.settings.signup_mode
    if mode == "platform":
        return {"signup_open": False, "first_run": False}
    open_ = mode != "closed" or svc.org_count(db) == 0
    return {"signup_open": open_, "first_run": svc.org_count(db) == 0}


@router.post("/signup", status_code=201)
def signup(request: Request, response: Response, data=Depends(_body), db=Depends(get_db)):
    ip = client_ip(request)
    limit(request, f"signup:{ip}", 5, 3600)
    user = svc.signup(db, request.app.state.settings.signup_mode, data.get("company"), data.get("full_name"),
                      data.get("email"), data.get("password"), ip)
    refresh = svc.issue_refresh(db, user, request.app.state.settings.refresh_days)
    db.commit()
    return _session(request, response, user, refresh, db)


@router.post("/login")
def login(request: Request, response: Response, data=Depends(_body), db=Depends(get_db)):
    ip = client_ip(request)
    email = str(data.get("email") or "").strip().lower()[:254]
    limit(request, f"login-ip:{ip}", 5, 60)
    limit(request, f"login-email:{email}", 5, 60)
    try:
        user, refresh = svc.login(db, email, data.get("password"), request.app.state.settings.refresh_days, ip)
    except svc.AuthError:
        raise HTTPException(401, "invalid email or password")
    return _session(request, response, user, refresh, db)


@router.post("/refresh")
def refresh(request: Request, response: Response, db=Depends(get_db)):
    ip = client_ip(request)
    limit(request, f"refresh-ip:{ip}", 60, 60)
    try:
        user, new = svc.rotate_refresh(db, request.cookies.get(COOKIE, ""), request.app.state.settings.refresh_days, ip)
    except svc.AuthError:
        out = JSONResponse({"error": "session expired", "errors": {}}, status_code=401)
        out.delete_cookie(COOKIE, path="/api/v1/auth")
        return out
    return _session(request, response, user, new, db)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db=Depends(get_db)):
    svc.logout(db, request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/api/v1/auth")


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)):
    return svc.me(ctx.db, ctx.user)


@router.post("/password", status_code=204)
def password(data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    svc.change_password(ctx, data.get("current_password"), data.get("new_password"))