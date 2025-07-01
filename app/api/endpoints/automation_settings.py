import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api.dependencies import get_db, get_current_active_user
from app.models.agent import Agent
from app.services.notification_service import get_notification_settings, toggle_notification_setting, get_notification_setting

router = APIRouter()
logger = logging.getLogger(__name__)


class AutomationSetting(BaseModel):
    """Schema for automation setting."""
    id: int
    is_enabled: bool
    type: str
    name: str
    description: str


class AutomationsResponse(BaseModel):
    """Response schema for automation settings."""
    team_notifications: AutomationSetting


class AutomationToggleRequest(BaseModel):
    """Request schema for toggling an automation setting."""
    is_enabled: bool


@router.get("/{workspace_id}", response_model=AutomationsResponse)
async def get_workspace_automation_settings(
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get all automation settings for a workspace.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this workspace's automations",
        )
    
    # Get team notification setting
    settings = get_notification_settings(db, workspace_id)
    team_notification_setting = None
    
    for setting in settings:
        if setting.category == "agents" and setting.type == "new_ticket_for_team":
            team_notification_setting = setting
            break
    
    # If no setting exists, create a default one
    if not team_notification_setting:
        team_notifications = AutomationSetting(
            id=0,
            is_enabled=False,
            type="new_ticket_for_team",
            name="New Ticket for Your Team",
            description="Notify team members when a new ticket is assigned to their team"
        )
    else:
        team_notifications = AutomationSetting(
            id=team_notification_setting.id,
            is_enabled=team_notification_setting.is_enabled,
            type=team_notification_setting.type,
            name="New Ticket for Your Team",
            description="Notify team members when a new ticket is assigned to their team"
        )
    
    return AutomationsResponse(team_notifications=team_notifications)


@router.put("/{workspace_id}/toggle/{setting_id}", response_model=dict)
async def toggle_automation_setting_endpoint(
    toggle_data: AutomationToggleRequest,
    workspace_id: int = Path(...),
    setting_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Toggle an automation setting.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to toggle this setting",
        )
    
    # If setting_id is 0, it means we need to create the setting
    if setting_id == 0:
        # Create the notification setting
        from app.models.notification import NotificationSetting
        import json
        from datetime import datetime
        
        new_setting = NotificationSetting(
            workspace_id=workspace_id,
            category="agents",
            type="new_ticket_for_team",
            is_enabled=toggle_data.is_enabled,
            channels=json.dumps(["email"]),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(new_setting)
        db.commit()
        db.refresh(new_setting)
        
        return {"success": True, "message": "Automation setting created successfully"}
    
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
    
    return {"success": True, "message": "Automation setting updated successfully"} 