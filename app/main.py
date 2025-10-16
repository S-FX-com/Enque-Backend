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
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limiter import limiter

from app.api.api import api_router
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

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
# Construct a regex for allowed origins to handle wildcards
origins = settings.BACKEND_CORS_ORIGINS
regex_parts = []
for origin in origins:
    # Escape dots and replace wildcard * with a regex pattern for subdomains
    part = origin.replace('.', r'\.').replace('*', r'[a-zA-Z0-9-]+')
    regex_parts.append(part)
origin_regex = r"|".join(regex_parts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # Must be empty when using allow_origin_regex
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middlewares
app.add_middleware(HealthMiddleware)

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

async def warm_up_cache():
    """Pre-loads frequently accessed data into the cache."""
    logger.info("🔥 Starting cache warming process...")
    try:
        from app.services.cache_service import cache_service
        from app.database.session import SessionLocal
        from app.models.agent import Agent

        await cache_service.connect()
        if not cache_service.is_redis_connected:
            logger.warning("Cache warming skipped: Redis is not connected.")
            return

        db = SessionLocal()
        try:
            active_agents = db.query(Agent).filter(Agent.is_active == True).all()
            count = 0
            for agent in active_agents:
                cache_key = f"user_agent:{agent.id}"
                user_data_for_cache = {
                    "id": agent.id,
                    "name": agent.name,
                    "email": agent.email,
                    "role": agent.role,
                    "workspace_id": agent.workspace_id,
                    "is_active": agent.is_active,
                    "avatar_url": agent.avatar_url
                }
                await cache_service.set(cache_key, user_data_for_cache, ttl=3600)  # Cache for 1 hour
                count += 1
            logger.info(f"✅ Cache warming complete. {count} active agents cached.")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"❌ Failed to warm up cache: {e}", exc_info=True)


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    # Start cache warming in the background
    import asyncio
    asyncio.create_task(warm_up_cache())

    # Initialize email sync scheduler
    try:
        from app.services.email_sync_task import start_scheduler
        start_scheduler()
    except ImportError:
        logger.warning("⚠️ Email sync scheduler not available (missing dependencies).")
    except Exception as e:
        logger.error(f"❌ Failed to start email sync scheduler: {e}")

@app.get("/")
def read_root():
    """Root endpoint"""
    return {"message": "Enque API is running"}
