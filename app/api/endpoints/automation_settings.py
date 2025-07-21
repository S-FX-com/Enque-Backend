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
    weekly_agent_summary: AutomationSetting


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
    weekly_summary_setting = None
    
    for setting in settings:
        if setting.category == "agents" and setting.type == "new_ticket_for_team":
            team_notification_setting = setting
        elif setting.category == "agents" and setting.type == "weekly_agent_summary":
            weekly_summary_setting = setting
    
    # If no team notification setting exists, create a default one
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
    
    # If no weekly summary setting exists, create a default one
    if not weekly_summary_setting:
        weekly_agent_summary = AutomationSetting(
            id=0,
            is_enabled=False,
            type="weekly_agent_summary",
            name="Weekly Agent Summary",
            description="Send weekly summary emails to agents on Fridays at 3pm ET"
        )
    else:
        weekly_agent_summary = AutomationSetting(
            id=weekly_summary_setting.id,
            is_enabled=weekly_summary_setting.is_enabled,
            type=weekly_summary_setting.type,
            name="Weekly Agent Summary",
            description="Send weekly summary emails to agents on Fridays at 3pm ET"
        )
    
    return AutomationsResponse(
        team_notifications=team_notifications,
        weekly_agent_summary=weekly_agent_summary
    )


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
        # Need to determine which type of setting to create based on request
        # For now, we'll handle team notifications as before
        # We need a way to distinguish between different types when creating
        # This endpoint might need to be enhanced to accept setting type
        from app.models.notification import NotificationSetting
        import json
        from datetime import datetime
        
        # Default to team notification for backward compatibility
        # TODO: Enhance this endpoint to handle different setting types
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


# New endpoint specifically for creating weekly agent summary setting
@router.post("/{workspace_id}/weekly-summary", response_model=dict)
async def create_weekly_summary_setting(
    toggle_data: AutomationToggleRequest,
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create or update weekly agent summary setting.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to modify this workspace's settings",
        )
    
    from app.models.notification import NotificationSetting
    import json
    from datetime import datetime
    
    # Check if setting already exists
    existing_setting = db.query(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "agents",
        NotificationSetting.type == "weekly_agent_summary"
    ).first()
    
    if existing_setting:
        # Update existing setting
        existing_setting.is_enabled = toggle_data.is_enabled
        existing_setting.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing_setting)
    else:
        # Create new setting
        new_setting = NotificationSetting(
            workspace_id=workspace_id,
            category="agents",
            type="weekly_agent_summary",
            is_enabled=toggle_data.is_enabled,
            channels=json.dumps(["email"]),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(new_setting)
        db.commit()
        db.refresh(new_setting)
    
    return {"success": True, "message": "Weekly agent summary setting updated successfully"} 