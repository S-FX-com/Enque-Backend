from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

import re

# Helper to get the async driver
def get_async_driver(uri: str) -> str:
    if uri.startswith("postgresql"):
        # Replaces postgresql:// or postgresql+psycopg2:// with postgresql+asyncpg://
        return re.sub(r"postgresql(\+psycopg2)?://", "postgresql+asyncpg://", uri)
    if uri.startswith("mysql"):
        # Replaces mysql:// or mysql+pymysql:// with mysql+aiomysql://
        return re.sub(r"mysql(\+pymysql)?://", "mysql+aiomysql://", uri)
    return uri

if settings.DATABASE_URI:
    async_db_uri = get_async_driver(settings.DATABASE_URI)
    
    engine = create_async_engine(
        async_db_uri,
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        echo=False,
    )
    
    AsyncSessionLocal = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
else:
    logger.warning("No se ha configurado DATABASE_URI. La funcionalidad de base de datos no estará disponible.")
    engine = None
    AsyncSessionLocal = None

async def get_db() -> AsyncSession:
    if AsyncSessionLocal is None:
        raise ValueError("No hay conexión a la base de datos configurada")
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
def get_pool_status():
    if engine is None:
        return {"error": "No database engine configured"}
    
    try:
        pool = engine.pool
        checked_out = pool.checkedout()
        checked_in = pool.checkedin()
        total_connections = checked_out + checked_in
        max_connections = settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW
        
        return {
            "pool_size": pool.size(),
            "checked_in": checked_in,
            "checked_out": checked_out,
            "overflow": pool.overflow(),            "total_connections": total_connections,
            "max_connections": max_connections,
            "pool_utilization": round((total_connections / max_connections) * 100, 2) if max_connections > 0 else 0
        }
    except Exception as e:
        return {"error": f"Could not get pool status: {e}"}

def log_pool_status():
    """Log current pool status (for debugging)"""
    status = get_pool_status()
    if "error" in status:
        logger.error(f"🚨 Pool status error: {status['error']}")
    else:
        logger.info(f"📊 DB Pool: {status['checked_out']} out, {status['checked_in']} in, {status['overflow']} overflow, {status['pool_utilization']}% used")

def is_pool_healthy():
    """Check if the connection pool is in a healthy state"""
    status = get_pool_status()
    if "error" in status:
        return False
    return status.get('pool_utilization', 100) < 80

from contextlib import asynccontextmanager

@asynccontextmanager
async def get_background_db_session():
    """
    Provides an AsyncSession for background tasks, creating a new engine
    to ensure it's bound to the correct event loop in a separate thread.
    """
    if not settings.DATABASE_URI:
        raise ValueError("No hay conexión a la base de datos configurada")

    # Create a new engine specifically for this background task context
    local_engine = create_async_engine(
        get_async_driver(settings.DATABASE_URI),
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_size=5,  # Smaller pool for background tasks
        max_overflow=10,
        echo=False,
    )

    LocalAsyncSessionMaker = sessionmaker(
        bind=local_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    async with LocalAsyncSessionMaker() as session:
        try:
            yield session
        finally:
            await session.close()
    
    # Dispose of the engine after the session is closed
    await local_engine.dispose()
