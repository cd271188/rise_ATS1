"""Copy an existing SQLite ATS database to a migrated PostgreSQL/pgvector database.

Usage: python scripts/migrate_sqlite_to_postgres.py --source sqlite:///ats_platform.db \
       --target postgresql+psycopg://ats_owner:...@host:5432/ats

The destination must be an empty database already upgraded with `alembic upgrade head`.
"""
import argparse
import sys

from sqlalchemy import create_engine, inspect, select, text

from app.models import Base


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="SQLAlchemy URL for the source SQLite database")
    parser.add_argument("--target", required=True, help="SQLAlchemy URL for the migrated PostgreSQL database")
    args = parser.parse_args(argv)
    if not args.source.startswith("sqlite:") or not args.target.startswith("postgresql"):
        parser.error("source must be SQLite and target must be PostgreSQL")

    source = create_engine(args.source)
    target = create_engine(args.target, pool_pre_ping=True)
    try:
        if target.dialect.name != "postgresql":
            parser.error("target is not PostgreSQL")
        source_inspector = inspect(source)
        target_inspector = inspect(target)
        tables = [t for t in Base.metadata.sorted_tables
                  if source_inspector.has_table(t.name) and target_inspector.has_table(t.name)]
        with target.connect() as conn:
            missing = [t.name for t in Base.metadata.sorted_tables if t.name not in target_inspector.get_table_names()]
            if missing:
                raise RuntimeError("target schema is not migrated; missing: " + ", ".join(missing))
            occupied = [t.name for t in tables if conn.execute(text(f'SELECT 1 FROM "{t.name}" LIMIT 1')).first()]
            if occupied:
                raise RuntimeError("target must be empty; tables contain data: " + ", ".join(occupied[:8]))

        copied = 0
        with source.connect() as src, target.begin() as dst:
            for table in tables:
                source_cols = {c["name"] for c in source_inspector.get_columns(table.name)}
                target_cols = {c["name"] for c in target_inspector.get_columns(table.name)}
                names = [c.name for c in table.columns if c.name in source_cols and c.name in target_cols
                         and c.name != "embedding_vector"]
                if not names:
                    continue
                stmt = select(*(table.c[name] for name in names)).order_by(*table.primary_key.columns)
                result = src.execute(stmt)
                sql = text(f'INSERT INTO "{table.name}" ({", ".join(chr(34)+n+chr(34) for n in names)}) '
                           f'VALUES ({", ".join(":"+n for n in names)})')
                while batch := result.fetchmany(500):
                    dst.execute(sql, [dict(zip(names, row)) for row in batch])
                    copied += len(batch)

            # Explicit IDs do not advance PostgreSQL sequences; move each generated sequence to its table maximum.
            for table in tables:
                for col in table.primary_key.columns:
                    if col.autoincrement is False or not isinstance(col.type, __import__("sqlalchemy").Integer):
                        continue
                    seq = dst.execute(text("SELECT pg_get_serial_sequence(:table, :col)"),
                                      {"table": f'public."{table.name}"', "col": col.name}).scalar()
                    if seq:
                        dst.execute(text(f'SELECT setval(:seq, COALESCE(max_id, 1), max_id IS NOT NULL) '
                                         f'FROM (SELECT MAX("{col.name}") AS max_id FROM "{table.name}") AS seq_state'),
                                   {"seq": seq})
        print(f"Copied {copied} rows across {len(tables)} tables. Candidate and job vectors were transferred; "
              "run the app indexer to rebuild any vectors whose model/profile text has changed.")
        return 0
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    sys.exit(main())
