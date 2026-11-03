"""Daily follow-up digest per organisation. Run: python -m app.jobs.reminders

Prints one digest per company. Replace `deliver` to send e-mail or chat messages; no provider is bundled."""
from sqlalchemy import select

from .. import rls
from ..config import Settings
from ..db import make_engine, make_sessionmaker
from ..models import Organization, User
from ..services.common import Ctx
from ..services.dashboard import followups_due


def build_digests(db) -> list[tuple[Organization, list[dict]]]:
    out = []
    for org in db.scalars(select(Organization).order_by(Organization.id)):
        owner = db.scalar(select(User).where(User.org_id == org.id, User.is_active.is_(True)).order_by(User.id))
        if owner:
            rls.only(db, org.id)
            out.append((org, followups_due(Ctx(db=db, user=owner))))
    return out


def deliver(org: Organization, items: list[dict]):
    print(f"== {org.name}: {len(items)} follow-up(s) due")
    for i in items:
        late = f"{i['overdue_days']}d overdue" if i["overdue_days"] > 0 else "due today"
        print(f"  {i['candidate_id']} {i['full_name']} ({i['client'] or '-'}) | {i['status']} | "
              f"{i['next_action'] or 'no action noted'} | {late} | recruiter: {i['recruiter'] or '-'}")


def main():
    db = make_sessionmaker(make_engine(Settings().database_url))()
    try:
        for org, items in build_digests(db):
            deliver(org, items)
    finally:
        db.close()


if __name__ == "__main__":
    main()