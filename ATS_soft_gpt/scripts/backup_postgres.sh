#!/bin/sh

# Dump the database to DIR/ats-YYYYMMDD-HHMMSS.dump (custom format) and delete dumps older than BACKUP_KEEP_DAYS.
# Uses the standard PG* environment variables (PGHOST, PGUSER, PGDATABASE, PGPASSWORD).
# CV files are not in the dump: with MinIO back up the minio_data volume, with AWS S3 turn on bucket versioning.

set -eu

dir="${1:-./backups}"
keep="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$dir"

file="$dir/ats-$(date +%Y%m%d-%H%M%S).dump"
pg_dump --format=custom --file="$file.partial"
mv "$file.partial" "$file"
find "$dir" -name 'ats-*.dump' -mtime +"$keep" -delete
echo "backup written: $file"