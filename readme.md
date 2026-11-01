# ATS Platform

*A product of Rise Consulting.*

A multi-tenant applicant-tracking application: FastAPI + SQLAlchemy backend, a vanilla-JS single-page front end (no build step, no CDN), SQLite by default and PostgreSQL-ready. The same code runs as a hosted service for many companies or as a self-hosted install for one.

Evolved from the single-user v1 app in `../ats_app` (which is left untouched).

## Quick start (local)

```
pip install -r requirements.txt
python -m app                     # http://127.0.0.1:8000
```

There are **no default accounts and no public sign-up**. Create the platform creator once, from the command line (the password comes from a prompt, or from `ATS_CREATOR_PASSWORD` in non-interactive use):

```
python -m app.cli create-creator --email you@rise.example --name "Your Name"
```

Sign in as the creator, add Rise admins on **Rise team**, and create client companies on **Client companies**. In Docker: `docker compose exec app python -m app.cli create-creator --email ... --name ...`.

Tables are created automatically on start (`ATS_AUTO_CREATE_TABLES=true`). Interactive API docs: `/docs` (the Swagger page loads its assets from a CDN, so it needs internet access).

New users: start with the illustrated walkthrough in [docs/ONBOARDING_GUIDE.pdf](docs/ONBOARDING_GUIDE.pdf) (also as [HTML](docs/ONBOARDING_GUIDE.html); screenshots are in `docs/screenshots/`).

Tests: `pip install pytest httpx` then `python -m pytest` (80 tests).

## Features

- Candidate Master as an editable grid: server paging, sort, per-column filters, column resize, edit in place (double-click, F2, Enter, or just type), arrow/Tab navigation, range selection, Ctrl+C copy as tab-separated text.
- Each cell edit saves on its own; if someone else changed the row you are told and the row refreshes.
- Add Candidate form with a live duplicate warning (name, email, or the last 10 digits of the phone). Duplicates warn, they never block.
- Interview tracker: the latest interview entry sets the candidate's current status.
- Dashboard, recruiter report, follow-ups due, Excel import and export (row cap 5,000, formula-safe export).
- Per-company dropdown lists, team management (invite, role, disable, reset password), audit log.
- Roles inside a company: owner, admin, recruiter, viewer. Viewers read only; recruiters create and edit; delete, lists, team, company settings and audit are admin/owner only; date of birth is visible to admin/owner only.
- Platform tier (Rise Consulting): a **creator** (everything below) and **Rise admins** whose abilities the creator ticks per person: create companies, rename/suspend/reactivate companies, manage client users (add, change role, disable, reset password). Every Rise admin can list companies. Only the creator manages Rise admins.
Rise staff live in a separate "Rise Consulting" organisation with read-only rights, so they can **never** open a client's candidates, interviews, lists, team or audit log. A client's audit log records Rise actions as "Rise Consulting" without naming the person. Suspending a company signs everyone out and blocks sign-in; data is kept.

## Configuration

All settings are environment variables with the `ATS_` prefix, or a `.env` file. See `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `ATS_DATABASE_URL` | `sqlite:///./ats_platform.db` | Any SQLAlchemy URL |
| `ATS_SECRET_KEY` | generated into `ats_secret.key` | Signing key; set explicitly in production |
| `ATS_ALLOWED_HOSTS` | `["localhost","127.0.0.1"]` | Host names the app will answer to (JSON list) |
| `ATS_SIGNUP_MODE` | `platform` | `platform` (no sign-up; Rise creates every company), `open` (anyone may create a company), `closed` (first-run setup, then invitations only) |
| `ATS_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `ATS_TRUST_PROXY` | `false` | Honour `X-Forwarded-For` (only behind your own proxy) |
| `ATS_AUTO_CREATE_TABLES` | `true` | Create tables on start; turn off and use Alembic for real deployments |
| `ATS_HOST`, `ATS_PORT` | `127.0.0.1`, `8000` | Used by `python -m app` |

## Deploying

**Hosted by Rise Consulting (default):** `ATS_SIGNUP_MODE=platform`, create the creator with the CLI, then Rise creates each client company. For a hosted service where customers sign themselves up use `open` instead. Either way: a real `ATS_SECRET_KEY`, `ATS_ALLOWED_HOSTS` set to your domain, `ATS_COOKIE_SECURE=true`, TLS terminated by a reverse proxy in front (set `ATS_TRUST_PROXY=true` only if that proxy sets `X-Forwarded-For`), and PostgreSQL.

**Self-hosted (one company):** `ATS_SIGNUP_MODE=closed`. The first person to open the app creates the company; after that sign-up is refused and the owner invites everyone else from the Team page.

**Docker local:** `cp .env.example .env`, edit it, then `docker compose up -d --build` (the default single-company SQLite setup remains suitable for development).

**Production PostgreSQL + pgvector:** copy `.env.prod.example` to `.env.prod`, replace all secrets, and point `ATS_DOMAIN` at the host. Then run `docker compose -f docker-compose.prod.yaml --env-file .env.prod up -d --build`. The one-shot `migrate` service applies Alembic migrations as `ats_owner`; the app and worker use the restricted `ats_app` role with row-level security. PostgreSQL data, Redis, MinIO files, and Caddy certificates use persistent volumes. Back up PostgreSQL and the MinIO volume together, and test restores before relying on them. The default stack needs ports 80/443 reachable for Caddy's HTTPS certificate.

To move the existing local SQLite database, first back it up and bring up the production stack once so it creates the empty PostgreSQL schema. Then copy the data using the owner URL (keep credentials out of shell history where possible):

```
python scripts/migrate_sqlite_to_postgres.py \
  --source sqlite:///./ats_platform.db \
  --target 'postgresql+psycopg://ats_owner:...@localhost:5432/ats'
