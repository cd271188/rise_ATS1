"""Load a v1 (single-user) ats.db into an existing organisation of this platform.

Usage (from the ats_platform folder):
    python scripts/import_v1_db.py --v1-db ../ats_app/ats.db --owner-email you@company.com

The organisation is the one the given user belongs to, and it must have no candidates yet.
v1 candidate numbers are kept (CND-0007 stays CND-0007). Dropdown lists from v1 are merged in.
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import make_engine, make_sessionmaker  # noqa: E402
from app.fields import DEFAULT_STATUS, FIELD_KEYS, SEED_LISTS  # noqa: E402
from app.models import Candidate, Interview, OrgCounter, User  # noqa: E402
from app.services import lists  # noqa: E402
from app.services.candidates import key_values  # noqa: E402


def _ts(text):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text), fmt)
        except (TypeError, ValueError):
            continue
    return datetime.utcnow()


def _blank(v):
    return None if v is None or (isinstance(v, str) and not v.strip()) else v


def import_v1(db, v1_path, owner_email):
    user = db.scalar(select(User).where(User.email == owner_email.strip().lower()))
    if not user:
        raise SystemExit(f"No user with email {owner_email}. Sign up (or run first-run setup) in the app first.")
    org_id = user.org_id
    if db.scalar(select(func.count()).select_from(Candidate).where(Candidate.org_id == org_id)):
        raise SystemExit("That organisation already has candidates; import only works into an empty one.")

    src = sqlite3.connect(str(v1_path))
    src.row_factory = sqlite3.Row
    try:
        cands = src.execute("SELECT * FROM candidates ORDER BY id").fetchall()
        ivs = src.execute("SELECT * FROM interviews ORDER BY id").fetchall()
        v1_lists = src.execute("SELECT list_name, value FROM lists ORDER BY sort_order, id").fetchall()
    except sqlite3.DatabaseError as ex:
        raise SystemExit(f"{v1_path} is not a v1 ATS database: {ex}")
    finally:
        src.close()

    for r in v1_lists:
        if r["list_name"] in SEED_LISTS and r["list_name"] != "status":
            lists.add_value(db, org_id, r["list_name"], r["value"])

    pk_map = {}
    for r in cands:
        vals = {k: _blank(r[k]) for k in FIELD_KEYS}
        vals["full_name"] = vals["full_name"] or "(unnamed)"
        c = Candidate(org_id=org_id, seq=r["id"], current_status=r["current_status"] or DEFAULT_STATUS,
                      created_by=user.id, created_at=_ts(r["last_updated"]), last_updated=_ts(r["last_updated"]),
                      **vals, **key_values(vals["full_name"], vals.get("email"), vals.get("phone")))
        db.add(c)
        db.flush()
        pk_map[r["id"]] = c.id

    for r in ivs:
        if r["candidate_pk"] not in pk_map:
            continue
        db.add(Interview(org_id=org_id, candidate_id=pk_map[r["candidate_pk"]], created_by=user.id,
                         created_at=_ts(r["created_at"]),
                         **{k: _blank(r[k]) for k in ("interview_stage", "interview_date", "interview_time",
                                                      "interviewer_panel", "feedback", "status", "next_action",
                                                      "next_followup_date")}))
    counter = db.get(OrgCounter, org_id)
    counter.next_candidate = max([r["id"] for r in cands], default=0) + 1
    db.commit()
    return len(cands), len(ivs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v1-db", required=True, help="path to the v1 ats.db")
    ap.add_argument("--owner-email", required=True, help="email of an existing user in the target organisation")
    args = ap.parse_args()
    if not Path(args.v1_db).is_file():
        raise SystemExit(f"File not found: {args.v1_db}")
    engine = make_engine(Settings().database_url)
    with make_sessionmaker(engine)() as db:
        n, m = import_v1(db, args.v1_db, args.owner_email)
        print(f"Imported {n} candidates and {m} interview entries.")


if __name__ == "__main__":
    main()