"""Dashboard KPIs, recruiter report and follow-ups, all scoped to the caller's organisation."""
from datetime import date, timedelta

from sqlalchemy import func, select

from ..fields import STATUSES
from ..models import Candidate, Interview, Job
from .candidates import scope
from .common import Ctx
from .jobs import to_dict as job_to_dict
from .lists import get_lists


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _rows(ctx: Ctx):
    return ctx.db.execute(select(
        Candidate.recruiter, Candidate.current_status, Candidate.profile_submitted_to_client,
        Candidate.date_added, Candidate.client_submission_date, Candidate.vendor_org_id).where(
        *scope(ctx))).all()


def _requirements_by_company(ctx: Ctx) -> list[dict]:
    rows = ctx.db.execute(select(Job.client, Job.status, func.count(Job.id)).where(
        Job.org_id == ctx.data_org_id, Job.deleted_at.is_(None)).group_by(Job.client, Job.status)).all()
    grouped: dict[str, dict] = {}
    for client, status, count in rows:
        name = (client or "").strip() or "Unspecified company"
        item = grouped.setdefault(name, {"company": name, "total": 0, "open": 0, "closed": 0})
        item["total"] += count
        if status == "Open":
            item["open"] += count
        elif status == "Closed":
            item["closed"] += count
    return sorted(grouped.values(), key=lambda item: item["company"].casefold())


def _recent_requirements(ctx: Ctx) -> list[dict]:
    rows = ctx.db.scalars(select(Job).where(
        Job.org_id == ctx.data_org_id, Job.deleted_at.is_(None)
    ).order_by(Job.last_updated.desc(), Job.seq.desc()).limit(25))
    items = [job_to_dict(job) for job in rows]
    for item in items:
        item.pop("jd_text", None)
    return items


def _names(ctx: Ctx, rows) -> list[str]:
    names = list(get_lists(ctx.db, ctx.org_id)["recruiters"])
    for r in rows:
        if r.recruiter and r.recruiter not in names:
            names.append(r.recruiter)
    return names


def _report(names, rows) -> list[dict]:
    out = []
    for n in names:
        mine = [r for r in rows if r.recruiter == n]
        out.append({"recruiter": n, "candidates_added": len(mine),
                    "vendor_submissions": sum(r.vendor_org_id is not None for r in mine),
                    "client_submissions": sum(r.profile_submitted_to_client == "Yes" for r in mine),
                    "offers": sum(r.current_status == "Offer" for r in mine),
                    "yet_to_join": sum(r.current_status == "Yet to Join" for r in mine),
                    "drops": sum(r.current_status == "Drop" for r in mine)})
    return out


def recruiter_report(ctx: Ctx) -> list[dict]:
    rows = _rows(ctx)
    return _report(_names(ctx, rows), rows)


def dashboard(ctx: Ctx, on: date | None = None) -> dict:
    on = on or ctx.today()
    nxt = (on.replace(day=28) + timedelta(days=4)).replace(day=1)
    periods = {"today": (on, on), "week": (week_start(on), week_start(on) + timedelta(days=6)),
               "month": (on.replace(day=1), nxt - timedelta(days=1))}
    rows = _rows(ctx)
    names = _names(ctx, rows)

    def inside(value, p):
        return bool(value) and periods[p][0].isoformat() <= value <= periods[p][1].isoformat()

    def table(field, only_yes):
        out = []
        for n in names:
            mine = [r for r in rows if r.recruiter == n and (not only_yes or r.profile_submitted_to_client == "Yes")]
            out.append({"recruiter": n, **{p: sum(inside(getattr(r, field), p) for r in mine) for p in periods}})
        out.append({"recruiter": "Total", **{p: sum(x[p] for x in out) for p in periods}})
        return out

    statuses = {s: 0 for s in STATUSES}
    for r in rows:
        statuses[r.current_status] = statuses.get(r.current_status, 0) + 1
    return {
        "as_of": on.isoformat(),
        "periods": {p: [a.isoformat() for a in v] for p, v in periods.items()},
        "kpis": {
            "total_candidates": len(rows),
            "submitted_to_client": sum(r.profile_submitted_to_client == "Yes" for r in rows),
            "in_interview": sum(r.current_status in ("L1 Interview", "L2 Interview", "L3 Interview") for r in rows),
            "offers": statuses.get("Offer", 0),
            "yet_to_join": statuses.get("Yet to Join", 0),
            "drops": statuses.get("Drop", 0),
        },
        "recruiter_submissions": table("date_added", False),
        "client_submissions": table("client_submission_date", True),
        "pipeline": [{"status": s, "count": c} for s, c in statuses.items()],
        "requirements_by_company": _requirements_by_company(ctx),
        "recent_requirements": _recent_requirements(ctx),
        "recruiter_activity": _report(names, rows),
        "followups_due": len(followups_due(ctx, on)),
    }


def followups_due(ctx: Ctx, on: date | None = None) -> list[dict]:
    """Interview entries whose follow-up date is today or earlier, for candidates still in play (not dropped or already accepted)."""
    on = on or ctx.today()
    stmt = select(Interview, Candidate).join(Candidate, Candidate.id == Interview.candidate_id).where(
        Interview.org_id == ctx.data_org_id, *scope(ctx),
        Interview.next_followup_date.is_not(None), Interview.next_followup_date <= on.isoformat(),
        Candidate.current_status.not_in(("Drop", "Yet to Join"))).order_by(Interview.next_followup_date, Interview.id)
    latest = {}
    for i, c in ctx.db.execute(stmt):
        latest[c.id] = (i, c)
    out = []
    for i, c in latest.values():
        newest = ctx.db.scalar(select(Interview.id).where(Interview.candidate_id == c.id).order_by(
            Interview.id.desc()).limit(1))
        if newest != i.id:
            continue  # a newer entry supersedes this follow-up
        out.append({"candidate_id": "CND-%04d" % c.seq, "full_name": c.full_name, "client": c.client,
                    "recruiter": c.recruiter, "status": c.current_status, "next_action": i.next_action,
                    "next_followup_date": i.next_followup_date,
                    "overdue_days": (on - date.fromisoformat(i.next_followup_date)).days})
    return sorted(out, key=lambda x: x["next_followup_date"])
