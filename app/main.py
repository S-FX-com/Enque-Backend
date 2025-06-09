# backend/app/main.py
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import os
import re
import socketio

from app.models import Agent, Team, TeamMember, Company, User, UnassignedUser, Task, Comment, Activity, CannedReply
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig
from app.models.global_signature import GlobalSignature
from app.models.notification import NotificationTemplate, NotificationSetting
from app.models.workflow import Workflow

from app.core.config import settings
from app.api.api import api_router
from app.database.session import get_db, engine
from app.core.socketio import sio

try:
    from app.services.email_sync_task import start_scheduler
    has_scheduler = True
except ImportError:
    has_scheduler = False
    print("WARNING: Email sync scheduler not loaded due to missing dependencies")

from app.utils.logger import logger

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    redirect_slashes=False
)

# Static files and uploads are now handled by S3
# Removed static file mounting as files are stored in S3

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

# Crear app Socket.IO con configuración correcta
socket_app = socketio.ASGIApp(sio, app)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html>
        <head>
            <title>Enque API</title>
        </head>
        <body>
            <h1>🎯 Enque API Server</h1>
            <p>✅ API is running successfully!</p>
            <p>📡 Real-time updates enabled with Socket.IO</p>
            <p>🔗 <a href="/docs">View API Documentation</a></p>
        </body>
    </html>
    """

@app.get("/v1/health", tags=["system"])
async def health_check_v1():
    return {"status": "ok", "database": "available" if engine else "not configured"}

@app.get("/api/health", tags=["system"])
async def health_check_legacy():
    return {"status": "ok", "database": "available" if engine else "not configured"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Enque API",
        "socketio": "enabled"
    }

def init_microsoft_integration():
    """
    Inicializar automáticamente la integración de Microsoft usando variables de entorno
    """
    try:
        db = next(get_db())
        integration = db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()

        if integration:
            # Microsoft integration exists
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
    ⚡ Run events when the application starts with performance optimizations
    """
    try:
        if engine:
            init_microsoft_integration()

        # ⚡ Initialize performance services (sync version)
        try:
            from app.services.cache_service import cache_service
            # Cache will initialize when first used
            # Cache service ready
        except Exception as e:
            logger.warning(f"Cache service setup failed: {e}")

        if has_scheduler and engine:
            start_scheduler()
        elif not engine:
            logger.warning("No se inició el sincronizador de emails porque no hay base de datos configurada")
            
    
    except Exception as e:
        logger.error(f"Error during startup events: {e}")

# Configurar logging

logger.info("Socket.IO enabled")
logger.info("API docs at /docs")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "app.main:socket_app",  # Usar socket_app en lugar de app
        host="0.0.0.0",
        port=port,
        reload=True,
        access_log=False
    )
