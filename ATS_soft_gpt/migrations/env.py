"""Alembic environment. The database URL comes from ATS_DATABASE_URL (same setting the app uses)."""
from logging.config import fileConfig

from alembic import context

from app.config import Settings
from app.db import make_engine
from app.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata
_settings = Settings()
URL = _settings.migration_database_url or _settings.database_url


def run_migrations_offline():
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = make_engine(URL)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=URL.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

