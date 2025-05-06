# backend/app/main.py
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles # Import StaticFiles
from pathlib import Path # Import Path
import os
import re

# Importar todos los modelos para asegurar que se registren
from app.models import Agent, Team, TeamMember, Company, User, UnassignedUser, Task, Comment, Activity
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig

from app.core.config import settings
from app.api.api import api_router
from app.database.session import get_db, engine

# Import email sync scheduler with try/except
try:
    from app.services.email_sync_task import start_scheduler
    has_scheduler = True
except ImportError:
    has_scheduler = False
    print("WARNING: Email sync scheduler not loaded due to missing dependencies")

from app.utils.logger import logger

# Create the application with a simple configuration
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0"
)

# Define static files directory relative to main.py
# Assuming main.py is in backend/app/
STATIC_DIR = Path(__file__).parent.parent / "static"
# Create static directory if it doesn't exist (especially for uploads)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "uploads" / "images").mkdir(parents=True, exist_ok=True) # Ensure uploads path exists

# Mount static files directory
# This will serve files from backend/static/ at the /static URL path
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Permitir todos los orígenes con el dominio enque.cc
def allow_origin_regex(origin: str):
    allowed_patterns = [
        r"^https://app\.enque\.cc$",
        r"^https://[a-zA-Z0-9-]+\.enque\.cc$",
        r"^http://localhost:\d+$"  # Para desarrollo local
    ]

    for pattern in allowed_patterns:
        if re.match(pattern, origin):
            return True
    return False

# Configure CORS with custom callback for dynamic subdomain validation
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Esto será filtrado por allow_origin_regex
    allow_origin_regex=None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=600,
)

@app.middleware("http")
async def cors_middleware(request, call_next):
    origin = request.headers.get("origin", "")
    response = await call_next(request)

    # Si el origen cumple con nuestros patrones, permitirlo
    if allow_origin_regex(origin):
        response.headers["Access-Control-Allow-Origin"] = origin

    return response

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Ruta principal
@app.get("/", tags=["system"])
async def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}. Visit /docs for API documentation."}

# Health check endpoint en el nuevo formato
@app.get("/v1/health", tags=["system"])
async def health_check_v1():
    return {"status": "ok", "database": "available" if engine else "not configured"}

# Health check endpoint para compatibilidad con versiones anteriores
@app.get("/api/health", tags=["system"])
async def health_check_legacy():
    return {"status": "ok", "database": "available" if engine else "not configured"}

def init_microsoft_integration():
    """
    Inicializar automáticamente la integración de Microsoft usando variables de entorno
    """
    try:
        # Obtener sesión de BD
        db = next(get_db())

        # Verificar si ya existe una integración de Microsoft
        integration = db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()

        # Si ya existe una integración activa, no hacer nada
        if integration:
            logger.info("Microsoft integration already exists, skipping initialization")
            return

        # Verificar si las variables de entorno necesarias están configuradas
        if not (settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET and settings.MICROSOFT_TENANT_ID):
            logger.warning("Microsoft integration environment variables missing, skipping initialization")
            return

        # Crear nueva integración con valores de las variables de entorno
        new_integration = MicrosoftIntegration(
            tenant_id=settings.MICROSOFT_TENANT_ID,
            client_id=settings.MICROSOFT_CLIENT_ID,
            client_secret=settings.MICROSOFT_CLIENT_SECRET,
            redirect_uri=settings.MICROSOFT_REDIRECT_URI,
            scope=settings.MICROSOFT_SCOPE,
            is_active=True
        )

        db.add(new_integration)
        db.commit()

        logger.info("Microsoft integration initialized successfully from environment variables")
    except Exception as e:
        logger.error(f"Error initializing Microsoft integration: {e}")

@app.on_event("startup")
def startup_events():
    """
    Run events when the application starts
    """
    try:
        # Inicializar integración de Microsoft
        if engine:
            init_microsoft_integration()

        if has_scheduler and engine:  # Solo iniciar el scheduler si hay BD configurada
            # Start background email sync scheduler
            start_scheduler()
        elif not engine:
            logger.warning("No se inició el sincronizador de emails porque no hay base de datos configurada")
    except Exception as e:
        logger.error(f"Error during startup events: {e}")

if __name__ == "__main__":
    import uvicorn
    # Usar el puerto proporcionado por Railway (PORT) o el 8000 por defecto
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
