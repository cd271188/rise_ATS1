# Deploymate single-instance deployment

Build the repository-root `Dockerfile` from `main`; retain its entrypoint.
Run one replica with autoscaling disabled, on port 8000, with `/readyz`
as the readiness endpoint. Start with 256m CPU / 512Mi requested and
512m CPU / 1Gi limited, then size from runtime measurements.

Attach a regular 10 GiB volume at `/data` before the first deployment.
The entrypoint prepares directories and drops privileges to the `ats` user.
Keep the database, CV files, and embedding cache on that volume:

| Environment variable | Value |
| --- | --- |
| `ATS_DATABASE_URL` | `sqlite:////data/ats.db` |
| `ATS_AUTO_CREATE_TABLES` | `true` |
| `ATS_WORKERS` | `1` |
| `ATS_STORAGE_BACKEND` | `disk` |
| `ATS_STORAGE_DIR` | `/data/cv_files` |
| `ATS_EMBEDDING_CACHE_DIR` | `/data/models_cache` |
| `ATS_COOKIE_SECURE` | `true` |
| `ATS_SIGNUP_MODE` | `platform` |

Set `ATS_SECRET_KEY` to a newly generated secret in the service environment;
never commit it. Set `ATS_ALLOWED_HOSTS` to a JSON list containing the service's
public hostname, `localhost`, and `127.0.0.1`. HTTPS is provided by Deploymate.
AI extraction remains disabled until an authorized provider key is configured.

This uses the application's default development environment and its documented
SQLite configuration. It is a persistent single-writer deployment, not the
hardened multi-company production stack. Do not enable multiple replicas or set
`ATS_ENVIRONMENT=production` without completing the PostgreSQL/RLS migration
and other checks described in the root README. A new volume starts empty;
the repository's bundled database and signing key are excluded from the image.
Platform creator provisioning uses `python -m app.cli create-creator` in the
running service with operator-provided identity/password; no default account
or public sign-up is enabled.

Verify service/build status and startup logs, then check `/healthz`, `/readyz`,
`/`, `/app.css`, `/js/main.js`, and `/api/v1/auth/config` over HTTPS.
Verify volume access using the application identity when service execution is
available. Back up SQLite consistently with its backup API and preserve CV
files together; take a backup before upgrades. Keep the volume on rollback,
and check schema compatibility before restoring an older image. New empty
installations use automatic table creation; do not mix this with Alembic on
the same database. Existing application data requires an explicit migration.
