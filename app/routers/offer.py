"""Offer letters: the compensation set-up (Rise and the company owner) and PDF generation for candidates."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..deps import get_ctx, json_body, limit as rate_limit
from ..services import offer as svc
from ..services.common import Ctx

router = APIRouter(tags=["offer"])
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


async def _upload(request: Request, ctx: Ctx) -> bytes:
    rate_limit(request, f"offer-template:{ctx.user.id}", 20, 3600)
    blob = await request.body()
    if not blob:
        raise HTTPException(400, "empty upload")
    return blob


def _file(found: tuple[bytes, str, str]) -> Response:
    blob, name, kind = found
    ext = "." + kind
    name = name if name.lower().endswith(ext) else name + ext
    return Response(blob, media_type=MIME[kind], headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- Rise Consulting
@router.get("/platform/companies/{org_id}/offer-structure")
def rise_get(org_id: int, ctc: str = "", ctx: Ctx = Depends(get_ctx)):
    return svc.rise_get(ctx, org_id, ctc)


@router.put("/platform/companies/{org_id}/offer-structure")
def rise_save(org_id: int, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return svc.rise_save(ctx, org_id, data)


@router.put("/platform/companies/{org_id}/offer-structure/template")
async def rise_template(org_id: int, request: Request, filename: str = "", ctx: Ctx = Depends(get_ctx)):
    return svc.rise_template(ctx, org_id, await _upload(request, ctx), filename)


@router.get("/platform/companies/{org_id}/offer-structure/template")
def rise_template_file(org_id: int, ctx: Ctx = Depends(get_ctx)):
    return _file(svc.rise_template_file(ctx, org_id))


@router.post("/platform/companies/{org_id}/offer-structure/send")
def rise_send(org_id: int, ctx: Ctx = Depends(get_ctx)):
    return svc.rise_send(ctx, org_id)


@router.post("/platform/companies/{org_id}/offer-structure/new-version")
def rise_new_version(org_id: int, ctx: Ctx = Depends(get_ctx)):
    return svc.rise_new_version(ctx, org_id)


# ---------------------------------------------------------------- the company owner
@router.get("/offer-structure")
def owner_get(ctc: str = "", ctx: Ctx = Depends(get_ctx)):
    return svc.owner_get(ctx, ctc)


@router.put("/offer-structure/template")
async def owner_template(request: Request, filename: str = "", ctx: Ctx = Depends(get_ctx)):
    return svc.owner_template(ctx, await _upload(request, ctx), filename)


@router.get("/offer-structure/template")
def owner_template_file(ctx: Ctx = Depends(get_ctx)):
    return _file(svc.owner_template_file(ctx))


@router.post("/offer-structure/accept")
def owner_accept(ctx: Ctx = Depends(get_ctx)):
    return svc.owner_accept(ctx)


@router.post("/offer-structure/feedback")
def owner_feedback(data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return svc.owner_feedback(ctx, data)


# ---------------------------------------------------------------- letters for candidates
@router.get("/candidates/{ref}/offer-letters/form")
def letter_form(ref: str, ctx: Ctx = Depends(get_ctx)):
    return svc.letter_form(ctx, ref)


@router.post("/candidates/{ref}/offer-letters/preview")
def letter_preview(ref: str, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return svc.letter_preview(ctx, ref, data)


@router.get("/candidates/{ref}/offer-letters")
def list_letters(ref: str, ctx: Ctx = Depends(get_ctx)):
    return svc.list_letters(ctx, ref)


@router.post("/candidates/{ref}/offer-letters", status_code=201)
def generate(ref: str, request: Request, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    rate_limit(request, f"offer:{ctx.user.id}", 30, 3600)
    return svc.generate(ctx, ref, data)


@router.get("/offer-letters/{letter_id}/pdf")
def letter_pdf(letter_id: int, ctx: Ctx = Depends(get_ctx)):
    blob, name = svc.download(ctx, letter_id)
    return Response(blob, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})