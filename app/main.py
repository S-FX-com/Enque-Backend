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
        logging.FileHandler("app.log"),
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

@app.get("/")
def read_root():
    """Root endpoint"""
    return {"message": "Enque API is running"}

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "OK", "timestamp": time.time()}
