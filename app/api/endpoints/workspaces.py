from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from typing import List

from app.models.agent import Agent
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.services.workspace import (
    create_workspace,
    get_workspaces,
    get_workspace,
    update_workspace,
    delete_workspace,
)

router = APIRouter()


@router.post("/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_route(
    workspace: WorkspaceCreate,
    db: Session = Depends(get_db),
):
    return create_workspace(db, workspace)


@router.get("/", response_model=List[WorkspaceResponse])
def get_workspaces_route(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return get_workspaces(db, request, skip, limit)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace_route(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_workspace(db, workspace_id)


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace_route(
    workspace_id: int,
    workspace: WorkspaceUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return update_workspace(db, workspace_id, workspace)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace_route(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    delete_workspace(db, workspace_id)
    return None
