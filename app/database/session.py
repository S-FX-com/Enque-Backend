from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Crear engine de SQLAlchemy solo si hay una conexión de base de datos configurada
if settings.DATABASE_URI:
    engine = create_engine(
        settings.DATABASE_URI,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=5,
        max_overflow=10
    )
    
    # Crear sessionmaker
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    logger.warning("No se ha configurado DATABASE_URI. La funcionalidad de base de datos no estará disponible.")
    engine = None
    SessionLocal = None


# Dependency para obtener sesión de DB
def get_db():
    if SessionLocal is None:
        raise ValueError("No hay conexión a la base de datos configurada")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 