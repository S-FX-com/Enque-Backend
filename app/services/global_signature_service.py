from typing import Any, Dict, Optional, List
from sqlalchemy.orm import Session
from app.models.global_signature import GlobalSignature
from app.schemas.global_signature import GlobalSignatureCreate, GlobalSignatureUpdate


def create(db: Session, *, obj_in: GlobalSignatureCreate) -> GlobalSignature:
    """Create a new global signature in the database."""
    db_obj = GlobalSignature(
        workspace_id=obj_in.workspace_id,
        content=obj_in.content,
        is_enabled=obj_in.is_enabled,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_by_workspace_id(db: Session, *, workspace_id: int) -> Optional[GlobalSignature]:
    """Get global signature by workspace ID."""
    return db.query(GlobalSignature).filter(GlobalSignature.workspace_id == workspace_id).first()


def get_enabled_by_workspace_id(db: Session, *, workspace_id: int) -> Optional[GlobalSignature]:
    """Get enabled global signature by workspace ID."""
    return db.query(GlobalSignature).filter(
        GlobalSignature.workspace_id == workspace_id,
        GlobalSignature.is_enabled == True
    ).first()


def update(
    db: Session, *, db_obj: GlobalSignature, obj_in: GlobalSignatureUpdate
) -> GlobalSignature:
    """Update global signature in the database."""
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def delete(db: Session, *, db_obj: GlobalSignature) -> None:
    """Delete global signature from the database."""
    db.delete(db_obj)
    db.commit() 