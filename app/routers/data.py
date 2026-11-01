"""Business endpoints: candidates, interviews, dashboard, lists, Excel import/export."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from ..deps import get_ctx, json_body, limit as rate_limit
from ..fields import CANDIDATE_FIELDS, INTERVIEW_FIELDS, SENSITIVE
from ..services import candidates as cand, dashboard as dash, erasure, excel_io, interviews as inter, lists as lists_svc
from ..services import vendors as vendors_svc
from ..services.common import Ctx
from ..services.runtime import ai_on

router = APIRouter()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/meta")
def meta(request: Request, ctx: Ctx = Depends(get_ctx)):
    fields = [{"key": k, "label": l, "type": t, "flag": f, "list": ls, "hint": h}
              for k, l, t, f, ls, h in CANDIDATE_FIELDS if ctx.is_admin or k not in SENSITIVE]
    return {"fields": fields, "interview_fields": INTERVIEW_FIELDS, "lists": lists_svc.lists_for(ctx),
            "vendors": vendors_svc.options(ctx), "today": ctx.today().isoformat(),
            "ai_enabled": ai_on(ctx, request.app.state.ai) and not ctx.vendor_id and not ctx.org.is_platform,
            "ai_where": request.app.state.ai.ai_where}


# -------------------------------- candidates --------------------------------

@router.get("/candidates")
def list_candidates(q: str = "", recruiter: str = "", client: str = "", status: str = "", duplicate: str = "",
                    date_from: str = "", date_to: str = "", sort: str = "candidate_id", direction: str = "asc",
                    limit: int = 50, offset: int = 0, f: list[str] = Query(default=[]), max_length: int = 30,
                    vendor_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    return cand.list_candidates(ctx, q, recruiter, client, status, duplicate, date_from, date_to, sort,
                                "desc" if direction == "desc" else "asc", limit, offset, f, vendor_id)


@router.post("/candidates", status_code=201)
def create_candidate(data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return cand.create_candidate(ctx, data)


@router.get("/candidates/duplicates")
def duplicates(name: str = "", email: str = "", phone: str = "", exclude: str = "", ctx: Ctx = Depends(get_ctx)):
    return cand.find_matches(ctx, name[:200], email[:254], phone[:50], exclude)


@router.get("/candidates/{ref}")
def get_candidate(ref: str, ctx: Ctx = Depends(get_ctx)):
    return cand.get_candidate(ctx, ref)


@router.patch("/candidates/{ref}")
def update_candidate(ref: str, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return cand.update_candidate(ctx, ref, data)


@router.delete("/candidates/{ref}", status_code=204)
def delete_candidate(ref: str, ctx: Ctx = Depends(get_ctx)):
    cand.delete_candidate(ctx, ref)
    return Response(status_code=204)


@router.delete("/candidates/{ref}/permanent", status_code=204)
def purge_candidate(ref: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    erasure.purge_candidate(ctx, request.app.state.ai, ref)
    return Response(status_code=204)


# -------------------------------- interviews --------------------------------

@router.get("/interviews")
def list_interviews(candidate_id: str = "", ctx: Ctx = Depends(get_ctx)):
    return inter.list_interviews(ctx, candidate_id or None)


@router.post("/interviews", status_code=201)
def create_interview(data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return inter.create_interview(ctx, data)


@router.put("/interviews/{iid}")
def update_interview(iid: int, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return inter.update_interview(ctx, iid, data)


@router.delete("/interviews/{iid}", status_code=204)
def delete_interview(iid: int, ctx: Ctx = Depends(get_ctx)):
    inter.delete_interview(ctx, iid)
    return Response(status_code=204)


# -------------------------------- dashboard / lists --------------------------------

@router.get("/dashboard")
def dashboard(on: str = "", ctx: Ctx = Depends(get_ctx)):
    try:
        day = date.fromisoformat(on) if on else None
    except ValueError:
        raise HTTPException(400, "use the format YYYY-MM-DD")
    return dash.dashboard(ctx, day)


@router.get("/reports/recruiters")
def recruiter_report(ctx: Ctx = Depends(get_ctx)):
    return dash.recruiter_report(ctx)


@router.get("/followups/due")
def followups_due(ctx: Ctx = Depends(get_ctx)):
    return dash.followups_due(ctx)


@router.get("/lists")
def get_lists(ctx: Ctx = Depends(get_ctx)):
    return lists_svc.lists_for(ctx)


@router.put("/lists")
def put_lists(data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    return lists_svc.put_lists(ctx, data)


# -------------------------------- excel --------------------------------

@router.get("/export.xlsx")
def export_xlsx(request: Request, ctx: Ctx = Depends(get_ctx)):
    rate_limit(request, f"export:{ctx.user.id}", 10, 3600)
    blob = excel_io.export_workbook(ctx)
    return Response(blob, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="ats_export.xlsx"'})


@router.post("/import")
async def import_xlsx(request: Request, ctx: Ctx = Depends(get_ctx)):
    rate_limit(request, f"import:{ctx.user.id}", 5, 3600)
    blob = await request.body()
    if not blob:
        raise HTTPException(400, "empty upload")
    return await run_in_threadpool(excel_io.import_workbook, ctx, blob, request.app.state.settings.import_row_cap)
