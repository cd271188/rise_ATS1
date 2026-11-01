#!/bin/sh

# Restore a dump made by backup_postgres.sh into an EMPTY database. Usage: restore.sh FILE.dump
# Uses the standard PG* environment variables. Stop the app and worker first. Then run 'alembic upgrade head'.
# Practise this on a spare database before you need it.

set -eu

[ $# -eq 1 ] || { echo "usage: $0 FILE.dump" >&2; exit 2; }
pg_restore --no-owner --exit-on-error --dbname="${PGDATABASE:?set PGDATABASE}" "$1"
echo "restored $1"