from typing import Any, Dict, Type

from sqlalchemy.orm import Session


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
    def get_by_id(self, db: Session, *, id: int):
        """Fetch a single record by primary key."""
        return db.query(self.model).filter(self.model.id == id).first()

    def get_by_workspace_id(
        self,
        db: Session,
        *,
        workspace_id: int,
        skip: int = 0,
        limit: int = 100,
    ):
        """Return records for a given workspace with pagination."""
        return (
            db.query(self.model)
            .filter(self.model.workspace_id == workspace_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_enabled_by_workspace_id(
        self,
        db: Session,
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
            # Model has no enabled flag – return all
            return self.get_by_workspace_id(
                db,
                workspace_id=workspace_id,
                skip=skip,
                limit=limit,
            )

        return (
            db.query(self.model)
            .filter(
                self.model.workspace_id == workspace_id,
                column.is_(True),
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

    # --------------------------------------------------------------------- #
    # Mutations
    # --------------------------------------------------------------------- #
    def update(self, db: Session, *, db_obj, obj_in) -> Any:
        """Patch an existing DB model with fields from a Pydantic schema."""
        update_data = obj_in.model_dump(exclude_unset=True)  # type: ignore
        for field, value in update_data.items():
            setattr(db_obj, field, value)

        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def delete(self, db: Session, *, db_obj) -> None:
        """Delete a record from the database."""
        db.delete(db_obj)
        db.commit()

    # --------------------------------------------------------------------- #
    # Statistics helpers
    # --------------------------------------------------------------------- #
    def count_by_workspace_id(self, db: Session, *, workspace_id: int) -> int:
        """Count total records for a workspace."""
        return (
            db.query(self.model)
            .filter(self.model.workspace_id == workspace_id)
            .count()
        )

    def count_enabled_by_workspace_id(
        self,
        db: Session,
        *,
        workspace_id: int,
    ) -> int:
        """Count enabled/active records for a workspace."""
        column = getattr(self.model, self.enabled_field, None)
        if column is None:
            return 0

        return (
            db.query(self.model)
            .filter(
                self.model.workspace_id == workspace_id,
                column.is_(True),
            )
            .count()
        )

    def get_stats(self, db: Session, *, workspace_id: int) -> Dict[str, int]:
        """Return {'total_count': X, 'enabled_count': Y} dictionary."""
        return {
            "total_count": self.count_by_workspace_id(db, workspace_id=workspace_id),
            "enabled_count": self.count_enabled_by_workspace_id(
                db, workspace_id=workspace_id
            ),
        }