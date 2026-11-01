"""Job-request report: how many job requests each client sent in a chosen period."""
import io
from collections import defaultdict
from datetime import date, timedelta

from openpyxl import Workbook
from sqlalchemy import String, cast, func, select

from ..models import Job
from . import audit, excel_io, jobs
from .common import Ctx, ValidationError

NO_CLIENT = "(No client)"
JSON_ROWS = 500
XLSX_ROWS = 20000
DEFAULT_DAYS = 90
MAX_DAYS = 366 * 5


def _received():
    return func.coalesce(Job.received_on, func.substr(cast(Job.created_at, String), 1, 10))


def _range(ctx: Ctx, date_from, date_to) -> tuple[str, str]:
    today = ctx.today()
    end = jobs._day(date_to, "date_to", today.isoformat())
    start = jobs._day(date_from, "date_from", (today - timedelta(days=DEFAULT_DAYS - 1)).isoformat())
    if start > end:
        raise ValidationError({"date_to": "must not be before the start date"})
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    if days > MAX_DAYS:
        raise ValidationError({"date_from": "the period can be at most 5 years"})
    return start, end


def _name(v) -> str:
    return " ".join(str(v or "").split()) or NO_CLIENT


def known_clients(ctx: Ctx) -> list[str]:
    seen = {}
    names = {_name(c) for (c,) in ctx.db.execute(select(Job.client).where(Job.org_id == ctx.data_org_id, Job.deleted_at.is_(None)).distinct())}
    for name in sorted(names):
        seen.setdefault(name.lower(), name)
    return sorted(seen.values(), key=str.lower)


def job_report(ctx: Ctx, date_from="", date_to="", client="", limit=JSON_ROWS) -> dict:
    jobs._need_client(ctx)
    start, end = _range(ctx, date_from, date_to)
    client = " ".join(str(client or "").split())[:200]
    rows = list(ctx.db.scalars(select(Job).where(
        Job.org_id == ctx.data_org_id, Job.deleted_at.is_(None), _received() >= start, _received() <= end
    ).order_by(_received().desc(), Job.seq.desc())))
    if client:
        want = client.lower()
        rows = [j for j in rows if _name(j.client).lower() == want]

    by_client = {}
    by_month = defaultdict(lambda: {"total": 0, "clients": set()})
    for j in rows:
        name = _name(j.client)
        c = by_client.setdefault(name.lower(), {"client": name, "total": 0, "open": 0, "closed": 0,
                                                 "first_received": None, "last_received": None})
        day = jobs.received_on(j)
        c["total"] += 1
        c["open" if j.status == "Open" else "closed"] += 1
        c["first_received"] = min(filter(None, [c["first_received"], day]), default=None)
        c["last_received"] = max(filter(None, [c["last_received"], day]), default=None)
        m = by_month(day or "")[:7]
        m["total"] += 1
        m["clients"].add(name.lower())
    total = len(rows)
    clients = sorted(by_client.values(), key=lambda c: (-c["total"], c["client"].lower()))
    for c in clients:
        c["share_pct"] = round(100 * c["total"] / total, 1) if total else 0
    months = [{"month": k, "total": v["total"], "clients": len(v["clients"])} for k, v in sorted(by_month.items())]
    listing = []
    for j in rows[:max(1, limit)]:
        r = {**jobs.EMPTY_REQ, **(j.requirements or {})}
        listing.append({"job_id": jobs.public_id(j.seq), "title": j.title, "client": _name(j.client),
                        "client_ref": j.client_ref or "", "received_on": jobs.received_on(j), "status": j.status,
                        "primary_skill": r["primary_skill"], "min_experience_years": r["min_experience_years"],
                        "max_experience_years": r["max_experience_years"], "locations": r["locations"],
                        "max_ctc_lakhs": r["max_ctc_lakhs"], "max_notice_days": r["max_notice_days"],
                        "has_jd_file": bool(j.jd_filename)})
    return {"date_from": start, "date_to": end, "client": client,
            "summary": {"total_jobs": total, "clients": len(clients), "open": sum(c["open"] for c in clients),
                        "closed": sum(c["closed"] for c in clients)},
            "by_client": clients, "by_month": months, "jobs": listing, "jobs_shown": len(listing),
            "clients": known_clients(ctx)}


def export_report(ctx: Ctx, date_from="", date_to="", client="") -> bytes:
    rep = job_report(ctx, date_from, date_to, client, limit=XLSX_ROWS)
    scope = f" [date_from] to {rep['date_to']}" + (f" [{rep['client']}]" if rep["client"] else "")
    wb = Workbook()
    by_client = [{"Client": None}, {"Job Requests": None}, {"Open": None}, {"Closed": None}, {"Share %": None},
                 {"First Received": None}, {"Last Received": None}]
    excel_io._sheet(wb, "By Client", f"Job Requests by Client {scope}", by_client,
                    [[c["client"], c["total"], c["open"], c["closed"], c["share_pct"], c["first_received"], c["last_received"]]
                     for c in rep["by_client"]], first=True)
    excel_io._sheet(wb, "By Month", f"Job Requests by Month {scope}", [{"Month": None}, {"Job Requests": None}, {"Clients": None}],
                    [[m["month"], m["total"], m["clients"]] for m in rep["by_month"]])
    cols = [{"Job ID": None}, {"Client": None}, {"Client Job ID": None}, {"Role": None}, {"Received": None}, {"Status": None},
            {"Primary Skill": None}, {"Min Exp (Yrs)": None}, {"Max Exp (Yrs)": None}, {"Locations": None},
            {"Budget (LPA)": None}, {"Max Notice (Days)": None}, {"JD File": None}]
    excel_io._sheet(wb, "Jobs", f"Job Requests {scope}", cols,
                    [[j["job_id"], j["client"], j["client_ref"], j["title"], j["received_on"], j["status"], j["primary_skill"],
                      j["min_experience_years"], j["max_experience_years"], ", ".join(j["locations"]), j["max_ctc_lakhs"],
                      j["max_notice_days"], "Yes" if j["has_jd_file"] else "No"] for j in rep["jobs"]])
    buf = io.BytesIO()
    wb.save(buf)
    audit.record(ctx, "export", "job_report", None, {"rows": rep["summary"]["total_jobs"], "from": rep["date_from"], "to": rep["date_to"]})
    ctx.db.commit()
    return buf.getvalue()
