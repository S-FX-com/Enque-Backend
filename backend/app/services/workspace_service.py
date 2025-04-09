from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate


def create_workspace(db: Session, workspace_in: WorkspaceCreate) -> Workspace:
    """
    Create a new workspace
    """
    db_workspace = Workspace(**workspace_in.dict())
    db.add(db_workspace)
    db.commit()
    db.refresh(db_workspace)
    return db_workspace


def get_workspace(db: Session, workspace_id: int) -> Optional[Workspace]:
    """
    Get a workspace by its ID
    """
    return db.query(Workspace).filter(Workspace.id == workspace_id).first()


def get_workspace_by_subdomain(db: Session, subdomain: str) -> Optional[Workspace]:
    """
    Get a workspace by its subdomain
    """
    return db.query(Workspace).filter(Workspace.subdomain == subdomain).first()


def get_workspaces(
    db: Session, 
    skip: int = 0, 
    limit: int = 100
) -> List[Workspace]:
    """
    Get a list of workspaces
    """
    return db.query(Workspace).order_by(Workspace.name).offset(skip).limit(limit).all()


def update_workspace(
    db: Session, 
    workspace_id: int, 
    workspace_in: WorkspaceUpdate
) -> Optional[Workspace]:
    """
    Update an existing workspace
    """
    db_workspace = get_workspace(db, workspace_id)
    if not db_workspace:
        return None
    
    update_data = workspace_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_workspace, field, value)
    
    db.commit()
    db.refresh(db_workspace)
    return db_workspace


def delete_workspace(db: Session, workspace_id: int) -> bool:
    """
    Delete a workspace
    
    Returns True if successfully deleted, False if not found
    """
    db_workspace = get_workspace(db, workspace_id)
    if not db_workspace:
        return False
    
    db.delete(db_workspace)
    db.commit()
    return True 