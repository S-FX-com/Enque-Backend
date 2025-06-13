import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

@dataclass
class CachedNotificationSettings:
    """Configuraciones de notificación cacheadas"""
    workspace_id: int
    settings_data: Dict[str, Any]
    cached_at: datetime
    expires_at: datetime

@dataclass
class CachedNotificationTemplate:
    """Template de notificación cacheado"""
    template_id: int
    workspace_id: int
    template_data: Dict[str, Any]
    cached_at: datetime
    expires_at: datetime

class NotificationCache:
    """Cache específico para notificaciones"""
    
    def __init__(self, default_ttl_minutes: int = 10):
        self.settings_cache: Dict[int, CachedNotificationSettings] = {}
        self.template_cache: Dict[int, CachedNotificationTemplate] = {}
        self.default_ttl = timedelta(minutes=default_ttl_minutes)
        
        # Estadísticas
        self.settings_hits = 0
        self.settings_misses = 0
        self.template_hits = 0
        self.template_misses = 0
        
    def get_notification_settings(self, workspace_id: int) -> Optional[Dict[str, Any]]:
        """Obtener configuraciones de notificación del cache"""
        if workspace_id in self.settings_cache:
            cached = self.settings_cache[workspace_id]
            if datetime.utcnow() < cached.expires_at:
                self.settings_hits += 1
                logger.debug(f"[NOTIFY_CACHE] Cache HIT para settings workspace {workspace_id}")
                return cached.settings_data
            else:
                # Cache expirado
                del self.settings_cache[workspace_id]
                logger.debug(f"[NOTIFY_CACHE] Cache EXPIRED para settings workspace {workspace_id}")
        
        self.settings_misses += 1
        logger.debug(f"[NOTIFY_CACHE] Cache MISS para settings workspace {workspace_id}")
        return None
    
    def set_notification_settings(self, workspace_id: int, settings_data: Dict[str, Any], ttl_minutes: Optional[int] = None):
        """Almacenar configuraciones de notificación en cache"""
        ttl = timedelta(minutes=ttl_minutes) if ttl_minutes else self.default_ttl
        now = datetime.utcnow()
        
        cached_settings = CachedNotificationSettings(
            workspace_id=workspace_id,
            settings_data=settings_data,
            cached_at=now,
            expires_at=now + ttl
        )
        
        self.settings_cache[workspace_id] = cached_settings
        logger.debug(f"[NOTIFY_CACHE] Settings cacheadas para workspace {workspace_id} (TTL: {ttl_minutes or self.default_ttl.seconds/60}min)")
    
    def get_notification_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        """Obtener template de notificación del cache"""
        if template_id in self.template_cache:
            cached = self.template_cache[template_id]
            if datetime.utcnow() < cached.expires_at:
                self.template_hits += 1
                logger.debug(f"[NOTIFY_CACHE] Cache HIT para template {template_id}")
                return cached.template_data
            else:
                # Cache expirado
                del self.template_cache[template_id]
                logger.debug(f"[NOTIFY_CACHE] Cache EXPIRED para template {template_id}")
        
        self.template_misses += 1
        logger.debug(f"[NOTIFY_CACHE] Cache MISS para template {template_id}")
        return None
    
    def set_notification_template(self, template_id: int, workspace_id: int, template_data: Dict[str, Any], ttl_minutes: Optional[int] = None):
        """Almacenar template de notificación en cache"""
        ttl = timedelta(minutes=ttl_minutes) if ttl_minutes else self.default_ttl
        now = datetime.utcnow()
        
        cached_template = CachedNotificationTemplate(
            template_id=template_id,
            workspace_id=workspace_id,
            template_data=template_data,
            cached_at=now,
            expires_at=now + ttl
        )
        
        self.template_cache[template_id] = cached_template
        logger.debug(f"[NOTIFY_CACHE] Template cacheado {template_id} (TTL: {ttl_minutes or self.default_ttl.seconds/60}min)")
    
    def invalidate_workspace_settings(self, workspace_id: int):
        """Invalidar cache de configuraciones para un workspace"""
        if workspace_id in self.settings_cache:
            del self.settings_cache[workspace_id]
            logger.info(f"[NOTIFY_CACHE] Cache invalidado para settings workspace {workspace_id}")
    
    def invalidate_template(self, template_id: int):
        """Invalidar cache de template específico"""
        if template_id in self.template_cache:
            del self.template_cache[template_id]
            logger.info(f"[NOTIFY_CACHE] Cache invalidado para template {template_id}")
    
    def invalidate_workspace_templates(self, workspace_id: int):
        """Invalidar todos los templates de un workspace"""
        templates_to_remove = []
        for template_id, cached in self.template_cache.items():
            if cached.workspace_id == workspace_id:
                templates_to_remove.append(template_id)
        
        for template_id in templates_to_remove:
            del self.template_cache[template_id]
        
        if templates_to_remove:
            logger.info(f"[NOTIFY_CACHE] {len(templates_to_remove)} templates invalidados para workspace {workspace_id}")
    
    def clear(self):
        """Limpiar todo el cache"""
        settings_count = len(self.settings_cache)
        template_count = len(self.template_cache)
        
        self.settings_cache.clear()
        self.template_cache.clear()
        
        # Resetear estadísticas
        self.settings_hits = 0
        self.settings_misses = 0
        self.template_hits = 0
        self.template_misses = 0
        
        logger.info(f"[NOTIFY_CACHE] Cache limpiado: {settings_count} settings + {template_count} templates")
    
    def cleanup_expired(self):
        """Limpiar entries expirados"""
        now = datetime.utcnow()
        
        # Limpiar settings expirados
        expired_settings = []
        for workspace_id, cached in self.settings_cache.items():
            if now >= cached.expires_at:
                expired_settings.append(workspace_id)
        
        for workspace_id in expired_settings:
            del self.settings_cache[workspace_id]
        
        # Limpiar templates expirados
        expired_templates = []
        for template_id, cached in self.template_cache.items():
            if now >= cached.expires_at:
                expired_templates.append(template_id)
        
        for template_id in expired_templates:
            del self.template_cache[template_id]
        
        if expired_settings or expired_templates:
            logger.debug(f"[NOTIFY_CACHE] Limpieza automática: {len(expired_settings)} settings + {len(expired_templates)} templates expirados")
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtener estadísticas del cache"""
        self.cleanup_expired()  # Limpiar antes de reportar stats
        
        settings_total = self.settings_hits + self.settings_misses
        template_total = self.template_hits + self.template_misses
        
        return {
            "settings_cache": {
                "entries": len(self.settings_cache),
                "hits": self.settings_hits,
                "misses": self.settings_misses,
                "hit_rate": round(self.settings_hits / settings_total * 100, 1) if settings_total > 0 else 0
            },
            "template_cache": {
                "entries": len(self.template_cache),
                "hits": self.template_hits,
                "misses": self.template_misses,
                "hit_rate": round(self.template_hits / template_total * 100, 1) if template_total > 0 else 0
            },
            "total_entries": len(self.settings_cache) + len(self.template_cache),
            "ttl_minutes": self.default_ttl.seconds // 60
        }

# Instancia global del cache de notificaciones
notification_cache = NotificationCache() 