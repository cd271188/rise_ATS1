"""Vendor companies managed by a client's owner or administrators."""
from fastapi import APIRouter, Depends

from ..deps import get_ctx
from ..deps import json_body as _body
from ..services import vendors as svc
from ..services.common import Ctx

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("")
def vendors(ctx: Ctx = Depends(get_ctx)):
    return svc.list_vendors(ctx)


@router.post("", status_code=201)
def create_vendor(data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.create_vendor(ctx, data)


@router.patch("/{vendor_id}")
def update_vendor(vendor_id: int, data=Depends(_body), ctx: Ctx = Depends(get_ctx)):
    return svc.update_vendor(ctx, vendor_id, data)


@router.get("/{vendor_id}/users")
def vendor_users(vendor_id: int, ctx: Ctx = Depends(get_ctx)):
    return svc.list_vendor_users(ctx, vendor_id)


@router.post("/{vendor_id}/users/{uid}/reset-password")
def reset_vendor_user(vendor_id: int, uid: int, ctx: Ctx = Depends(get_ctx)):
    return svc.reset_vendor_user_password(ctx, vendor_id, uid)