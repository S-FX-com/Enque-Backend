from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

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

router = APIRouter()


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