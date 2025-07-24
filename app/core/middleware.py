"""
Middleware personalizado para gestión de caché
"""
import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.cache import user_cache


class CacheMiddleware(BaseHTTPMiddleware):
    """
    Middleware que gestiona la limpieza periódica del caché
    """
    
    def __init__(self, app, cleanup_interval: int = 100):
        super().__init__(app)
        self.cleanup_interval = cleanup_interval
        self.request_count = 0
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Limpiar caché expirado cada N requests
        self.request_count += 1
        if self.request_count % self.cleanup_interval == 0:
            user_cache.clear_expired()
        
        # Procesar request
        response = await call_next(request)
        
        # Calcular tiempo de respuesta
        process_time = time.time() - start_time
        
        # Agregar header con tiempo de procesamiento
        response.headers["X-Process-Time"] = str(round(process_time * 1000, 2))
        
        return response


class AuthMetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware específico para métricas de autenticación
    """
    
    def __init__(self, app):
        super().__init__(app)
        self.auth_requests = 0
        self.auth_cache_hits = 0
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Identificar si es un request que requiere autenticación
        requires_auth = self._requires_authentication(request)
        
        if requires_auth:
            self.auth_requests += 1
            
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        if requires_auth:
            # Log detallado para requests de autenticación
            logger.debug(f"AUTH REQUEST: {request.method} {request.url.path} - {process_time*1000:.2f}ms")
            
            # Agregar métricas al header de respuesta
            cache_stats = user_cache.get_stats()
            response.headers["X-Auth-Cache-Users"] = str(cache_stats["active_cached_users"])
            response.headers["X-Auth-Request-Count"] = str(self.auth_requests)
            
        return response
    
    def _requires_authentication(self, request: Request) -> bool:
        """
        Determina si el request requiere autenticación
        """
        # Rutas que no requieren autenticación
        public_paths = [
            "/v1/auth/login",
            "/v1/auth/verify-token",
            "/v1/health",
            "/docs",
            "/openapi.json",
            "/v1/microsoft/auth/callback"
        ]
        
        path = request.url.path
        return not any(path.startswith(public_path) for public_path in public_paths) 