import logging
import time
import socketio
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limiter import limiter

from app.api.api import api_router
from app.core.config import settings
from app.core.socketio import sio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

async def warm_up_cache():
    """Pre-loads frequently accessed data into the cache."""
    logger.info("🔥 Starting cache warming process...")
    try:
        from app.services.cache_service import cache_service
        from app.database.session import AsyncSessionLocal
        from app.models.agent import Agent
        from sqlalchemy.future import select

        if not cache_service.is_redis_connected:
            logger.warning("Cache warming skipped: Redis is not connected.")
            return

        async with AsyncSessionLocal() as db:
            stmt = select(Agent).where(Agent.is_active == True)
            result = await db.execute(stmt)
            active_agents = result.scalars().all()
            
            count = 0
            for agent in active_agents:
                cache_key = f"user_agent:{agent.id}"
                user_data_for_cache = {
                    "id": agent.id, "name": agent.name, "email": agent.email,
                    "role": agent.role, "workspace_id": agent.workspace_id,
                    "is_active": agent.is_active, "avatar_url": agent.avatar_url
                }
                await cache_service.set(cache_key, user_data_for_cache, ttl=3600)
                count += 1
            logger.info(f"✅ Cache warming complete. {count} active agents cached.")
    except Exception as e:
        logger.error(f"❌ Failed to warm up cache: {e}", exc_info=True)

from app.services.cache_service import init_redis_pool, close_redis_pool

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("Application startup...")
    
    # Initialize Redis pool
    await init_redis_pool()
    
    # Warm up cache before accepting traffic
    await warm_up_cache()

    # Initialize email sync scheduler in a thread-safe way
    try:
        from app.services.email_sync_task import start_scheduler
        # Get the current running event loop
        loop = asyncio.get_running_loop()
        # Pass the loop to the scheduler to ensure tasks run in the same context
        start_scheduler(loop)
    except ImportError:
        logger.warning("⚠️ Email sync scheduler not available (missing dependencies).")
    except Exception as e:
        logger.error(f"❌ Failed to start email sync scheduler: {e}")
    
    yield
    # Shutdown logic
    logger.info("Application shutdown...")
    await close_redis_pool()

app = FastAPI(
    title="Enque API",
    description="Customer service platform API",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.API_V1_STR else "/openapi.json",
    lifespan=lifespan
)

class HealthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return Response("OK", status_code=200)
        return await call_next(request)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

origins = settings.BACKEND_CORS_ORIGINS
regex_parts = [o.replace('.', r'\.').replace('*', r'[a-zA-Z0-9-]+') for o in origins]
origin_regex = r"|".join(regex_parts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(HealthMiddleware)
app.include_router(api_router, prefix=settings.API_V1_STR)
socket_app = socketio.ASGIApp(sio, app)

@app.get("/health-detailed")
async def health_check_detailed():
    """Detailed health check including database pool status"""
    from app.database.session import get_pool_status, is_pool_healthy
    health_status = {"status": "healthy", "timestamp": time.time()}
    try:
        pool_status = get_pool_status()
        health_status["database"] = {
            "pool_healthy": is_pool_healthy(),
            "pool_status": pool_status
        }
        if not is_pool_healthy():
            health_status["status"] = "degraded"
    except Exception as db_error:
        health_status["database"] = {"pool_healthy": False, "error": str(db_error)}
        health_status["status"] = "degraded"
    return health_status

@app.get("/")
def read_root():
    """Root endpoint"""
    return {"message": "Enque API is running"}
