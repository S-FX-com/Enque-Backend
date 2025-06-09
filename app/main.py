# backend/app/main.py

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import os
import re
import socketio

from app.api.api import api_router
from app.core.config import settings
from app.core.socketio import sio
from app.database.session import get_db, engine
from app.utils.logger import logger

# Modelos (solo para garantizar carga en otras partes)
from app.models import (
    Agent, Team, TeamMember, Company, User, UnassignedUser,
    Task, Comment, Activity, CannedReply,
    MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig,
    GlobalSignature, NotificationTemplate, NotificationSetting,
    Workflow
)

# Scheduler opcional
try:
    from app.services.email_sync_task import start_scheduler
    has_scheduler = True
except ImportError:
    has_scheduler = False
    logger.warning("Email sync scheduler not loaded due to missing dependencies")

# App principal
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    redirect_slashes=False
)

# Socket.IO
socket_app = socketio.ASGIApp(sio, app)

# CORS Middleware
def _allow_origin_regex(origin: str):
    return any(re.match(pattern, origin) for pattern in [
        r"^https://app\.enque\.cc$",
        r"^https://users\.enque\.cc$",
        r"^https://[a-zA-Z0-9-]+\.enque\.cc$",
        r"^http://localhost:\d+$"
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitido pero filtrado con middleware personalizado
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=600,
)

@app.middleware("http")
async def cors_filter_middleware(request: Request, call_next):
    origin = request.headers.get("origin", "")
    response = await call_next(request)

    if origin and (origin == "https://users.enque.cc" or _allow_origin_regex(origin)):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response

# Rutas
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html>
        <head><title>Enque API</title></head>
        <body>
            <h1>🎯 Enque API Server</h1>
            <p>✅ API is running successfully!</p>
            <p>📡 Real-time updates enabled with Socket.IO</p>
            <p>🔗 <a href="/docs">View API Documentation</a></p>
        </body>
    </html>
    """

@app.get("/v1/health", tags=["system"])
@app.get("/api/health", tags=["system"])
async def health_check_v1():
    return {"status": "ok", "database": "available" if engine else "not configured"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Enque API",
        "socketio": "enabled"
    }

# Integración de Microsoft
def init_microsoft_integration():
    try:
        db_gen = get_db()
        db = next(db_gen)

        integration = db.query(MicrosoftIntegration).filter_by(is_active=True).first()
        if integration or not all([
            settings.MICROSOFT_CLIENT_ID,
            settings.MICROSOFT_CLIENT_SECRET,
            settings.MICROSOFT_TENANT_ID
        ]):
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
        logger.info("Microsoft integration initialized from environment variables")
    except Exception as e:
        logger.error(f"Error initializing Microsoft integration: {e}")
    finally:
        if 'db_gen' in locals():
            db_gen.close()

# Eventos de arranque
@app.on_event("startup")
def on_startup():
    try:
        if engine:
            init_microsoft_integration()
            try:
                from app.services.cache_service import cache_service
            except Exception as e:
                logger.warning(f"Cache service setup failed: {e}")

            if has_scheduler:
                start_scheduler()
        else:
            logger.warning("No DB configured: skipping integrations and scheduler")
    except Exception as e:
        logger.error(f"Startup error: {e}")

# Logging inicial
logger.info("✅ Socket.IO enabled")
logger.info("📚 API docs at /docs")

# Uvicorn standalone
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:socket_app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True,
        access_log=False
    )
