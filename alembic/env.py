from logging.config import fileConfig
import logging
import os
import time

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import create_engine

from alembic import context

# Import all models to ensure they're registered with SQLAlchemy metadata
from app.models import Agent, Team, TeamMember, Company, User, UnassignedUser, Task, Comment, Activity, CannedReply
from app.database.session import engine
from app.core.config import settings

# Configure logger
logger = logging.getLogger("alembic")

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from app.models.agent import Base as AgentBase
from app.models.team import Base as TeamBase
from app.models.task import Base as TaskBase
from app.models.company import Base as CompanyBase
from app.models.user import Base as UserBase
from app.models.comment import Base as CommentBase
from app.models.activity import Base as ActivityBase
from app.models.canned_reply import Base as CannedReplyBase

# target_metadata = None
target_metadata = [
    AgentBase.metadata,
    TeamBase.metadata,
    TaskBase.metadata,
    CompanyBase.metadata,
    UserBase.metadata,
    CommentBase.metadata,
    ActivityBase.metadata,
    CannedReplyBase.metadata 
]


def get_working_engine():
    """Tries different configurations to get a working database engine"""
    # Try with DATABASE_URI URL first (main logic)
    try:
        logger.info("Trying connection with DATABASE_URI...")
        connectable = engine
        with connectable.connect() as connection:
            logger.info("Successful connection with DATABASE_URI")
            return connectable
    except Exception as e:
        logger.error(f"Error connecting with DATABASE_URI: {str(e)}")
    
    # Try with Railway's MYSQL_URL directly
    try:
        mysql_url = os.getenv("MYSQL_URL")
        if mysql_url:
            logger.info("Trying connection with MYSQL_URL...")
            direct_engine = create_engine(mysql_url)
            with direct_engine.connect() as connection:
                logger.info("Successful connection with MYSQL_URL")
                return direct_engine
    except Exception as e:
        logger.error(f"Error connecting with MYSQL_URL: {str(e)}")
    
    # Try with external host
    try:
        host = os.getenv("MYSQLHOST", "hopper.proxy.rlwy.net")
        port = os.getenv("MYSQLPORT", "40531")
        user = os.getenv("MYSQLUSER", "root")
        password = os.getenv("MYSQLPASSWORD", "")
        database = os.getenv("MYSQL_DATABASE", "railway")
        
        ext_url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
        logger.info(f"Trying connection with external host: {host}")
        ext_engine = create_engine(ext_url)
        with ext_engine.connect() as connection:
            logger.info(f"Successful connection with external host: {host}")
            return ext_engine
    except Exception as e:
        logger.error(f"Error connecting with external host: {str(e)}")
    
    # Wait a moment and try again with the first option
    logger.info("Waiting 5 seconds before trying again...")
    time.sleep(5)
    return engine


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = settings.DATABASE_URI
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = get_working_engine()

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