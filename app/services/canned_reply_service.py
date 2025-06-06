from typing import Any, Dict, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from app.models.canned_reply import CannedReply
from app.schemas.canned_reply import CannedReplyCreate, CannedReplyUpdate


def create(db: Session, *, obj_in: CannedReplyCreate, created_by_agent_id: int) -> CannedReply:
    """Create a new canned reply in the database."""
    db_obj = CannedReply(
        workspace_id=obj_in.workspace_id,
        name=obj_in.name,
        description=obj_in.description,
        content=obj_in.content,
        created_by_agent_id=created_by_agent_id,
        is_enabled=obj_in.is_enabled,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_by_id(db: Session, *, id: int) -> Optional[CannedReply]:
    """Get canned reply by ID."""
    return db.query(CannedReply).filter(CannedReply.id == id).first()


def get_by_workspace_id(
    db: Session, *, workspace_id: int, skip: int = 0, limit: int = 100
) -> List[CannedReply]:
    """Get all canned replies by workspace ID with pagination."""
    return (
        db.query(CannedReply)
        .filter(CannedReply.workspace_id == workspace_id)
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_enabled_by_workspace_id(
    db: Session, *, workspace_id: int, skip: int = 0, limit: int = 100
) -> List[CannedReply]:
    """Get enabled canned replies by workspace ID with pagination."""
    return (
        db.query(CannedReply)
        .filter(
            CannedReply.workspace_id == workspace_id,
            CannedReply.is_enabled == True
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def update(
    db: Session, *, db_obj: CannedReply, obj_in: CannedReplyUpdate
) -> CannedReply:
    """Update canned reply in the database."""
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def delete(db: Session, *, db_obj: CannedReply) -> None:
    """Delete canned reply from the database."""
    db.delete(db_obj)
    db.commit()


def count_by_workspace_id(db: Session, *, workspace_id: int) -> int:
    """Count total canned replies in a workspace."""
    return db.query(CannedReply).filter(CannedReply.workspace_id == workspace_id).count()


def count_enabled_by_workspace_id(db: Session, *, workspace_id: int) -> int:
    """Count enabled canned replies in a workspace."""
    return (
        db.query(CannedReply)
        .filter(
            CannedReply.workspace_id == workspace_id,
            CannedReply.is_enabled == True
        )
        .count()
    )


def get_stats(db: Session, *, workspace_id: int) -> Dict[str, Any]:
    """Get statistics for canned replies in a workspace."""
    total_count = count_by_workspace_id(db=db, workspace_id=workspace_id)
    enabled_count = count_enabled_by_workspace_id(db=db, workspace_id=workspace_id)
    
    return {
        "total_count": total_count,
        "enabled_count": enabled_count,
    }