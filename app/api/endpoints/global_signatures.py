from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.dependencies import get_db, get_current_active_user as get_current_active_agent
from app.models.agent import Agent
from app.schemas.global_signature import GlobalSignature, GlobalSignatureCreate, GlobalSignatureUpdate
from app.services.global_signature_service import create, get_by_workspace_id, get_enabled_by_workspace_id, update, delete

router = APIRouter()


@router.post("/", response_model=GlobalSignature)
def create_global_signature(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    global_signature_in: GlobalSignatureCreate,
) -> Any:
    """Create a new global signature."""
    if current_agent.role != "admin":
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    # Check if a global signature already exists for this workspace
    existing_signature = get_by_workspace_id(
        db=db, workspace_id=global_signature_in.workspace_id
    )
    
    if existing_signature:
        raise HTTPException(
            status_code=400, detail="A global signature already exists for this workspace"
        )
    
    return create(
        db=db, obj_in=global_signature_in
    )


@router.get("/{workspace_id}", response_model=GlobalSignature)
def get_global_signature(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    workspace_id: int,
) -> Any:
    """Get global signature by workspace ID."""
    # Make sure the agent belongs to the workspace they're trying to query
    if current_agent.workspace_id != workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    global_signature = get_by_workspace_id(
        db=db, workspace_id=workspace_id
    )
    
    if global_signature is None:
        raise HTTPException(
            status_code=404, detail="Global signature not found"
        )
    
    return global_signature


@router.get("/{workspace_id}/enabled", response_model=GlobalSignature)
def get_enabled_global_signature(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    workspace_id: int,
) -> Any:
    """Get enabled global signature by workspace ID."""
    # Make sure the agent belongs to the workspace they're trying to query
    if current_agent.workspace_id != workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    global_signature = get_enabled_by_workspace_id(
        db=db, workspace_id=workspace_id
    )
    
    if global_signature is None:
        raise HTTPException(
            status_code=404, detail="No enabled global signature found"
        )
    
    return global_signature


@router.put("/{workspace_id}", response_model=GlobalSignature)
def update_global_signature(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    workspace_id: int,
    global_signature_in: GlobalSignatureUpdate,
) -> Any:
    """Update global signature."""
    # Only admins can update the global signature
    if current_agent.role != "admin":
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    # Make sure the agent belongs to the workspace they're trying to update
    if current_agent.workspace_id != workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    global_signature = get_by_workspace_id(
        db=db, workspace_id=workspace_id
    )
    
    if global_signature is None:
        # Create new global signature if it doesn't exist
        create_data = GlobalSignatureCreate(
            workspace_id=workspace_id,
            content=global_signature_in.content or ""
        )
        return create(
            db=db, obj_in=create_data
        )
    
    global_signature = update(
        db=db, db_obj=global_signature, obj_in=global_signature_in
    )
    
    return global_signature


@router.delete("/{workspace_id}")
def delete_global_signature(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    workspace_id: int,
) -> Any:
    """Delete global signature."""
    # Only admins can delete the global signature
    if current_agent.role != "admin":
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    # Make sure the agent belongs to the workspace they're trying to delete from
    if current_agent.workspace_id != workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    global_signature = get_by_workspace_id(
        db=db, workspace_id=workspace_id
    )
    
    if global_signature is None:
        raise HTTPException(
            status_code=404, detail="Global signature not found"
        )
    
    delete(db=db, db_obj=global_signature)
    
    return {"message": "Global signature deleted successfully"} 