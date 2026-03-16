import os
import urllib.parse
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, create_engine
from sqlalchemy.engine import URL

from alembic import context
from dotenv import load_dotenv

# load .env
load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not found in .env")

    # Handle the complex password by constructing the URL safely
    if "@" in db_url and "://" in db_url:
        try:
            # Protocol
            prefix, rest = db_url.split("://", 1)
            # Split by the LAST '@' to separate user:pass from host:port/db
            credentials, host_info = rest.rsplit("@", 1)
            # Split credentials by the FIRST ':' to get user and pass
            username, password = credentials.split(":", 1)
            # URL-decode password (handles special chars like @, #, !, etc.)
            password = urllib.parse.unquote(password)
            
            # Split host_info to get host, port, db and query
            # host_info example: server.com:5432/dbname?sslmode=disable
            if "/" in host_info:
                host_port, db_part = host_info.split("/", 1)
            else:
                host_port, db_part = host_info, ""
                
            if ":" in host_port:
                host, port = host_port.split(":", 1)
            else:
                host, port = host_port, 5432
                
            if "?" in db_part:
                database, query_str = db_part.split("?", 1)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(query_str).items()}
            else:
                database, query = db_part, {}

            url_obj = URL.create(
                drivername="postgresql",
                username=username,
                password=password,
                host=host,
                port=int(port),
                database=database,
                query=query
            )
            return create_engine(url_obj, poolclass=pool.NullPool)
        except Exception as e:
            # Fallback if manual parsing fails
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql://", 1)
            return create_engine(db_url, poolclass=pool.NullPool)
    
    # Simple fallback
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, poolclass=pool.NullPool)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    db_url = os.getenv("DATABASE_URL")
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
