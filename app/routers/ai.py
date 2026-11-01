"""CV upload/parse/download, jobs and candidate matching."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from ..deps import get_ctx, json_body, limit as rate_limit
from ..services import cv as cv_svc, job_reports, jobs as jobs_svc, platform as platform_svc
from ..services.common import Ctx

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
router = APIRouter(tags=["ai"])


async def _upload(request: Request, ctx: Ctx, key: str, count: int) -> bytes:
    rate_limit(request, f"key:{key}:{ctx.user.id}", count, 3600)
    blob = await request.body()
    if not blob:
        raise HTTPException(400, "empty upload")
    return blob


# -------------------------------- CVs --------------------------------

@router.post("/cv/parse")
async def parse_cv(request: Request, filename: str = "", ctx: Ctx = Depends(get_ctx)):
    blob = await _upload(request, ctx, "cv-parse", 48)
    return await run_in_threadpool(cv_svc.parse_upload, ctx, request.app.state.ai, blob, filename)


@router.post("/candidates/{ref}/cv", status_code=201)
async def add_cv(ref: str, request: Request, filename: str = "", ctx: Ctx = Depends(get_ctx)):
    blob = await _upload(request, ctx, "cv-add", 60)
    return await run_in_threadpool(cv_svc.add_to_candidate, ctx, request.app.state.ai, ref, blob, filename)


@router.get("/candidates/{ref}/cv/info")
def cv_info(ref: str, ctx: Ctx = Depends(get_ctx)):
    return cv_svc.info(ctx, ref)


@router.get("/candidates/{ref}/cv")
def cv_download(ref: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    name, mime, blob = cv_svc.download(ctx, request.app.state.ai, ref)
    safe = name.replace('"', '').replace('\\', '')
    return Response(blob, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.get("/list_jobs")
def list_jobs(status: str = "", q: str = "", ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        raise HTTPException(403, "use the client requirements page")
    return jobs_svc.list_jobs(ctx, status, q)


# -------------------------------- jobs --------------------------------

@router.get("/jobs")
def list_jobs(status: str = "", q: str = "", company_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        if company_id is None:
            raise HTTPException(400, "select a client company")
        return platform_svc.list_jobs_for_platform(ctx, company_id)
    return jobs_svc.list_jobs(ctx, status, q)


@router.post("/jobs", status_code=201)
async def create_job(request: Request, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    rate_limit(request, f"job-create:{ctx.user.id}", 60, 3600)
    if ctx.user.platform_role:
        from ..services.platform import create_job_description
        company_id = data.pop("company_id", None)
        if company_id is None:
            raise HTTPException(400, "select a client company")
        return await run_in_threadpool(create_job_description, ctx, request.app.state.ai, company_id, data)
    return await run_in_threadpool(jobs_svc.create_job, ctx, request.app.state.ai, data)


@router.get("/jobs/{ref}")
def get_job(ref: str, ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        raise HTTPException(403, "open requirements through the client requirements page")
    return jobs_svc.get_job(ctx, ref)


@router.patch("/jobs/{ref}")
async def update_job(ref: str, request: Request, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        raise HTTPException(403, "platform staff can create requirements but cannot edit them")
    return await run_in_threadpool(jobs_svc.update_job, ctx, request.app.state.ai, ref, data)


@router.delete("/jobs/{ref}", status_code=204)
def delete_job(ref: str, ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        raise HTTPException(403, "platform staff cannot delete company requirements")
    jobs_svc.delete_job(ctx, ref)
    return Response(status_code=204)


@router.post("/jobs/{ref}/jd")
async def upload_jd(ref: str, request: Request, filename: str = "", ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        raise HTTPException(403, "platform staff can create requirements but cannot edit them")
    blob = await _upload(request, ctx, "jd-upload", 60)
    return await run_in_threadpool(jobs_svc.upload_jd, ctx, request.app.state.ai, ref, blob, filename)


@router.get("/jobs/{ref}/jd")
def download_jd(ref: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        raise HTTPException(403, "platform staff cannot open company requirements")
    name, mime, blob = jobs_svc.download_jd(ctx, request.app.state.ai, ref)
    safe = name.replace('"', '').replace('\\', '')
    return Response(blob, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.get("/jobs/{ref}/matches")
async def job_matches(ref: str, request: Request, min_score: int = 0, exclude_flagged: bool = False, limit: int = 50,
                      ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        raise HTTPException(403, "platform staff cannot search company candidates")
    rate_limit(request, f"match:{ctx.user.id}", 120, 3600)
    params = {"min_score": min_score, "exclude_flagged": exclude_flagged, "limit": limit}
    return await run_in_threadpool(jobs_svc.matches, ctx, request.app.state.ai, ref, params)


@router.post("/match")
async def search_cvs(request: Request, data=Depends(json_body), ctx: Ctx = Depends(get_ctx)):
    if ctx.user.platform_role:
        raise HTTPException(403, "platform staff cannot search company candidates")
    rate_limit(request, f"match:{ctx.user.id}", 120, 3600)
    return await run_in_threadpool(jobs_svc.search, ctx, request.app.state.ai, data)


# -------------------------------- reports --------------------------------

@router.get("/reports/jobs")
def jobs_report(date_from: str = "", date_to: str = "", client: str = "", ctx: Ctx = Depends(get_ctx)):
    if ctx.org.is_platform:
        raise HTTPException(403, "Rise staff cannot access company job reports")
    return job_reports.job_report(ctx, date_from, date_to, client)


@router.get("/reports/jobs.xlsx")
async def jobs_report_xlsx(request: Request, date_from: str = "", date_to: str = "", client: str = "", ctx: Ctx = Depends(get_ctx)):
    if ctx.org.is_platform:
        raise HTTPException(403, "Rise staff cannot access company job reports")
    rate_limit(request, f"export:{ctx.user.id}", 10, 3600)
    blob = job_reports.export_report(ctx, date_from, date_to, client)
    return Response(blob, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="Job_Requests.xlsx"'})
