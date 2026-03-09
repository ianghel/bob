"""Alembic environment configuration."""

import os
import sys
from logging.config import fileConfig
from urllib.parse import quote_plus

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from core.database.models import Base

config = context.config

# Override sqlalchemy.url from env vars
db_host = os.getenv("DB_HOST", "127.0.0.1")
db_port = os.getenv("DB_PORT", "3306")
db_name = os.getenv("DB_DATABASE", "bob")
db_user = os.getenv("DB_USERNAME", "root")
db_pass = os.getenv("DB_PASSWORD", "")
_url = f"mysql+pymysql://{db_user}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}"
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
