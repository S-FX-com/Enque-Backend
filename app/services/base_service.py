from typing import Any, Dict, Type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func


class BaseService:
    """
    Generic reusable CRUD helper for SQLAlchemy models that belong to a workspace
    and support an enabled/active flag.

    Sub-classes must provide:
        model (SQLAlchemy model class)
        enabled_field (str) – column name for the enabled boolean field (optional)
    """

    model: Type  # Concrete subclasses must override
    enabled_field: str = "is_active"

    # --------------------------------------------------------------------- #
    # Basic getters
    # --------------------------------------------------------------------- #
    async def get_by_id(self, db: AsyncSession, *, id: int):
        """Fetch a single record by primary key."""
        result = await db.execute(select(self.model).filter(self.model.id == id))
        return result.scalars().first()

    async def get_by_workspace_id(
        self,
        db: AsyncSession,
        *,
        workspace_id: int,
        skip: int = 0,
        limit: int = 100,
    ):
        """Return records for a given workspace with pagination."""
        result = await db.execute(
            select(self.model)
            .filter(self.model.workspace_id == workspace_id)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_enabled_by_workspace_id(
        self,
        db: AsyncSession,
        *,
        workspace_id: int,
        skip: int = 0,
        limit: int = 100,
    ):
        """
        Return enabled/active records for a workspace. If the underlying model
        does not expose the `enabled_field`, fall back to a standard query.
        """
        column = getattr(self.model, self.enabled_field, None)
        if column is None:
            return await self.get_by_workspace_id(
                db,
                workspace_id=workspace_id,
                skip=skip,
                limit=limit,
            )

        result = await db.execute(
            select(self.model)
            .filter(
                self.model.workspace_id == workspace_id,
                column.is_(True),
            )
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    # --------------------------------------------------------------------- #
    # Mutations
    # --------------------------------------------------------------------- #
    async def update(self, db: AsyncSession, *, db_obj, obj_in) -> Any:
        """Patch an existing DB model with fields from a Pydantic schema."""
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, *, db_obj) -> None:
        """Delete a record from the database."""
        await db.delete(db_obj)
        await db.commit()

    # --------------------------------------------------------------------- #
    # Statistics helpers
    # --------------------------------------------------------------------- #
    async def count_by_workspace_id(self, db: AsyncSession, *, workspace_id: int) -> int:
        """Count total records for a workspace."""
        result = await db.execute(
            select(func.count()).select_from(self.model).filter(self.model.workspace_id == workspace_id)
        )
        return result.scalar()

    async def count_enabled_by_workspace_id(
        self,
        db: AsyncSession,
        *,
        workspace_id: int,
    ) -> int:
        """Count enabled/active records for a workspace."""
        column = getattr(self.model, self.enabled_field, None)
        if column is None:
            return 0

        result = await db.execute(
            select(func.count()).select_from(self.model).filter(
                self.model.workspace_id == workspace_id,
                column.is_(True),
            )
        )
        return result.scalar()

    async def get_stats(self, db: AsyncSession, *, workspace_id: int) -> Dict[str, int]:
        """Return {'total_count': X, 'enabled_count': Y} dictionary."""
        return {
            "total_count": await self.count_by_workspace_id(db, workspace_id=workspace_id),
            "enabled_count": await self.count_enabled_by_workspace_id(
                db, workspace_id=workspace_id
            ),
        }
