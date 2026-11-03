#!/bin/sh

# Runs once, when the postgres data volume is first created (docker-entrypoint-initdb.d).
# Creates the restricted login the running app uses. It cannot change the schema, is not a superuser and does not
# bypass row-level security, so each request can only reach the companies it was granted.
# owner / superuser: migrations, backups, operator commands. Operators only.
# the app and worker. NOSUPERUSER NOBYPASSRLS.
# optional: sign-in for routine support. No access to any tenant table (granted separately, see README).

set -eu

: "${ATS_APP_DB_PASSWORD:?set ATS_APP_DB_PASSWORD}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v dbname="$POSTGRES_DB" -v app_pw="$ATS_APP_DB_PASSWORD" -v support_pw="${ATS_SUPPORT_DB_PASSWORD:-}" <<'SQL'
CREATE ROLE ats_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'app_pw';
GRANT CONNECT ON DATABASE :'dbname' TO ats_app;
SELECT (:'support_pw' <> '') AS want_support \gset
\if :want_support
  CREATE ROLE ats_support LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD :'support_pw';
  GRANT CONNECT ON DATABASE :'dbname' TO ats_support;
\endif
SQL