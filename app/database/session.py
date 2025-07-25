from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

if settings.DATABASE_URI:
    # ⚡ Optimized database engine with connection pooling compatible with SQLAlchemy 2.0
    engine = create_engine(
        settings.DATABASE_URI,
        pool_pre_ping=True,  # Validate connections before use
        pool_recycle=settings.DB_POOL_RECYCLE,  # Recycle connections every hour
        pool_size=settings.DB_POOL_SIZE,  # Base connection pool size
        max_overflow=settings.DB_MAX_OVERFLOW,  # Additional connections when needed
        pool_timeout=settings.DB_POOL_TIMEOUT,  # Timeout when getting connection
        echo=False,  # Set to True for SQL debugging
        # 🔧 SIMPLIFIED: Basic MySQL connection parameters only
        connect_args={
            "charset": "utf8mb4",
            "autocommit": False,
            "connect_timeout": 30,  # Connection timeout
            "read_timeout": 60,     # Read timeout  
            "write_timeout": 60,    # Write timeout
        } if "mysql" in settings.DATABASE_URI else {}
    )
    SessionLocal = sessionmaker(
        autocommit=False, 
        autoflush=False, 
        bind=engine,
        expire_on_commit=False  # Keep objects accessible after commit
    )
else:
    logger.warning("No se ha configurado DATABASE_URI. La funcionalidad de base de datos no estará disponible.")
    engine = None
    SessionLocal = None

def get_db():
    if SessionLocal is None:
        raise ValueError("No hay conexión a la base de datos configurada")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 🔧 ADDED: Connection pool monitoring functions
def get_pool_status():
    """Get current connection pool status for monitoring"""
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
            "overflow": pool.overflow(),
            # "invalid": pool.invalid(),  # 🔧 REMOVED: This method doesn't exist in current SQLAlchemy version
            "total_connections": total_connections,
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
    
    # Consider unhealthy if we're using more than 80% of available connections
    return status.get('pool_utilization', 100) < 80 