from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.dependencies import get_db, get_current_active_user as get_current_active_agent
from app.models.agent import Agent
from app.schemas.canned_reply import CannedReply, CannedReplyCreate, CannedReplyUpdate
from app.services.canned_reply_service import create, get_by_id, get_by_workspace_id, get_enabled_by_workspace_id, update, delete

router = APIRouter()


@router.post("/", response_model=CannedReply)
def create_canned_reply(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    canned_reply_in: CannedReplyCreate,
) -> Any:
    """Create a new canned reply."""
    if current_agent.role != "admin":
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    # Make sure the agent belongs to the workspace they're trying to create for
    if current_agent.workspace_id != canned_reply_in.workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    return create(
        db=db, obj_in=canned_reply_in
    )


@router.get("/", response_model=List[CannedReply])
def get_canned_replies(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    workspace_id: Optional[int] = Query(None, description="Filter by workspace ID"),
    enabled_only: bool = Query(False, description="Return only enabled canned replies"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of records to return"),
) -> Any:
    """Get canned replies with optional filtering."""
    # If workspace_id is provided, make sure the agent belongs to that workspace
    target_workspace_id = workspace_id or current_agent.workspace_id
    
    if current_agent.workspace_id != target_workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    if enabled_only:
        canned_replies = get_enabled_by_workspace_id(
            db=db, workspace_id=target_workspace_id, skip=skip, limit=limit
        )
    else:
        canned_replies = get_by_workspace_id(
            db=db, workspace_id=target_workspace_id, skip=skip, limit=limit
        )
    
    return canned_replies


@router.get("/{canned_reply_id}", response_model=CannedReply)
def get_canned_reply(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    canned_reply_id: int,
) -> Any:
    """Get canned reply by ID."""
    canned_reply = get_by_id(
        db=db, id=canned_reply_id
    )
    
    if canned_reply is None:
        raise HTTPException(
            status_code=404, detail="Canned reply not found"
        )
    
    # Make sure the agent belongs to the workspace of the canned reply
    if current_agent.workspace_id != canned_reply.workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    return canned_reply


@router.put("/{canned_reply_id}", response_model=CannedReply)
def update_canned_reply(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    canned_reply_id: int,
    canned_reply_in: CannedReplyUpdate,
) -> Any:
    """Update canned reply."""
    # Only admins can update canned replies
    if current_agent.role != "admin":
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    canned_reply = get_by_id(
        db=db, id=canned_reply_id
    )
    
    if canned_reply is None:
        raise HTTPException(
            status_code=404, detail="Canned reply not found"
        )
    
    # Make sure the agent belongs to the workspace of the canned reply
    if current_agent.workspace_id != canned_reply.workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    canned_reply = update(
        db=db, db_obj=canned_reply, obj_in=canned_reply_in
    )
    
    return canned_reply


@router.delete("/{canned_reply_id}")
def delete_canned_reply(
    *,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_agent),
    canned_reply_id: int,
) -> Any:
    """Delete canned reply."""
    # Only admins can delete canned replies
    if current_agent.role != "admin":
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    canned_reply = get_by_id(
        db=db, id=canned_reply_id
    )
    
    if canned_reply is None:
        raise HTTPException(
            status_code=404, detail="Canned reply not found"
        )
    
    # Make sure the agent belongs to the workspace of the canned reply
    if current_agent.workspace_id != canned_reply.workspace_id:
        raise HTTPException(
            status_code=403, detail="INSUFFICIENT_PERMISSIONS"
        )
    
    delete(db=db, db_obj=canned_reply)
    
    return {"message": "Canned reply deleted successfully"}