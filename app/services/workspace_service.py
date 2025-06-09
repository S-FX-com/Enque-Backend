from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from app.models.workspace import Workspace
from app.models.agent import Agent
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate, WorkspaceSetupCreate, WorkspaceSetupResponse
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings


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
    return db.query(Workspace).order_by(Workspace.subdomain).offset(skip).limit(limit).all()


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


def setup_workspace(db: Session, setup_data: WorkspaceSetupCreate) -> WorkspaceSetupResponse:
    """
    Create a new workspace with the first admin user.
    This is a public endpoint for initial setup.
    """
    try:
        # Verificar que el subdomain no exista
        existing_workspace = get_workspace_by_subdomain(db, setup_data.subdomain)
        if existing_workspace:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A workspace with this subdomain already exists"
            )
        
        # Con múltiples workspaces, el mismo email puede existir en diferentes workspaces
        # Solo verificamos que el subdomain sea único
        # existing_agent = db.query(Agent).filter(Agent.email == setup_data.admin_email).first()
        # if existing_agent:
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail="An agent with this email already exists"
        #     )
        
        # Crear workspace
        workspace_data = WorkspaceCreate(subdomain=setup_data.subdomain)
        workspace = create_workspace(db, workspace_data)
        
        # Crear primer admin
        admin = Agent(
            name=setup_data.admin_name,
            email=setup_data.admin_email,
            password=get_password_hash(setup_data.admin_password),
            role="admin",
            is_active=True,
            workspace_id=workspace.id
        )
        
        db.add(admin)
        db.commit()
        db.refresh(admin)
        
        # Crear token de acceso
        access_token = create_access_token(
            subject=str(admin.id),
            extra_data={"workspace_id": workspace.id}
        )
        
        # Preparar response
        admin_dict = {
            "id": admin.id,
            "name": admin.name,
            "email": admin.email,
            "role": admin.role,
            "is_active": admin.is_active,
            "workspace_id": admin.workspace_id,
            "created_at": admin.created_at.isoformat() if admin.created_at else None,
            "updated_at": admin.updated_at.isoformat() if admin.updated_at else None,
        }
        
        return WorkspaceSetupResponse(
            workspace=workspace,
            admin=admin_dict,
            access_token=access_token,
            token_type="bearer"
        )
        
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database error: subdomain or email already exists"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating workspace: {str(e)}"
        ) 