# backend/app/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import os
import re
import socketio
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.api import api_router
from app.database.session import engine
from app.core.socketio import sio
from app.utils.logger import logger
from app.services import startup_services

# Configuración del ciclo de vida de la aplicación
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja eventos de inicio y cierre de la aplicación"""
    await startup_services.initialize()
    yield
    await startup_services.shutdown()

# Creación de la aplicación FastAPI
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="1.0.0",
        redirect_slashes=False,
        lifespan=lifespan
    )

    _configure_cors(app)
    _configure_routes(app)
    _configure_middleware(app)

    return app

# Configuración de CORS
def _configure_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Filtrado por el middleware personalizado
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )

# Configuración de rutas
def _configure_routes(app: FastAPI) -> None:
    app.include_router(api_router, prefix=settings.API_V1_STR)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root():
        return _get_root_html()

    @app.get("/health", include_in_schema=False)
    async def health_check():
        return {
            "status": "healthy",
            "service": "Enque API",
            "socketio": "enabled",
            "database": "available" if engine else "not configured"
        }

# Configuración de middleware
def _configure_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def cors_middleware(request: Request, call_next):
        origin = request.headers.get("origin", "")
        response = await call_next(request)

        if origin and _is_allowed_origin(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"

        return response

# Helpers
def _is_allowed_origin(origin: str) -> bool:
    """Check if origin matches allowed patterns"""
    allowed_patterns = [
        r"^https://app\.enque\.cc$",
        r"^https://users\.enque\.cc$",
        r"^https://[a-zA-Z0-9-]+\.enque\.cc$",
        r"^http://localhost:\d+$"
    ]
    return any(re.match(pattern, origin) for pattern in allowed_patterns)

def _get_root_html() -> str:
    """Generate HTML for root endpoint"""
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

# Creación de la aplicación
app = create_app()
# socket_app = socketio.ASGIApp(sio, app)
socket_app = app

# Inicialización del logger
logger.info("Socket.IO enabled")
logger.info("API docs available at /docs")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:socket_app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=settings.DEBUG,
        access_log=False
    )