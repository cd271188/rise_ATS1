"""Liveness and readiness probes (no authentication)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..deps import get_db

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request, db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "database unavailable"}, status_code=503)
    ping = getattr(request.app.state.limiter, "ping", None)
    if ping and not ping():
        return JSONResponse({"status": "redis unavailable"}, status_code=503)
    return {"status": "ready"}