from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api.dependencies import get_current_active_user, get_current_active_admin, get_current_workspace
from app.database.session import get_db
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.models.automation import Automation
from app.schemas.automation import (
    Automation as AutomationSchema,
    AutomationCreate,
    AutomationUpdate
)
from app.services import automation_service
from app.utils.logger import logger
from app.services.notification_service import is_team_notification_enabled, toggle_notification_setting, get_notification_settings

router = APIRouter()


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


@router.get("/", response_model=List[AutomationSchema])
async def read_automations(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    active_only: bool = Query(False, description="Filter only active automations"),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve automations for the current workspace with pagination.
    """
    logger.info(f"Fetching automations for workspace {current_workspace.id} with skip={skip}, limit={limit}")
    
    if active_only:
        automations = automation_service.get_active_by_workspace_id(
            db=db, workspace_id=current_workspace.id, skip=skip, limit=limit
        )
    else:
        automations = automation_service.get_by_workspace_id(
            db=db, workspace_id=current_workspace.id, skip=skip, limit=limit
        )
    
    logger.info(f"Retrieved {len(automations)} automations.")
    return automations


@router.post("/", response_model=AutomationSchema)
async def create_automation(
    automation_in: AutomationCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Create a new automation.
    """
    logger.info(f"Creating automation '{automation_in.name}' for workspace {current_workspace.id}")
    
    # Set the workspace_id from the current workspace
    automation_in.workspace_id = current_workspace.id
    
    automation = automation_service.create(
        db=db, obj_in=automation_in, created_by_agent_id=current_user.id
    )
    
    logger.info(f"Created automation with ID {automation.id}")
    return automation


@router.get("/{automation_id}", response_model=AutomationSchema)
async def read_automation(
    automation_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get automation by ID.
    """
    automation = automation_service.get_by_id(db=db, id=automation_id)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )
    
    # Check if automation belongs to current workspace
    if automation.workspace_id != current_workspace.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )
    
    return automation


@router.put("/{automation_id}", response_model=AutomationSchema)
async def update_automation(
    automation_id: int,
    automation_in: AutomationUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Update an automation.
    """
    automation = automation_service.get_by_id(db=db, id=automation_id)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )
    
    # Check if automation belongs to current workspace
    if automation.workspace_id != current_workspace.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )
    
    automation = automation_service.update(db=db, db_obj=automation, obj_in=automation_in)
    logger.info(f"Updated automation {automation_id}")
    return automation


@router.delete("/{automation_id}", response_model=AutomationSchema)
async def delete_automation(
    automation_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Delete an automation.
    """
    automation = automation_service.get_by_id(db=db, id=automation_id)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )
    
    # Check if automation belongs to current workspace
    if automation.workspace_id != current_workspace.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )
    
    automation_service.delete(db=db, db_obj=automation)
    logger.info(f"Deleted automation {automation_id}")
    return automation


@router.get("/stats/summary")
async def get_automation_stats(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get automation statistics for the current workspace.
    """
    stats = automation_service.get_stats(db=db, workspace_id=current_workspace.id)
    return stats 


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
    
    # For team notifications, we use the notification_settings table
    from app.services.notification_service import get_notification_setting
    
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