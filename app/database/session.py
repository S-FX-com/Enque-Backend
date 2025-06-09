from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

if settings.DATABASE_URI:
    # ⚡ Optimized database engine with connection pooling
    engine = create_engine(
        settings.DATABASE_URI,
        pool_pre_ping=True,  # Validate connections before use
        pool_recycle=settings.DB_POOL_RECYCLE,  # Recycle connections every hour
        pool_size=settings.DB_POOL_SIZE,  # Base connection pool size
        max_overflow=settings.DB_MAX_OVERFLOW,  # Additional connections when needed
        pool_timeout=settings.DB_POOL_TIMEOUT,  # Timeout when getting connection
        echo=False,  # Set to True for SQL debugging
        # MySQL-specific optimizations
        connect_args={
            "charset": "utf8mb4",
            "autocommit": False,
            "connect_timeout": 10,
            "read_timeout": 30,
            "write_timeout": 30,
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