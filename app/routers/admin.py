"""Team, organisation settings and audit log (administrators)."""
from fastapi import APIRouter, Depends

from ..deps import get_ctx, json_body
from ..services import auth as svc
from ..services.common import Ctx

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def users(ctx: Ctx = Depends(get_ctx)):
    return svc.list_users(ctx)


@router.post("/users", status_code=201)
def invite(data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return svc.invite_user(ctx, data)


@router.patch("/users/{uid}")
def update(uid: int, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return svc.update_user(ctx, uid, data)


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, ctx: Ctx = Depends(get_ctx)):
    return svc.reset_password(ctx, uid)


@router.patch("/org")
def org(data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return svc.update_org(ctx, data)


@router.get("/audit")
def audit(limit: int = 100, offset: int = 0, ctx: Ctx = Depends(get_ctx)):
    return svc.list_audit(ctx, limit, offset)