import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api.dependencies import get_db, get_current_active_user
from app.models.agent import Agent
from app.models.notification import NotificationSetting
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
    daily_outstanding_tasks: AutomationSetting  # 🔧 ADDED: New automation for daily outstanding tasks
    weekly_manager_summary: AutomationSetting  # 🔧 ADDED: New automation for weekly manager summaries


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
    
    # Get automation settings
    stmt_team = select(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "teams",
        NotificationSetting.type == "new_ticket_created"
    )
    result_team = await db.execute(stmt_team)
    team_notification_setting = result_team.scalars().first()

    stmt_weekly = select(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "agents",
        NotificationSetting.type == "weekly_agent_summary"
    )
    result_weekly = await db.execute(stmt_weekly)
    weekly_summary_setting = result_weekly.scalars().first()

    # 🔧 ADDED: Get daily outstanding tasks setting
    stmt_daily = select(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "agents",
        NotificationSetting.type == "daily_outstanding_tasks"
    )
    result_daily = await db.execute(stmt_daily)
    daily_outstanding_setting = result_daily.scalars().first()

    # 🔧 ADDED: Get weekly manager summary setting
    stmt_manager = select(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "teams",
        NotificationSetting.type == "weekly_manager_summary"
    )
    result_manager = await db.execute(stmt_manager)
    weekly_manager_setting = result_manager.scalars().first()
    
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
    
    # 🔧 ADDED: Daily Outstanding Tasks setting
    if not daily_outstanding_setting:
        daily_outstanding_tasks = AutomationSetting(
            id=0,
            is_enabled=False,
            type="daily_outstanding_tasks",
            name="Daily Outstanding Tasks Report",
            description="Send daily outstanding tasks report to agents at 7am ET"
        )
    else:
        daily_outstanding_tasks = AutomationSetting(
            id=daily_outstanding_setting.id,
            is_enabled=daily_outstanding_setting.is_enabled,
            type=daily_outstanding_setting.type,
            name="Daily Outstanding Tasks Report",
            description="Send daily outstanding tasks report to agents at 7am ET"
        )
    
    # 🔧 ADDED: Weekly Manager Summary setting
    if not weekly_manager_setting:
        weekly_manager_summary = AutomationSetting(
            id=0,
            is_enabled=False,
            type="weekly_manager_summary",
            name="Weekly Manager Summary",
            description="Send weekly team summary emails to team managers on Fridays at 4pm ET"
        )
    else:
        weekly_manager_summary = AutomationSetting(
            id=weekly_manager_setting.id,
            is_enabled=weekly_manager_setting.is_enabled,
            type=weekly_manager_setting.type,
            name="Weekly Manager Summary",
            description="Send weekly team summary emails to team managers on Fridays at 4pm ET"
        )
    
    return AutomationsResponse(
        team_notifications=team_notifications,
        weekly_agent_summary=weekly_agent_summary,
        daily_outstanding_tasks=daily_outstanding_tasks,  # 🔧 ADDED: Include new automation
        weekly_manager_summary=weekly_manager_summary  # 🔧 ADDED: Include weekly manager summary
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
        await db.commit()
        await db.refresh(new_setting)
        
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
    
    import json
    from datetime import datetime
    
    # Check if setting already exists
    stmt = select(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "agents",
        NotificationSetting.type == "weekly_agent_summary"
    )
    result = await db.execute(stmt)
    existing_setting = result.scalars().first()
    
    if existing_setting:
        # Update existing setting
        existing_setting.is_enabled = toggle_data.is_enabled
        existing_setting.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(existing_setting)
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
        await db.commit()
        await db.refresh(new_setting)
    
    return {"success": True, "message": "Weekly agent summary setting updated successfully"} 


# New endpoint specifically for creating daily outstanding tasks setting
@router.post("/{workspace_id}/daily-outstanding", response_model=dict)
async def create_daily_outstanding_setting(
    toggle_data: AutomationToggleRequest,
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create or update daily outstanding tasks setting.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to modify this workspace's settings",
        )
    
    import json
    from datetime import datetime
    
    # Check if setting already exists
    stmt = select(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "agents",
        NotificationSetting.type == "daily_outstanding_tasks"
    )
    result = await db.execute(stmt)
    existing_setting = result.scalars().first()
    
    if existing_setting:
        # Update existing setting
        existing_setting.is_enabled = toggle_data.is_enabled
        existing_setting.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(existing_setting)
    else:
        # Create new setting
        new_setting = NotificationSetting(
            workspace_id=workspace_id,
            category="agents",
            type="daily_outstanding_tasks",
            is_enabled=toggle_data.is_enabled,
            channels=json.dumps(["email"]),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(new_setting)
        await db.commit()
        await db.refresh(new_setting)
    
    return {"success": True, "message": "Daily outstanding tasks setting updated successfully"}


# New endpoint specifically for creating weekly manager summary setting
@router.post("/{workspace_id}/weekly-manager-summary", response_model=dict)
async def create_weekly_manager_summary_setting(
    toggle_data: AutomationToggleRequest,
    workspace_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create or update weekly manager summary setting.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to modify this workspace's settings",
        )
    
    import json
    from datetime import datetime
    
    # Check if setting already exists
    stmt = select(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "teams",
        NotificationSetting.type == "weekly_manager_summary"
    )
    result = await db.execute(stmt)
    existing_setting = result.scalars().first()
    
    if existing_setting:
        # Update existing setting
        existing_setting.is_enabled = toggle_data.is_enabled
        existing_setting.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(existing_setting)
    else:
        # Create new setting
        new_setting = NotificationSetting(
            workspace_id=workspace_id,
            category="teams",
            type="weekly_manager_summary",
            is_enabled=toggle_data.is_enabled,
            channels=json.dumps(["email"]),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(new_setting)
        await db.commit()
        await db.refresh(new_setting)
    
    return {"success": True, "message": "Weekly manager summary setting updated successfully"}
