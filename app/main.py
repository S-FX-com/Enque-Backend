"""
FastAPI Application with caching optimization
"""
import logging
import time
import socketio
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.api import api_router
from app.core.middleware import CacheMiddleware
from app.core.config import settings
from app.core.socketio import sio

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class HealthMiddleware(BaseHTTPMiddleware):
    """Simple health check middleware"""
    
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return Response("OK", status_code=200)
        return await call_next(request)

# Create FastAPI app
app = FastAPI(
    title="Enque API",
    description="Customer service platform API",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.API_V1_STR else "/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middlewares
app.add_middleware(HealthMiddleware)
app.add_middleware(CacheMiddleware)

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Socket.IO integration
socket_app = socketio.ASGIApp(sio, app)

# 🔧 SIMPLIFIED: Basic health check endpoint 
@app.get("/health-detailed")
async def health_check_detailed():
    """Detailed health check including database pool status"""
    try:
        from app.database.session import get_pool_status, is_pool_healthy
        
        health_status = {
            "status": "healthy",
            "timestamp": time.time(),
            "services": {
                "api": "running",
                "socketio": "connected" if sio else "unavailable"
            }
        }
        
        # Check database pool health (safely)
        try:
            pool_status = get_pool_status()
            health_status["database"] = {
                "pool_healthy": is_pool_healthy(),
                "pool_status": pool_status
            }
            
            # Determine overall health
            if not is_pool_healthy():
                health_status["status"] = "degraded"
                health_status["warnings"] = ["Database connection pool usage is high"]
        except Exception as db_error:
            health_status["database"] = {
                "pool_healthy": False,
                "error": str(db_error)
            }
            health_status["status"] = "degraded"
            health_status["warnings"] = ["Database pool monitoring failed"]
            
        return health_status
    except Exception as e:
        return {
            "status": "error",
            "timestamp": time.time(),
            "error": str(e)
        }

@app.on_event("startup")
def startup_event():
    """Initialize email sync scheduler on startup"""
    try:
        from app.services.email_sync_task import start_scheduler
        start_scheduler()
    except ImportError:
        logger.warning("⚠️ Email sync scheduler not available (missing dependencies)")
    except Exception as e:
        logger.error(f"❌ Failed to start email sync scheduler: {e}")

@app.get("/")
def read_root():
    """Root endpoint"""
    return {"message": "Enque API is running"}
