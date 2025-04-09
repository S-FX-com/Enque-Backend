from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles
import os

# Importar todos los modelos para asegurar que se registren
from app.models import Agent, Team, TeamMember, Company, User, UnassignedUser, Task, Comment, Activity
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig

from app.core.config import settings
from app.api.api import api_router
from app.database.session import get_db

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

# Configure CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Ruta principal
@app.get("/", tags=["system"])
async def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}. Visit /docs for API documentation."}

# Health check endpoint en el nuevo formato
@app.get("/v1/health", tags=["system"])
async def health_check_v1():
    try:
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

# Health check endpoint para compatibilidad con versiones anteriores
@app.get("/api/health", tags=["system"])
async def health_check_legacy():
    try:
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

@app.on_event("startup")
def startup_events():
    """
    Run events when the application starts
    """
    try:
        if has_scheduler:
            # Start background email sync scheduler
            start_scheduler()
    except Exception as e:
        print(f"Error starting email sync scheduler: {e}")

if __name__ == "__main__":
    import uvicorn
    # Usar el puerto proporcionado por Railway (PORT) o el 8000 por defecto
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port) 