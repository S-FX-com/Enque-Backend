import logging
import time
from typing import List, Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Path, Body, Request
from sqlalchemy.orm import Session, noload
from pydantic import BaseModel

from app.api.dependencies import get_db, get_current_active_user
from app.models.agent import Agent
from app.models.notification import NotificationTemplate, NotificationSetting
from app.schemas.notification import (
    NotificationSettingsResponse,
    NotificationToggleRequest,
    NotificationTeamsConnectRequest,
    NotificationTemplateUpdateRequest,
)
from app.core.notification_cache import notification_cache
from app.services.notification_service import (
    get_notification_templates,
    get_notification_settings,
    get_notification_template,
    get_notification_setting,
    update_notification_template,
    toggle_notification_setting,
    connect_notification_channel,
    format_notification_settings_response,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/fast/{workspace_id}", response_model=NotificationSettingsResponse)
async def get_workspace_notification_settings_fast(
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Obtener configuraciones de notificación optimizadas con cache.
    Versión ultra-rápida que usa cache y consultas optimizadas.
    """
    start_time = time.time()
    
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="No tienes permisos para acceder a las notificaciones de este workspace",
        )
    
    # Intentar obtener del cache primero
    cached_settings = notification_cache.get_notification_settings(workspace_id)
    if cached_settings:
        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"[NOTIFY_FAST] Settings obtenidas del cache en {duration_ms:.2f}ms para workspace {workspace_id}")
        return NotificationSettingsResponse(**cached_settings)
    
    # Cache miss - obtener de la base de datos con consultas optimizadas
    logger.info(f"[NOTIFY_FAST] Cache miss, consultando DB para workspace {workspace_id}")
    
    # Consultas optimizadas sin cargar relaciones automáticamente
    settings = db.query(NotificationSetting)\
        .options(noload(NotificationSetting.workspace))\
        .options(noload(NotificationSetting.template))\
        .filter(NotificationSetting.workspace_id == workspace_id)\
        .all()
    
    # Obtener templates solo si son necesarios
    template_ids = [s.template_id for s in settings if s.template_id]
    templates_dict = {}
    if template_ids:
        templates = db.query(NotificationTemplate)\
            .options(noload(NotificationTemplate.workspace))\
            .options(noload(NotificationTemplate.notification_settings))\
            .filter(NotificationTemplate.id.in_(template_ids))\
            .all()
        templates_dict = {t.id: t for t in templates}
    
    # Formatear respuesta manualmente para evitar consultas adicionales
    response_data = _format_notification_settings_optimized(settings, templates_dict)
    
    # Guardar en cache
    notification_cache.set_notification_settings(workspace_id, response_data)
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"[NOTIFY_FAST] Settings obtenidas de DB en {duration_ms:.2f}ms para workspace {workspace_id}")
    
    return NotificationSettingsResponse(**response_data)


@router.get("/templates/fast/{workspace_id}")
async def get_notification_templates_fast(
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> List[Dict[str, Any]]:
    """
    Obtener templates de notificación optimizados.
    """
    start_time = time.time()
    
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="No tienes permisos para acceder a los templates de este workspace",
        )
    
    # Consulta optimizada sin cargar relaciones
    templates = db.query(NotificationTemplate)\
        .options(noload(NotificationTemplate.workspace))\
        .options(noload(NotificationTemplate.notification_settings))\
        .filter(NotificationTemplate.workspace_id == workspace_id)\
        .all()
    
    result = [
        {
            "id": t.id,
            "type": t.type,
            "name": t.name,
            "subject": t.subject,
            "template": t.template,
            "is_enabled": t.is_enabled,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat()
        }
        for t in templates
    ]
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"[NOTIFY_FAST] {len(result)} templates obtenidos en {duration_ms:.2f}ms para workspace {workspace_id}")
    
    return result


@router.get("/settings/fast/{workspace_id}")
async def get_notification_settings_fast(
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> List[Dict[str, Any]]:
    """
    Obtener configuraciones de notificación optimizadas.
    """
    start_time = time.time()
    
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="No tienes permisos para acceder a las configuraciones de este workspace",
        )
    
    # Consulta optimizada sin cargar relaciones
    settings = db.query(NotificationSetting)\
        .options(noload(NotificationSetting.workspace))\
        .options(noload(NotificationSetting.template))\
        .filter(NotificationSetting.workspace_id == workspace_id)\
        .all()
    
    result = [
        {
            "id": s.id,
            "category": s.category,
            "type": s.type,
            "is_enabled": s.is_enabled,
            "channels": s.channels,
            "template_id": s.template_id,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat()
        }
        for s in settings
    ]
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"[NOTIFY_FAST] {len(result)} settings obtenidos en {duration_ms:.2f}ms para workspace {workspace_id}")
    
    return result


@router.put("/fast/{workspace_id}/template/{template_id}", response_model=dict)
async def update_notification_template_fast(
    template_data: NotificationTemplateUpdateRequest,
    workspace_id: int = Path(...),
    template_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Actualizar template de notificación optimizado.
    """
    start_time = time.time()
    
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="No tienes permisos para actualizar este template",
        )
    
    # Verificar que el template existe sin cargar relaciones
    template = db.query(NotificationTemplate)\
        .options(noload(NotificationTemplate.workspace))\
        .options(noload(NotificationTemplate.notification_settings))\
        .filter(
            NotificationTemplate.id == template_id,
            NotificationTemplate.workspace_id == workspace_id
        ).first()
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail="Template no encontrado",
        )
    
    # Actualizar template
    updated_template = update_notification_template(
        db, template_id, template_data.content
    )
    
    if not updated_template:
        raise HTTPException(
            status_code=400,
            detail="Falló la actualización del template",
        )
    
    # Invalidar cache
    notification_cache.invalidate_template(template_id)
    notification_cache.invalidate_workspace_settings(workspace_id)
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"[NOTIFY_FAST] Template {template_id} actualizado en {duration_ms:.2f}ms")
    
    return {"success": True, "message": "Template actualizado exitosamente"}


