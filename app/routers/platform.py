"""Rise Consulting console: client companies and Rise staff. Never exposes client business data."""
from fastapi import APIRouter, Depends

from ..deps import get_ctx
from ..deps import json_body as _body
from ..services import platform as svc
from ..services.common import Ctx

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/companies")
def companies(ctx: Ctx = Depends(get_ctx)):
    return svc.list_companies(ctx)


@router.post("/companies", status_code=201)
def create_company(data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.create_company(ctx, data)


@router.patch("/companies/{org_id}")
def update_company(org_id: int, data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.update_company(ctx, org_id, data)


@router.post("/companies/{org_id}/vendors", status_code=201)
def create_company_vendor(org_id: int, data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.create_company_vendor(ctx, org_id, data)


@router.get("/companies/{org_id}/users")
def company_users(org_id: int, ctx: Ctx = Depends(get_ctx)):
    return svc.list_company_users(ctx, org_id)


@router.post("/companies/{org_id}/users", status_code=201)
def create_company_user(org_id: int, data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.create_company_user(ctx, org_id, data)


@router.patch("/companies/{org_id}/users/{uid}")
def update_company_user(org_id: int, uid: int, data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.update_company_user(ctx, org_id, uid, data)


@router.post("/companies/{org_id}/users/{uid}/reset-password")
def reset_company_user(org_id: int, uid: int, ctx: Ctx = Depends(get_ctx)):
    return svc.reset_company_user_password(ctx, org_id, uid)


@router.get("/audit")
def audit(limit: int = 100, offset: int = 0, company_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    return svc.list_audit(ctx, limit, offset, company_id)


@router.get("/staff")
def staff(ctx: Ctx = Depends(get_ctx)):
    return svc.list_staff(ctx)


@router.post("/staff", status_code=201)
def create_staff(data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.create_staff(ctx, data)


@router.patch("/staff/{uid}")
def update_staff(uid: int, data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.update_staff(ctx, uid, data)


@router.post("/staff/{uid}/reset-password")
def reset_staff(uid: int, ctx: Ctx = Depends(get_ctx)):
    return svc.reset_staff_password(ctx, uid)