from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from app.models.workspace import Workspace
from app.models.agent import Agent
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate, WorkspaceSetupCreate, WorkspaceSetupResponse
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings

async def create_workspace(db: AsyncSession, workspace_in: WorkspaceCreate) -> Workspace:
    """
    Create a new workspace
    """
    db_workspace = Workspace(**workspace_in.dict())
    db.add(db_workspace)
    await db.commit()
    await db.refresh(db_workspace)
    return db_workspace

async def get_workspace(db: AsyncSession, workspace_id: int) -> Optional[Workspace]:
    """
    Get a workspace by its ID
    """
    result = await db.execute(select(Workspace).filter(Workspace.id == workspace_id))
    return result.scalars().first()

async def get_workspace_by_subdomain(db: AsyncSession, subdomain: str) -> Optional[Workspace]:
    """
    Get a workspace by its subdomain
    """
    result = await db.execute(select(Workspace).filter(Workspace.subdomain == subdomain))
    return result.scalars().first()

async def get_workspaces(
    db: AsyncSession, 
    skip: int = 0, 
    limit: int = 100
) -> List[Workspace]:
    """
    Get a list of workspaces
    """
    result = await db.execute(select(Workspace).order_by(Workspace.subdomain).offset(skip).limit(limit))
    return result.scalars().all()

async def update_workspace(
    db: AsyncSession, 
    workspace_id: int, 
    workspace_in: WorkspaceUpdate
) -> Optional[Workspace]:
    """
    Update an existing workspace
    """
    db_workspace = await get_workspace(db, workspace_id)
    if not db_workspace:
        return None
    
    update_data = workspace_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_workspace, field, value)
    
    await db.commit()
    await db.refresh(db_workspace)
    return db_workspace

async def delete_workspace(db: AsyncSession, workspace_id: int) -> bool:
    """
    Delete a workspace
    
    Returns True if successfully deleted, False if not found
    """
    db_workspace = await get_workspace(db, workspace_id)
    if not db_workspace:
        return False
    
    await db.delete(db_workspace)
    await db.commit()
    return True

async def setup_workspace(db: AsyncSession, setup_data: WorkspaceSetupCreate) -> WorkspaceSetupResponse:
    """
    Create a new workspace with the first admin user.
    This is a public endpoint for initial setup.
    """
    try:
        existing_workspace = await get_workspace_by_subdomain(db, setup_data.subdomain)
        if existing_workspace:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A workspace with this subdomain already exists"
            )
        
        workspace_data = WorkspaceCreate(subdomain=setup_data.subdomain)
        workspace = await create_workspace(db, workspace_data)
        
        admin = Agent(
            name=setup_data.admin_name,
            email=setup_data.admin_email,
            password=get_password_hash(setup_data.admin_password),
            role="admin",
            is_active=True,
            workspace_id=workspace.id
        )
        
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        
        access_token = create_access_token(
            subject=str(admin.id),
            extra_data={"workspace_id": workspace.id}
        )
        
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
        
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database error: subdomain or email already exists"
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating workspace: {str(e)}"
        )
