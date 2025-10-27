from typing import Any, Dict, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.global_signature import GlobalSignature
from app.schemas.global_signature import GlobalSignatureCreate, GlobalSignatureUpdate


async def create(db: AsyncSession, *, obj_in: GlobalSignatureCreate) -> GlobalSignature:
    """Create a new global signature in the database."""
    db_obj = GlobalSignature(
        workspace_id=obj_in.workspace_id,
        content=obj_in.content,
        is_enabled=obj_in.is_enabled,
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_by_workspace_id(db: AsyncSession, *, workspace_id: int) -> Optional[GlobalSignature]:
    """Get global signature by workspace ID."""
    stmt = select(GlobalSignature).filter(GlobalSignature.workspace_id == workspace_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_enabled_by_workspace_id(db: AsyncSession, *, workspace_id: int) -> Optional[GlobalSignature]:
    """Get enabled global signature by workspace ID."""
    stmt = select(GlobalSignature).filter(
        GlobalSignature.workspace_id == workspace_id,
        GlobalSignature.is_enabled == True
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def update(
    db: AsyncSession, *, db_obj: GlobalSignature, obj_in: GlobalSignatureUpdate
) -> GlobalSignature:
    """Update global signature in the database."""
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def delete(db: AsyncSession, *, db_obj: GlobalSignature) -> None:
    """Delete global signature from the database."""
    await db.delete(db_obj)
    await db.commit()
