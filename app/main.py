# backend/app/main.py
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
import re

from app.models import Agent, Team, TeamMember, Company, User, UnassignedUser, Task, Comment, Activity
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig

from app.core.config import settings
from app.api.api import api_router
from app.database.session import get_db, engine

try:
    from app.services.email_sync_task import start_scheduler
    has_scheduler = True
except ImportError:
    has_scheduler = False
    print("WARNING: Email sync scheduler not loaded due to missing dependencies")

from app.utils.logger import logger

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0"
)

STATIC_DIR = Path(__file__).parent.parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "uploads" / "images").mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Configurar directorio de uploads como contenido estático
uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

def allow_origin_regex(origin: str):
    allowed_patterns = [
        r"^https://app\.enque\.cc$",
        r"^https://users\.enque\.cc$",
        r"^https://[a-zA-Z0-9-]+\.enque\.cc$",
        r"^http://localhost:\d+$"
    ]

    for pattern in allowed_patterns:
        if re.match(pattern, origin):
            return True
    return False

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Esto permite todos los orígenes, pero lo filtraremos con el middleware personalizado
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

    # Asegurarse de agregar el origen a la respuesta si es permitido
    if origin and (origin == "https://users.enque.cc" or allow_origin_regex(origin)):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/", tags=["system"])
async def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}. Visit /docs for API documentation."}

@app.get("/v1/health", tags=["system"])
async def health_check_v1():
    return {"status": "ok", "database": "available" if engine else "not configured"}

@app.get("/api/health", tags=["system"])
async def health_check_legacy():
    return {"status": "ok", "database": "available" if engine else "not configured"}

def init_microsoft_integration():
    """
    Inicializar automáticamente la integración de Microsoft usando variables de entorno
    """
    try:
        db = next(get_db())
        integration = db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()

        if integration:
            logger.info("Microsoft integration already exists, skipping initialization")
            return

        if not (settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET and settings.MICROSOFT_TENANT_ID):
            logger.warning("Microsoft integration environment variables missing, skipping initialization")
            return

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
        if engine:
            init_microsoft_integration()

        if has_scheduler and engine:
            start_scheduler()
        elif not engine:
            logger.warning("No se inició el sincronizador de emails porque no hay base de datos configurada")
    except Exception as e:
        logger.error(f"Error during startup events: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
