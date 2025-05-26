from typing import Any, Dict, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from app.models.canned_reply import CannedReply
from app.schemas.canned_reply import CannedReplyCreate, CannedReplyUpdate


def create(db: Session, *, obj_in: CannedReplyCreate, created_by_agent_id: int) -> CannedReply:
    """Create a new canned reply in the database."""
    db_obj = CannedReply(
        workspace_id=obj_in.workspace_id,
        title=obj_in.title,
        content=obj_in.content,
        created_by_agent_id=created_by_agent_id,
        is_enabled=obj_in.is_enabled,
        category=obj_in.category,
        tags=obj_in.tags,
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


def get_by_category(
    db: Session, *, workspace_id: int, category: str, skip: int = 0, limit: int = 100
) -> List[CannedReply]:
    """Get canned replies by workspace ID and category with pagination."""
    return (
        db.query(CannedReply)
        .filter(
            CannedReply.workspace_id == workspace_id,
            CannedReply.category == category,
            CannedReply.is_enabled == True
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def search_by_tags(
    db: Session, *, workspace_id: int, tags: List[str], skip: int = 0, limit: int = 100
) -> List[CannedReply]:
    """Search canned replies by tags within a workspace."""
    query = db.query(CannedReply).filter(
        CannedReply.workspace_id == workspace_id,
        CannedReply.is_enabled == True
    )
    
    # Filter by tags if provided
    if tags:
        for tag in tags:
            query = query.filter(CannedReply.tags.contains([tag]))
    
    return query.offset(skip).limit(limit).all()


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
    
    # Get unique categories
    categories_query = db.query(distinct(CannedReply.category)).filter(
        CannedReply.workspace_id == workspace_id,
        CannedReply.category.isnot(None)
    )
    categories = [cat[0] for cat in categories_query.all()]
    
    # Get unique tags (this is a bit more complex with JSON arrays)
    tags_query = db.query(CannedReply.tags).filter(
        CannedReply.workspace_id == workspace_id,
        CannedReply.tags.isnot(None)
    )
    all_tags = []
    for tag_list in tags_query.all():
        if tag_list[0]:  # Check if tags is not None
            all_tags.extend(tag_list[0])
    
    unique_tags = list(set(all_tags))
    
    return {
        "total_count": total_count,
        "enabled_count": enabled_count,
        "categories": categories,
        "tags": unique_tags
    }