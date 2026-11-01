"""Operator commands. python -m app.cli create-creator --email you@rise.com --name "Your Name"
The password is read from ATS_CREATOR_PASSWORD, or prompted for (never passed on the command line)."""
import argparse
import os
import getpass
import sys

from .config import Settings
from .db import create_tables, make_engine, make_sessionmaker
from .services import breakglass, platform
from .services.common import ValidationError


def reindex(settings, engine) -> int:
    from sqlalchemy import select
    from .import rls
    from .models import Candidate, Organization, User
    from .services import profiles, runtime
    from .services.candidates import scope
    from .services.common import Ctx
    rt = runtime.build(settings)
    with make_sessionmaker(engine)() as db:
        total = 0
        for org in db.scalars(select(Organization).where(Organization.parent_org_id.is_(None))):
            user = db.scalar(select(User).where(User.org_id == org.id).limit(1))
            if not user:
                continue
            rls.only(db, org.id)
            ctx = Ctx(db=db, user=user)
            rows = list(db.scalars(select(Candidate).where(*scope(ctx))))
            _, pending = profiles.ensure(ctx, rt, rows, cap=len(rows) or 1)
            if pending:
                print(f"{org.name} : {pending} candidates have no text to index or could not be embedded", file=sys.stderr)
            total += len(rows) - pending
        print(f"Indexed {total} candidates")
        return 0

def test_llm(settings) -> int:
    from .services import runtime
    from .services.llm import LlmError
    rt = runtime.build(settings)
    if not rt.ai_enabled:
        print("error: no AI model is configured (set ATS_LLM_BASE_URL or ATS_OPENAI_API_KEY)", file=sys.stderr)
        return 1
    print(f"model {settings.llm_model} at {settings.llm_base_url or 'api.openai.com'}")
    try:
        data, (tin, tout) = rt.llm.parse_cv("Priya Nair, Data Engineer at Acme, Pune. 6 years of Python and SQL. "
                                            "Notice period 30 days. priya.nair@example.com")
        print(f"ok ({tin} tokens in, {tout} out) : {data['full_name']}, {data['primary_skill_role']}, "
              f"{data['total_experience_years']} yrs, skills {data['skills']}")
        return 0
    except LlmError as e:
        print("error: " + str(e) + " (details are in the log)", file=sys.stderr)
        return 1

def staff_access(args, engine) -> int:
    import getpass as gp
    try:
        if args.cmd == "grant-staff-access":
            out = breakglass.grant(engine, args.reason, args.hours, args.ticket, args.operator or gp.getuser())
            print(f"role:       {out['role']}")
            print(f"password:   {out['password']}  (shown once)")
            print(f"expires:    {out['expires_at']:%Y-%m-%d %H:%M UTC}")
            print("Read-only, every statement is logged, and it is removed automatically at expiry.")
        elif args.cmd == "revoke-staff-access":
            if not breakglass.revoke(engine, args.role, args.operator or gp.getuser()):
                print("error: no active grant for that role", file=sys.stderr)
                return 1
            print("revoked")
        elif args.cmd == "reap-staff-access":
            for role in breakglass.reap(engine):
                print("removed " + role)
        else:
            for g in breakglass.listing(engine):
                print(f"{g['role']:<26} until {g['expires_at']:%Y-%m-%d %H:%M} {g['operator']} {g['ticket'] or '-'} {g['reason']}")
        return 0
    except breakglass.BreakglassError as e:
        print("error: " + str(e), file=sys.stderr)
        return 1

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-creator", help="create the Rise Consulting creator account")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--company", default="Rise Consulting")
    sub.add_parser("test-llm", help="send a sample CV to the configured AI model and show what it understood")
    sub.add_parser("reindex", help="build the AI search index for every candidate that is not indexed yet")
    g = sub.add_parser("grant-staff-access", help="create a time-limited, read-only database login for an operator (owner credential)")
    g.add_argument("--reason", required=True, help="why client data must be looked at (written to the audit log)")
    g.add_argument("--hours", type=float, default=1, help="validity in hours, at most {breakglass.MAX_HOURS}")
    g.add_argument("--ticket", default="", help="support ticket or approval reference")
    g.add_argument("--operator", default="", help="who is asking (default: the OS user)")
    r = sub.add_parser("revoke-staff-access", help="end a break-glass login now")
    r.add_argument("role")
    r.add_argument("--operator", default="")
    sub.add_parser("list-staff-access", help="show break-glass logins and their state")
    sub.add_parser("reap-staff-access", help="remove expired break-glass logins (run every minute by the reaper service)")
    args = p.parse_args(argv)

    settings = Settings()
    if args.cmd == "test-llm":
        return test_llm(settings)
    owner_commands = {"grant-staff-access", "revoke-staff-access", "list-staff-access", "reap-staff-access"}
    engine = make_engine(settings.migration_database_url or settings.database_url) if args.cmd in owner_commands else settings.database_url
    if args.cmd in owner_commands:
        return staff_access(args, engine)
    if settings.auto_create_tables:
        create_tables(engine)
    if args.cmd == "reindex":
        return reindex(settings, engine)
    
    password = os.environ.get("ATS_CREATOR_PASSWORD") or getpass.getpass("Password (min 10 characters): ")
    with make_sessionmaker(engine)() as db:
        try:
            user = platform.bootstrap_creator(db, args.email, args.name, password, args.company)
            print(f"creator account created: {user.email}")
            return 0
        except ValidationError as e:
            print("error: " + "; ".join(f"{k} {v}" for k, v in e.errors.items()), file=sys.stderr)
            return 1

if __name__ == "__main__":
    sys.exit(main())