```

The destination must be empty. The script preserves IDs and legacy embedding bytes; PostgreSQL lazily converts legacy vectors into the native `vector(384)` column as profiles are indexed. After import, run `docker compose -f docker-compose.prod.yaml --env-file .env.prod exec app python -m app.cli reindex` to rebuild candidate profiles. Keep a restorable backup until you confirm users, candidates, jobs, and CV downloads in the new deployment.

**Migrations:** `alembic upgrade head` (the URL comes from `ATS_DATABASE_URL`). `0001_baseline` creates the original tables; `0002_platform_roles` adds company suspension and the platform roles.
If you upgrade an install that relied on open sign-up, set `ATS_SIGNUP_MODE=open` (or `closed`) explicitly - the default is now `platform`.
When you change `app/models.py`: `alembic revision --autogenerate -m "describe change"`.
Do not mix `ATS_AUTO_CREATE_TABLES=true` with Alembic on the same database.

## Moving v1 data in

1. Start the platform and create the company and its owner (in `platform` mode: as creator, on Client companies).
2. `python scripts/import_v1_db.py --v1-db ../ats_app/ats.db --owner-email you@company.com`

Candidate numbers are preserved (CND-0007 stays CND-0007), interview history and dropdown values come across, and the next new candidate continues after the highest v1 number. The target company must have no candidates yet. (Alternatively use Excel export from v1 and Import on the Candidates page.)

## Reminders

`python -m app.jobs.reminders` prints, per company, the candidates whose follow-up date is today or overdue. Run it from cron or Task Scheduler; there is no email or WhatsApp delivery yet.

## Security model in brief

- Passwords: argon2id. Access token: 15-minute JWT kept in page memory only. Refresh token: random, stored hashed, HttpOnly SameSite=Lax cookie, rotated on every use; reuse of an old token revokes the whole session family.
- Every business row carries `org_id`; the organisation always comes from the signed-in user, never from the request. Reaching another company's record returns 404.
- Writes require the `X-Requested-With` header and a JSON content type (CSRF defence). Host allow-list, body-size caps, a Content-Security-Policy with no inline script or style, `no-store` on API responses, generic 500 errors.
- Rate limits (in memory, per process): login 5/min per IP and per email, 120/min per user, import 5/hour per company, export 10/hour per user, with `429` and `Retry-After`.
- Optimistic locking: edits carry the row `version`; a stale edit gets `409` with the current row.
- Excel export neutralises cells that start with `=` + `- @`.

## Tested, and not tested

**Tested here:** the full API and service layer on SQLite (80 pytest cases, including cross-company isolation, the role matrix, the Rise permission checklist, company suspension, token rotation and reuse detection, rate limits, stale-edit conflicts, Excel round-trip, v1 import), the Alembic migrations (`upgrade`, `check`, `downgrade` on SQLite), and the front end in headless Edge (Rise console, company creation, first sign-in with a temporary password, suspension, dashboard,
grid editing/sort/filter/keyboard/selection, forms, interviews, reports, settings, team, audit, export, sign-out).

**Not tested - treat as unverified until you run them:**
- PostgreSQL/pgvector migration, RLS behavior, and the SQLite-to-PostgreSQL transfer (these need a running Postgres instance).
- Full production Docker deployment and HTTPS certificate issuance (requires Docker and a public domain pointed at the server).
- Multiple server processes: the rate limiter is per process; use a shared store (e.g. Redis) before scaling out.
- The system clipboard on Ctrl+C (the copy handler is implemented; the OS clipboard was not read back).
- Excel import through the browser UI (the import service is covered by tests).

## Known limitations

- No e-mail delivery and no self-service "forgot password": invited users and password resets get a temporary password shown once to the admin (Rise staff can reset any client user's password; only the creator can reset Rise staff).
- No company-delete endpoint: companies are suspended, not removed.
- Creators exist only via the server-side CLI; the web console cannot create or change a creator.
- Pasting into the grid is not implemented (copy is).
- No hard-delete/purge endpoint: deleted candidates are soft-deleted and kept for audit.
- No SSO/MFA, billing or plans, CV upload/parsing, or LLM agent; those are outside this build.
- PostgreSQL deployments enforce row-level security for every tenant table; app startup refuses to run if policies are missing or the database login can bypass them.
- Candidate and job embedding vectors use pgvector cosine search on PostgreSQL; SQLite keeps its existing byte-vector storage for local development.
- A refresh from two browser tabs at the same instant could be treated as token reuse and sign you out.

## Layout

```
app/          main.py, cli.py, config, models, security, rate limiter, services/, routers/, jobs/
web/          index.html, app.css, js/ (api, router, ui, grid, pages/)
migrations/   Alembic (0001_baseline, 0002_platform_roles)
scripts/      import_v1_db.py
tests/        pytest
```
