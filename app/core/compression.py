import gzip
import io
import logging
from typing import Optional, Set

try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class SmartCompressionMiddleware(BaseHTTPMiddleware):

    # Content types que DEBEN comprimirse (texto y JSON)
    COMPRESSIBLE_TYPES: Set[str] = {
        "text/html",
        "text/plain",
        "text/css",
        "text/javascript",
        "text/xml",
        "application/json",
        "application/javascript",
        "application/xml",
        "application/xhtml+xml",
        "application/rss+xml",
        "application/atom+xml",
    }

    # Content types que NO deben comprimirse (ya están comprimidos)
    EXCLUDED_TYPES: Set[str] = {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        "video/mp4",
        "video/webm",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-gzip",
    }

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 500,  # Bytes mínimos para comprimir
        gzip_level: int = 6,       # Nivel de compresión gzip (1-9)
        brotli_quality: int = 4,   # Nivel de compresión brotli (0-11)
        brotli_mode: str = "text", # Modo brotli: text, font, generic
    ):
        """
        Args:
            app: ASGI application
            minimum_size: Tamaño mínimo en bytes para aplicar compresión
            gzip_level: Nivel de compresión gzip (1=rápido, 9=mejor ratio)
            brotli_quality: Calidad brotli (0=rápido, 11=mejor ratio)
            brotli_mode: Modo de compresión brotli
        """
        super().__init__(app)
        self.minimum_size = minimum_size
        self.gzip_level = gzip_level
        self.brotli_quality = brotli_quality

        # Convertir modo brotli a constante
        if BROTLI_AVAILABLE:
            mode_map = {
                "text": brotli.MODE_TEXT,
                "font": brotli.MODE_FONT,
                "generic": brotli.MODE_GENERIC,
            }
            self.brotli_mode = mode_map.get(brotli_mode, brotli.MODE_TEXT)
        else:
            self.brotli_mode = None
            logger.warning(
                "⚠️ Brotli not available. Install with: pip install brotli. "
                "Falling back to gzip only."
            )

        logger.info(f"✅ Compression middleware initialized:")
        logger.info(f"   • Brotli: {'enabled' if BROTLI_AVAILABLE else 'disabled'}")
        logger.info(f"   • Gzip level: {gzip_level}")
        logger.info(f"   • Minimum size: {minimum_size} bytes")

    async def dispatch(self, request: Request, call_next):
        """Procesa la request y comprime la response si es apropiado."""
        response = await call_next(request)

        # Solo comprimir si el cliente lo acepta
        accept_encoding = request.headers.get("accept-encoding", "").lower()

        # Determinar método de compresión
        should_brotli = BROTLI_AVAILABLE and "br" in accept_encoding
        should_gzip = "gzip" in accept_encoding

        if not (should_brotli or should_gzip):
            return response

        # Verificar si la response ya está comprimida
        if "content-encoding" in response.headers:
            return response

        # Verificar content-type
        content_type = response.headers.get("content-type", "").lower().split(";")[0].strip()

        # No comprimir si es un tipo excluido
        if any(excluded in content_type for excluded in self.EXCLUDED_TYPES):
            return response

        # Solo comprimir tipos compresibles
        if not any(compressible in content_type for compressible in self.COMPRESSIBLE_TYPES):
            # Si no coincide exactamente, verificar si es texto genérico
            if not content_type.startswith("text/") and not content_type.startswith("application/"):
                return response

        # Obtener el body de la response
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        # No comprimir si es muy pequeño
        original_size = len(response_body)
        if original_size < self.minimum_size:
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Comprimir
        compressed_body, encoding_used, compression_ratio = self._compress(
            response_body,
            use_brotli=should_brotli,
            use_gzip=should_gzip
        )

        # Si la compresión no redujo el tamaño, enviar sin comprimir
        if len(compressed_body) >= original_size:
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Crear headers de la response comprimida
        headers = MutableHeaders(response.headers)
        headers["content-encoding"] = encoding_used
        headers["content-length"] = str(len(compressed_body))

        # Agregar header informativo (útil para debugging)
        headers["x-compression-ratio"] = f"{compression_ratio:.2f}"
        headers["x-original-size"] = str(original_size)

        # Vary header para indicar que la response varía según Accept-Encoding
        vary = headers.get("vary", "")
        if vary:
            headers["vary"] = f"{vary}, Accept-Encoding"
        else:
            headers["vary"] = "Accept-Encoding"

        # Log de métricas (solo para responses grandes)
        if original_size > 10000:  # > 10 KB
            logger.debug(
                f"📊 Compressed {original_size:,} → {len(compressed_body):,} bytes "
                f"({compression_ratio:.1f}% reduction) using {encoding_used}"
            )

        return Response(
            content=compressed_body,
            status_code=response.status_code,
            headers=dict(headers),
            media_type=response.media_type,
        )

    def _compress(
        self,
        body: bytes,
        use_brotli: bool,
        use_gzip: bool
    ) -> tuple[bytes, str, float]:
        """
        Comprime el body con el mejor algoritmo disponible.

        Returns:
            tuple[bytes, str, float]: (compressed_body, encoding, compression_ratio_percent)
        """
        original_size = len(body)

        # Intentar Brotli primero (mejor compresión)
        if use_brotli and BROTLI_AVAILABLE:
            try:
                compressed = brotli.compress(
                    body,
                    quality=self.brotli_quality,
                    mode=self.brotli_mode
                )
                ratio = ((original_size - len(compressed)) / original_size) * 100
                return compressed, "br", ratio
            except Exception as e:
                logger.warning(f"Brotli compression failed: {e}, falling back to gzip")

        # Fallback a Gzip
        if use_gzip:
            try:
                buffer = io.BytesIO()
                with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=self.gzip_level) as gz:
                    gz.write(body)
                compressed = buffer.getvalue()
                ratio = ((original_size - len(compressed)) / original_size) * 100
                return compressed, "gzip", ratio
            except Exception as e:
                logger.error(f"Gzip compression failed: {e}")

        # Si todo falla, retornar sin comprimir
        return body, "identity", 0.0


