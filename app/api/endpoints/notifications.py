import logging
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Path, Body, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
import json
from datetime import datetime
from sqlalchemy.sql import func

from app.api.dependencies import get_db, get_current_active_user
from app.models.agent import Agent
from app.models.notification import NotificationSetting
from app.schemas.notification import (
    NotificationSettingsResponse,
    NotificationToggleRequest,
    NotificationTeamsConnectRequest,
    NotificationTemplateUpdateRequest,
)
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


@router.get("/{workspace_id}", response_model=NotificationSettingsResponse)
async def get_workspace_notification_settings(
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get all notification settings for a workspace.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this workspace's notifications",
        )
    
    response = format_notification_settings_response(db, workspace_id)
    return response


@router.put("/{workspace_id}/template/{template_id}", response_model=dict)
async def update_notification_template_endpoint(
    template_data: NotificationTemplateUpdateRequest,
    workspace_id: int = Path(...),
    template_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Update a notification template.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to update this template",
        )
    
    # Check if template exists and belongs to workspace
    template = get_notification_template(db, template_id)
    if not template or template.workspace_id != workspace_id:
        raise HTTPException(
            status_code=404,
            detail="Template not found",
        )
    
    updated_template = update_notification_template(
        db, template_id, template_data.content
    )
    
    if not updated_template:
        raise HTTPException(
            status_code=400,
            detail="Failed to update template",
        )
    
    return {"success": True, "message": "Template updated successfully"}


@router.put("/{workspace_id}/toggle/{setting_id}", response_model=dict)
async def toggle_notification_setting_endpoint(
    toggle_data: NotificationToggleRequest,
    workspace_id: int = Path(...),
    setting_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Toggle a notification setting.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to toggle this setting",
        )
    
    # Check if setting exists and belongs to workspace
    setting = get_notification_setting(db, setting_id)
    if not setting or setting.workspace_id != workspace_id:
        raise HTTPException(
            status_code=404,
            detail="Setting not found",
        )
    
    updated_setting = toggle_notification_setting(
        db, setting_id, toggle_data.is_enabled
    )
    
    if not updated_setting:
        raise HTTPException(
            status_code=400,
            detail="Failed to update setting",
        )
    
    return {"success": True, "message": "Setting updated successfully"}


@router.post("/{workspace_id}/connect/teams", response_model=dict)
async def connect_teams_channel(
    connect_data: NotificationTeamsConnectRequest,
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Connect Microsoft Teams notification channel.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to connect Teams for this workspace",
        )
    
    config = {"webhook_url": connect_data.webhook_url}
    connected = connect_notification_channel(db, workspace_id, "teams", config)
    
    if not connected:
        raise HTTPException(
            status_code=400,
            detail="Failed to connect Teams channel",
        )
    
    return {"success": True, "message": "Teams channel connected successfully"}


@router.post("/{workspace_id}/connect/enque_popup", response_model=dict)
async def connect_popup_channel(
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Connect Enque popup notification channel.
    Initializes all popup notification settings if they don't exist.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to connect popup notifications for this workspace",
        )
    
    # Initialize popup settings for all notification types
    try:
        # Tipos de notificaciones a actualizar
        notification_types = ["new_ticket_created", "new_response", "ticket_assigned"]
        
        for notification_type in notification_types:
            # Buscar configuración existente
            setting = db.query(NotificationSetting).filter(
                NotificationSetting.workspace_id == workspace_id,
                NotificationSetting.category == "agents",
                NotificationSetting.type == notification_type
            ).first()
            
            if setting:
                # Actualizar configuración existente añadiendo canal enque_popup
                channels = json.loads(setting.channels) if isinstance(setting.channels, str) else setting.channels
                if "enque_popup" not in channels:
                    channels.append("enque_popup")
                    setting.channels = json.dumps(channels)
                    setting.updated_at = datetime.utcnow()
            else:
                # Si no existe, crear una nueva configuración
                new_setting = NotificationSetting(
                    workspace_id=workspace_id,
                    category="agents",
                    type=notification_type,
                    is_enabled=True,
                    channels=json.dumps(["enque_popup"]),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_setting)
        
        db.commit()
        
        return {"success": True, "message": "Popup notifications initialized successfully"}
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error initializing popup notifications: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize popup notifications: {str(e)}",
        ) 