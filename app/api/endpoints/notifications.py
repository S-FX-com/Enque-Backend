import logging
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Path, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.api.dependencies import get_db, get_current_active_user
from app.models.agent import Agent
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
    db: AsyncSession = Depends(get_db),
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

    response = await format_notification_settings_response(db, workspace_id)
    return response


@router.put("/{workspace_id}/template/{template_id}", response_model=dict)
async def update_notification_template_endpoint(
    template_data: NotificationTemplateUpdateRequest,
    workspace_id: int = Path(...),
    template_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
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
    template = await get_notification_template(db, template_id)
    if not template or template.workspace_id != workspace_id:
        raise HTTPException(
            status_code=404,
            detail="Template not found",
        )

    updated_template = await update_notification_template(
        db, template_id, template_data.content
    )

    if not updated_template:
        raise HTTPException(
            status_code=400,
            detail="Failed to update template",
        )

    return {"success": True, "message": "Template updated successfully"}


@router.post("/{workspace_id}/create-missing-settings", response_model=dict)
async def create_missing_notification_settings(
    workspace_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create missing notification settings for a workspace based on existing templates.
    """
    if current_user.workspace_id != workspace_id and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to create settings for this workspace",
        )

    from app.models.notification import NotificationSetting, NotificationTemplate
    from sqlalchemy import select
    import json
    from datetime import datetime

    # Get all templates for this workspace
    stmt = select(NotificationTemplate).where(NotificationTemplate.workspace_id == workspace_id)
    result = await db.execute(stmt)
    templates = result.scalars().all()

    # Get existing settings
    stmt = select(NotificationSetting).where(NotificationSetting.workspace_id == workspace_id)
    result = await db.execute(stmt)
    existing_settings = result.scalars().all()
    
    # Create a set of existing (category, type, channel) combinations
    existing_combinations = set()
    for setting in existing_settings:
        channels = json.loads(setting.channels) if isinstance(setting.channels, str) else setting.channels
        for channel in channels:
            existing_combinations.add((setting.category, setting.type, channel))
    
    # Define the expected settings based on templates and standard configurations
    settings_to_create = []
    
    for template in templates:
        # Determine category and channel based on template type
        if template.type.endswith("_agent"):
            category = "agents"
            base_type = template.type.replace("_agent", "")
        else:
            category = "users" if template.type in ["new_ticket_created", "ticket_closed", "new_agent_response"] else "agents"
            base_type = template.type
        
        # Map template types to notification types
        if base_type == "new_ticket_created":
            notification_type = "new_ticket_created"
        elif base_type == "ticket_closed":
            notification_type = "ticket_closed"
        elif base_type == "new_agent_response":
            notification_type = "new_agent_response"
        elif base_type == "new_response":
            notification_type = "new_response"
        elif base_type == "ticket_assigned":
            notification_type = "ticket_assigned"
        else:
            notification_type = base_type
        
        # Create email settings for users and agents
        if (category, notification_type, "email") not in existing_combinations:
            settings_to_create.append({
                "workspace_id": workspace_id,
                "category": category,
                "type": notification_type,
                "is_enabled": False,  # Default to disabled
                "channels": json.dumps(["email"]),
                "template_id": template.id,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
    
    # Create the missing settings
    created_count = 0
    for setting_data in settings_to_create:
        new_setting = NotificationSetting(**setting_data)
        db.add(new_setting)
        created_count += 1

    if created_count > 0:
        await db.commit()

    return {
        "success": True,
        "message": f"Created {created_count} missing notification settings",
        "created_count": created_count
    }


@router.put("/{workspace_id}/toggle/{setting_id}", response_model=dict)
async def toggle_notification_setting_endpoint(
    toggle_data: NotificationToggleRequest,
    workspace_id: int = Path(...),
    setting_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
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

    # If setting_id is 0, it means we need to create the setting
    if setting_id == 0:
        from app.models.notification import NotificationSetting, NotificationTemplate
        from sqlalchemy import select
        import json
        from datetime import datetime

        # Try to create missing notification settings for this workspace
        # Get all templates for this workspace
        stmt = select(NotificationTemplate).where(NotificationTemplate.workspace_id == workspace_id)
        result = await db.execute(stmt)
        templates = result.scalars().all()

        # Get existing settings
        stmt = select(NotificationSetting).where(NotificationSetting.workspace_id == workspace_id)
        result = await db.execute(stmt)
        existing_settings = result.scalars().all()
        
        # Create a set of existing (category, type, channel) combinations
        existing_combinations = set()
        for setting in existing_settings:
            channels = json.loads(setting.channels) if isinstance(setting.channels, str) else setting.channels
            for channel in channels:
                existing_combinations.add((setting.category, setting.type, channel))
        
        # Create missing settings based on templates
        created_count = 0
        for template in templates:
            # Determine category and channel based on template type
            if template.type.endswith("_agent"):
                category = "agents"
                base_type = template.type.replace("_agent", "")
            else:
                category = "users" if template.type in ["new_ticket_created", "ticket_closed", "new_agent_response"] else "agents"
                base_type = template.type
            
            # Map template types to notification types
            if base_type == "new_ticket_created":
                notification_type = "new_ticket_created"
            elif base_type == "ticket_closed":
                notification_type = "ticket_closed"
            elif base_type == "new_agent_response":
                notification_type = "new_agent_response"
            elif base_type == "new_response":
                notification_type = "new_response"
            elif base_type == "ticket_assigned":
                notification_type = "ticket_assigned"
            else:
                notification_type = base_type
            
            # Create email settings if they don't exist
            if (category, notification_type, "email") not in existing_combinations:
                new_setting = NotificationSetting(
                    workspace_id=workspace_id,
                    category=category,
                    type=notification_type,
                    is_enabled=toggle_data.is_enabled,  # Use the requested state
                    channels=json.dumps(["email"]),
                    template_id=template.id,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_setting)
                created_count += 1
        
        if created_count > 0:
            await db.commit()
            return {"success": True, "message": f"Created {created_count} missing notification settings"}
        else:
            # No settings were created, return an error
            raise HTTPException(
                status_code=400,
                detail="No missing notification settings found to create. Please refresh the page.",
            )

    # Check if setting exists and belongs to workspace
    setting = await get_notification_setting(db, setting_id)
    if not setting or setting.workspace_id != workspace_id:
        raise HTTPException(
            status_code=404,
            detail="Setting not found",
        )

    updated_setting = await toggle_notification_setting(
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
    db: AsyncSession = Depends(get_db),
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
    connected = await connect_notification_channel(db, workspace_id, "teams", config)

    if not connected:
        raise HTTPException(
            status_code=400,
            detail="Failed to connect Teams channel",
        )

    return {"success": True, "message": "Teams channel connected successfully"} 