# ============================================================================
# Funciones Helper para Configuración
# ============================================================================

def create_compression_middleware(
    minimum_size: int = 500,
    gzip_level: int = 6,
    brotli_quality: int = 4,
) -> type[SmartCompressionMiddleware]:
    """
    Factory function para crear middleware con configuración custom.

    Args:
        minimum_size: Bytes mínimos para comprimir (default: 500)
        gzip_level: Nivel gzip 1-9 (default: 6 - balance)
        brotli_quality: Nivel brotli 0-11 (default: 4 - balance)

    Recomendaciones:
        - Desarrollo: gzip_level=1, brotli_quality=1 (rápido)
        - Producción: gzip_level=6, brotli_quality=4 (balance)
        - Máxima compresión: gzip_level=9, brotli_quality=11 (CPU alto)

    Example:
        ```python
        from app.core.compression import create_compression_middleware

        app.add_middleware(
            create_compression_middleware(
                minimum_size=1000,
                gzip_level=6,
                brotli_quality=4
            )
        )
        ```
    """
    def middleware_factory(app: ASGIApp) -> SmartCompressionMiddleware:
        return SmartCompressionMiddleware(
            app=app,
            minimum_size=minimum_size,
            gzip_level=gzip_level,
            brotli_quality=brotli_quality,
        )

    return middleware_factory


# ============================================================================
# Métricas y Estadísticas
# ============================================================================

class CompressionStats:
    """Clase para trackear estadísticas de compresión (opcional)."""

    def __init__(self):
        self.total_requests = 0
        self.compressed_requests = 0
        self.total_original_bytes = 0
        self.total_compressed_bytes = 0
        self.brotli_count = 0
        self.gzip_count = 0

    def record(self, original_size: int, compressed_size: int, encoding: str):
        """Registra una operación de compresión."""
        self.total_requests += 1
        if encoding in ("br", "gzip"):
            self.compressed_requests += 1
            self.total_original_bytes += original_size
            self.total_compressed_bytes += compressed_size

            if encoding == "br":
                self.brotli_count += 1
            else:
                self.gzip_count += 1

    def get_stats(self) -> dict:
        """Retorna estadísticas acumuladas."""
        if self.total_original_bytes == 0:
            return {"compression_ratio": 0, "savings_bytes": 0}

        savings = self.total_original_bytes - self.total_compressed_bytes
        ratio = (savings / self.total_original_bytes) * 100

        return {
            "total_requests": self.total_requests,
            "compressed_requests": self.compressed_requests,
            "compression_rate": f"{(self.compressed_requests / max(self.total_requests, 1)) * 100:.1f}%",
            "total_original_bytes": self.total_original_bytes,
            "total_compressed_bytes": self.total_compressed_bytes,
            "savings_bytes": savings,
            "compression_ratio": f"{ratio:.1f}%",
            "brotli_usage": self.brotli_count,
            "gzip_usage": self.gzip_count,
        }


# Singleton global para stats (opcional)
compression_stats = CompressionStats()
