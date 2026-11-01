#!/bin/sh

# For a database that already exists (deploy/postgres-init only runs on a brand-new volume): create the restricted
# ats_app login and give it its privileges. Run as the owner/superuser, once, after 'alembic upgrade head'.
# ATS_APP_DB_PASSWORD=... PGHOST=postgres PGUSER=ats PGDATABASE=ats PGPASSWORD=... sh scripts/create_app_role.sh
# Then point ATS_DATABASE_URL of the app and worker at ats_app (docker-compose.prod.yml does this) and set ATS_RLS_ENABLED=true.

set -eu

: "${ATS_APP_DB_PASSWORD:?set ATS_APP_DB_PASSWORD}"
db="${PGDATABASE:-ats}"

psql -v ON_ERROR_STOP=1 -v dbname="$db" -v app_pw="$ATS_APP_DB_PASSWORD" <<'SQL'
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ats_app') AS make \gset
\if :make
  CREATE ROLE ats_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
\endif

ALTER ROLE ats_app PASSWORD :'app_pw';
GRANT CONNECT ON DATABASE :"dbname" TO ats_app;
GRANT USAGE ON SCHEMA public TO ats_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ats_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ats_app;
GRANT EXECUTE ON FUNCTION app_org_ids() TO ats_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ats_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ats_app;
REVOKE ALL ON audit_log FROM ats_app;
GRANT SELECT, INSERT ON audit_log TO ats_app;
GRANT UPDATE (diff) ON audit_log TO ats_app;
SQL

echo "ats_app is ready."