@router.put("/fast/{workspace_id}/toggle/{setting_id}", response_model=dict)
async def toggle_notification_setting_fast(
    toggle_data: NotificationToggleRequest,
    workspace_id: int = Path(...),
    setting_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Alternar configuración de notificación optimizada.
    """
    start_time = time.time()
    
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="No tienes permisos para alternar esta configuración",
        )
    
    # Verificar que la configuración existe sin cargar relaciones
    setting = db.query(NotificationSetting)\
        .options(noload(NotificationSetting.workspace))\
        .options(noload(NotificationSetting.template))\
        .filter(
            NotificationSetting.id == setting_id,
            NotificationSetting.workspace_id == workspace_id
        ).first()
    
    if not setting:
        raise HTTPException(
            status_code=404,
            detail="Configuración no encontrada",
        )
    
    # Actualizar configuración
    updated_setting = toggle_notification_setting(
        db, setting_id, toggle_data.is_enabled
    )
    
    if not updated_setting:
        raise HTTPException(
            status_code=400,
            detail="Falló la actualización de la configuración",
        )
    
    # Invalidar cache
    notification_cache.invalidate_workspace_settings(workspace_id)
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(f"[NOTIFY_FAST] Setting {setting_id} alternado en {duration_ms:.2f}ms")
    
    return {"success": True, "message": "Configuración actualizada exitosamente"}


@router.get("/cache/stats")
async def get_notification_cache_stats(
    current_user: Agent = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    Obtener estadísticas del cache de notificaciones.
    Solo accesible para admins y superadmins.
    """
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(
            status_code=403, 
            detail="Solo admins pueden ver estadísticas del cache"
        )
    
    return notification_cache.get_stats()


@router.post("/cache/clear")
async def clear_notification_cache(
    current_user: Agent = Depends(get_current_active_user)
) -> Dict[str, str]:
    """
    Limpiar el cache de notificaciones.
    Solo accesible para superadmins.
    """
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=403, 
            detail="Solo superadmins pueden limpiar el cache"
        )
    
    notification_cache.clear()
    return {"message": "Cache de notificaciones limpiado exitosamente"}


def _format_notification_settings_optimized(
    settings: List[NotificationSetting], 
    templates_dict: Dict[int, NotificationTemplate]
) -> Dict[str, Any]:
    """
    Formatear configuraciones de notificación de forma optimizada.
    """
    import json
    
    # Inicializar estructura de respuesta
    response_data = {
        "agents": {
            "email": {
                "new_ticket_created": {"is_enabled": False, "id": None, "template": None},
                "new_response": {"is_enabled": False, "id": None, "template": None},
                "ticket_assigned": {"is_enabled": False, "id": None, "template": None}
            },
            "enque_popup": {
                "new_ticket_created": {"is_enabled": False, "id": None},
                "new_response": {"is_enabled": False, "id": None},
                "ticket_assigned": {"is_enabled": False, "id": None}
            },
            "teams": {
                "is_connected": False,
                "is_enabled": False,
                "id": None
            }
        },
        "users": {
            "email": {
                "new_ticket_created": {"is_enabled": False, "id": None, "template": None},
                "ticket_closed": {"is_enabled": False, "id": None, "template": None},
                "new_agent_response": {"is_enabled": False, "id": None, "template": None}
            }
        }
    }
    
    # Procesar configuraciones
    for setting in settings:
        channels = json.loads(setting.channels) if isinstance(setting.channels, str) else setting.channels
        
        # Obtener contenido del template si existe
        template_content = None
        if setting.template_id and setting.template_id in templates_dict:
            template = templates_dict[setting.template_id]
            template_content = template.template
        
        # Procesar según categoría y tipo
        if setting.category == "agents":
            if setting.type == "new_ticket_created" and "email" in channels:
                response_data["agents"]["email"]["new_ticket_created"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id,
                    "template": template_content
                }
            elif setting.type == "new_response" and "email" in channels:
                response_data["agents"]["email"]["new_response"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id,
                    "template": template_content
                }
            elif setting.type == "ticket_assigned" and "email" in channels:
                response_data["agents"]["email"]["ticket_assigned"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id,
                    "template": template_content
                }
            elif setting.type == "new_ticket_created" and "enque_popup" in channels:
                response_data["agents"]["enque_popup"]["new_ticket_created"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id
                }
            elif setting.type == "new_response" and "enque_popup" in channels:
                response_data["agents"]["enque_popup"]["new_response"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id
                }
            elif setting.type == "ticket_assigned" and "enque_popup" in channels:
                response_data["agents"]["enque_popup"]["ticket_assigned"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id
                }
            elif setting.type == "teams":
                response_data["agents"]["teams"] = {
                    "is_enabled": setting.is_enabled,
                    "is_connected": True,
                    "id": setting.id
                }
        
        elif setting.category == "users":
            if setting.type == "new_ticket_created" and "email" in channels:
                response_data["users"]["email"]["new_ticket_created"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id,
                    "template": template_content
                }
            elif setting.type == "ticket_closed" and "email" in channels:
                response_data["users"]["email"]["ticket_closed"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id,
                    "template": template_content
                }
            elif setting.type == "new_agent_response" and "email" in channels:
                response_data["users"]["email"]["new_agent_response"] = {
                    "is_enabled": setting.is_enabled,
                    "id": setting.id,
                    "template": template_content
                }
    
    return response_data 