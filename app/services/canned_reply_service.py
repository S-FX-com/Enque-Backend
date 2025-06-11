from typing import Any, Dict, List, Optional, Type

from sqlalchemy.orm import Session

from app.models.canned_reply import CannedReply
from app.schemas.canned_reply import CannedReplyCreate, CannedReplyUpdate
from app.services.base_service import BaseService


class CannedReplyService(BaseService):
    """
    Object-oriented service layer for the CannedReply model.
    Inherits generic CRUD/statistics helpers from BaseService and only
    customises behaviour where needed (the create method in this case).
    """

    # ------------------------------------------------------------------ #
    # Configuration expected by BaseService
    # ------------------------------------------------------------------ #
    model: Type = CannedReply
    enabled_field: str = "is_enabled"

    # ------------------------------------------------------------------ #
    # Custom create
    # ------------------------------------------------------------------ #
    def create(
        self,
        db: Session,
        *,
        obj_in: CannedReplyCreate,
        created_by_agent_id: int,
    ) -> CannedReply:
        """
        Create a new canned reply in the database.

        Args:
            db: SQLAlchemy session.
            obj_in: Pydantic schema with the canned-reply data.
            created_by_agent_id: ID of the agent creating the reply.

        Returns:
            The newly created CannedReply SQLAlchemy instance.
        """
        db_obj = self.model(
            workspace_id=obj_in.workspace_id,
            name=obj_in.name,
            description=obj_in.description,
            content=obj_in.content,
            is_enabled=obj_in.is_enabled,
            created_by_agent_id=created_by_agent_id,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj


# Singleton instance used by functional wrappers for backward-compatibility
canned_reply_service = CannedReplyService()

# ---------------------------------------------------------------------- #
# Backward-compatible functional API
# ---------------------------------------------------------------------- #
def create(
    db: Session,
    *,
    obj_in: CannedReplyCreate,
    created_by_agent_id: int,
) -> CannedReply:
    return canned_reply_service.create(
        db, obj_in=obj_in, created_by_agent_id=created_by_agent_id
    )


def get_by_id(db: Session, *, id: int) -> Optional[CannedReply]:
    return canned_reply_service.get_by_id(db, id=id)


def get_by_workspace_id(
    db: Session, *, workspace_id: int, skip: int = 0, limit: int = 100
) -> List[CannedReply]:
    return canned_reply_service.get_by_workspace_id(
        db, workspace_id=workspace_id, skip=skip, limit=limit
    )


def get_enabled_by_workspace_id(
    db: Session, *, workspace_id: int, skip: int = 0, limit: int = 100
) -> List[CannedReply]:
    return canned_reply_service.get_enabled_by_workspace_id(
        db, workspace_id=workspace_id, skip=skip, limit=limit
    )


def update(
    db: Session,
    *,
    db_obj: CannedReply,
    obj_in: CannedReplyUpdate,
) -> CannedReply:
    return canned_reply_service.update(db, db_obj=db_obj, obj_in=obj_in)


def delete(db: Session, *, db_obj: CannedReply) -> None:
    canned_reply_service.delete(db, db_obj=db_obj)


def count_by_workspace_id(db: Session, *, workspace_id: int) -> int:
    return canned_reply_service.count_by_workspace_id(
        db, workspace_id=workspace_id
    )


def count_enabled_by_workspace_id(db: Session, *, workspace_id: int) -> int:
    return canned_reply_service.count_enabled_by_workspace_id(
        db, workspace_id=workspace_id
    )


def get_stats(db: Session, *, workspace_id: int) -> Dict[str, Any]:
    return canned_reply_service.get_stats(db, workspace_id=workspace_id)