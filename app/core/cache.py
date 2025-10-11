"""
Sistema de caché para usuarios autenticados
Almacena datos de usuario por 5 minutos para evitar consultas repetitivas a la DB
"""
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

@dataclass
class CachedUserData:
    """Estructura para almacenar datos del usuario en caché"""
    id: int
    name: str
    email: str
    role: str
    workspace_id: int
    is_active: bool
    cached_at: float
    expires_at: float

    def is_expired(self) -> bool:
        """Verifica si el caché ha expirado"""
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para logging"""
        return asdict(self)

class UserCache:
    """
    Cache en memoria para datos de usuarios autenticados
    Cache por 5 minutos para evitar consultas repetitivas
    """
    
    def __init__(self, cache_duration_minutes: int = 5):
        self._cache: Dict[int, CachedUserData] = {}
        self._cache_duration = cache_duration_minutes * 60  # Convertir a segundos

    def get(self, user_id: int) -> Optional[CachedUserData]:
        """
        Obtiene datos del usuario desde el caché
        Returns None si no existe o ha expirado
        """
        if user_id not in self._cache:
            return None
        
        cached_data = self._cache[user_id]
        
        if cached_data.is_expired():
            del self._cache[user_id]
            return None
        
        return cached_data

    def set(self, user_data: 'Agent') -> None:
        """
        Almacena datos del usuario en el caché
        """
        current_time = time.time()
        expires_at = current_time + self._cache_duration
        
        cached_user = CachedUserData(
            id=user_data.id,
            name=user_data.name,
            email=user_data.email,
            role=user_data.role,
            workspace_id=user_data.workspace_id,
            is_active=user_data.is_active,
            cached_at=current_time,
            expires_at=expires_at
        )
        
        self._cache[user_data.id] = cached_user

    def delete(self, user_id: int) -> None:
        """
        Elimina usuario del caché (útil cuando se actualiza perfil)
        """
        if user_id in self._cache:
            del self._cache[user_id]

    def clear_expired(self) -> None:
        """
        Limpia entradas expiradas del caché
        """
        current_time = time.time()
        expired_users = [
            user_id for user_id, cached_data in self._cache.items()
            if cached_data.expires_at <= current_time
        ]
        
        for user_id in expired_users:
            del self._cache[user_id]

    def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas del caché para monitoring
        """
        current_time = time.time()
        active_count = len([
            cached_data for cached_data in self._cache.values()
            if cached_data.expires_at > current_time
        ])
        
        return {
            "total_cached_users": len(self._cache),
            "active_cached_users": active_count,
            "cache_duration_minutes": self._cache_duration / 60,
            "cache_hit_data": list(self._cache.keys())
        }

# Instancia global del caché
user_cache = UserCache()

def create_user_from_cache(cached_data: CachedUserData) -> 'Agent':
    """
    Crea un objeto Agent desde datos cacheados
    Solo incluye los campos esenciales, sin relaciones pesadas
    """
    from app.models.agent import Agent
    
    user = Agent()
    user.id = cached_data.id
    user.name = cached_data.name
    user.email = cached_data.email
    user.role = cached_data.role
    user.workspace_id = cached_data.workspace_id
    user.is_active = cached_data.is_active
    
    return user 