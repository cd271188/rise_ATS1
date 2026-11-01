"""Background housekeeping: python -m app.worker
Builds the search index for candidates that have none (so the first search after a big import is not slow) and removes
CV uploads that were never saved. Run one copy; on PostgreSQL a second copy waits on an advisory lock."""
import logging
import signal
import threading

from sqlalchemy import select, text

from .config import Settings
from .db import make_engine, make_sessionmaker
from . import rls
from .models import Candidate, CandidateProfile, Organization, User
from .services import cv, profiles, runtime
from .services.common import Ctx

log = logging.getLogger("ats.worker")
LOCK_ID = 727_001
PER_ORG = 256


def index_pending(db, rt) -> int:
    """Embed up to PER_ORG unindexed candidates for each company that has some. Returns how many were done."""
    org_ids = db.scalars(select(Organization.id).where(Organization.parent_org_id.is_(None),
                                                        Organization.is_platform.is_(False)).order_by(Organization.id)).all()
    done = 0
    for org_id in org_ids:
        rls.only(db, org_id)
        user = db.scalar(select(User).where(User.org_id == org_id).limit(1))
        if not user:
            continue
        rows = list(db.scalars(select(Candidate).outerjoin(CandidateProfile, CandidateProfile.candidate_id == Candidate.id)
                  .where(Candidate.org_id == org_id, Candidate.deleted_at.is_(None),
                         CandidateProfile.candidate_id.is_(None)).order_by(Candidate.id).limit(PER_ORG)))
        if not rows:
            continue
        _, pending = profiles.ensure(Ctx(db=db, user=user), rt, rows, cap=PER_ORG)
        done += len(rows) - pending
        if pending == len(rows):  # nothing could be embedded (model missing?); stop hammering it
            log.warning("org %s: %s candidates could not be indexed", org_id, pending)
    return done


def run_once(sessionmaker, rt) -> dict:
    with sessionmaker() as db:
        drafts = cv.purge_all_drafts(db, rt)
    with sessionmaker() as db:
        indexed = index_pending(db, rt)
    return {"drafts_removed": drafts, "indexed": indexed}


def _hold_lock(engine) -> bool:
    """PostgreSQL: keep a session-level advisory lock for the life of the process so only one worker runs."""
    if engine.dialect.name != "postgresql":
        return True
    conn = engine.connect()
    if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID}).scalar():
        return True
    conn.close()
    return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    engine = make_engine(settings.database_url)
    rt = runtime.build(settings)
    sm = make_sessionmaker(engine)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    lock = False
    while not stop.is_set():
        try:
            lock = lock or _hold_lock(engine)
            if lock:
                res = run_once(sm, rt)
                if res["drafts_removed"] or res["indexed"]:
                    log.info("worker pass: %s", res)
        except Exception:
            log.exception("worker pass failed")
        if lock not in (True, False):
            lock.close()
        stop.wait(settings.index_interval_seconds)
    if lock not in (True, False):
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())