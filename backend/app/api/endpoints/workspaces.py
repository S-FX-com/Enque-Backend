from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user, get_current_active_admin, get_current_workspace
from app.database.session import get_db
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.schemas.workspace import Workspace as WorkspaceSchema, WorkspaceCreate, WorkspaceUpdate
from app.services.workspace_service import (
    get_workspaces, 
    get_workspace, 
    get_workspace_by_subdomain,
    create_workspace, 
    update_workspace,
    delete_workspace
)

router = APIRouter()


@router.get("/", response_model=List[WorkspaceSchema])
async def read_workspaces(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_admin),
) -> Any:
    """
    Retrieve all workspaces (admin only)
    """
    workspaces = get_workspaces(db, skip=skip, limit=limit)
    return workspaces


@router.post("/", response_model=WorkspaceSchema)
async def create_workspace_endpoint(
    workspace_in: WorkspaceCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
) -> Any:
    """
    Create a new workspace (admin only)
    """
    # Check if subdomain already exists
    existing_workspace = get_workspace_by_subdomain(db, workspace_in.subdomain)
    if existing_workspace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A workspace with this subdomain already exists",
        )
    
    # Create the workspace
    workspace = create_workspace(db, workspace_in)
    return workspace


@router.get("/current", response_model=WorkspaceSchema)
async def read_current_workspace(
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get current workspace
    """
    return current_workspace


@router.get("/{workspace_id}", response_model=WorkspaceSchema)
async def read_workspace_endpoint(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
) -> Any:
    """
    Get workspace by ID (admin only)
    """
    workspace = get_workspace(db, workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return workspace


@router.put("/{workspace_id}", response_model=WorkspaceSchema)
async def update_workspace_endpoint(
    workspace_id: int,
    workspace_in: WorkspaceUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
) -> Any:
    """
    Update a workspace (admin only)
    """
    # Check if workspace exists
    workspace = get_workspace(db, workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    
    # Check if subdomain is being changed and already exists
    if "subdomain" in workspace_in.dict(exclude_unset=True):
        if workspace_in.subdomain != workspace.subdomain:
            existing_workspace = get_workspace_by_subdomain(db, workspace_in.subdomain)
            if existing_workspace:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A workspace with this subdomain already exists",
                )
    
    # Update the workspace
    updated_workspace = update_workspace(db, workspace_id, workspace_in)
    return updated_workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_endpoint(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
):
    """
    Delete a workspace (admin only)
    """
    success = delete_workspace(db, workspace_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) 