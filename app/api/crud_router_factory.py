from typing import List, Type, Callable, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.models.agent import Agent  # current_user typing


def create_crud_router(
    *,
    service: Any,
    schema: Type,
    create_schema: Type,
    update_schema: Type,
    model_name: str,
    require_auth: bool = True,
) -> APIRouter:
    """
    Generic CRUD router factory.

    Args:
        service: Service instance that implements
                 create, get_by_id, get_by_workspace_id,
                 update, delete.
        schema: Pydantic response schema.
        create_schema: Pydantic schema for POST.
        update_schema: Pydantic schema for PUT.
        model_name: Human-readable name for errors.
        require_auth: Whether to enforce workspace scoping
                      via current_user dependency.

    Returns:
        fastapi.APIRouter ready to include in your API.
    """
    router = APIRouter()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _workspace_guard(obj_workspace_id: int, current_user: Agent):
        if obj_workspace_id != current_user.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{model_name} does not belong to your workspace.",
            )

    # ------------------------------------------------------------------ #
    # Routes
    # ------------------------------------------------------------------ #
    @router.post("/", response_model=schema, status_code=status.HTTP_201_CREATED)
    def create_item(
        *,
        db: Session = Depends(dependencies.get_db),
        item_in: create_schema,
        current_user: Agent = Depends(dependencies.get_current_active_user)
        if require_auth
        else None,
    ):
        # Ensure workspace consistency (if field exists on the schema)
        if require_auth and hasattr(item_in, "workspace_id"):
            if item_in.workspace_id != current_user.workspace_id:  # type: ignore[attr-defined]
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot create object in another workspace.",
                )

        # Service may optionally accept created_by_agent_id
        kwargs = {"obj_in": item_in}
        if "created_by_agent_id" in service.create.__code__.co_varnames:  # type: ignore[attr-defined]
            kwargs["created_by_agent_id"] = getattr(current_user, "id", None)  # type: ignore[attr-defined]
        obj = service.create(db, **kwargs)  # type: ignore[arg-type]
        return obj

    @router.get("/", response_model=List[schema])
    def list_items(
        db: Session = Depends(dependencies.get_db),
        skip: int = 0,
        limit: int = 100,
        current_user: Agent = Depends(dependencies.get_current_active_user)
        if require_auth
        else None,
    ):
        if require_auth:
            return service.get_by_workspace_id(
                db, workspace_id=current_user.workspace_id, skip=skip, limit=limit  # type: ignore[attr-defined]
            )
        # Fallback (no auth)
        return service.get_by_workspace_id(db, workspace_id=None, skip=skip, limit=limit)  # type: ignore[arg-type]

    @router.get("/{item_id}", response_model=schema)
    def read_item(
        *,
        db: Session = Depends(dependencies.get_db),
        item_id: int,
        current_user: Agent = Depends(dependencies.get_current_active_user)
        if require_auth
        else None,
    ):
        obj = service.get_by_id(db, id=item_id)
        if not obj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{model_name} not found")

        if require_auth:
            _workspace_guard(obj.workspace_id, current_user)  # type: ignore[attr-defined]

        return obj

    @router.put("/{item_id}", response_model=schema)
    def update_item(
        *,
        db: Session = Depends(dependencies.get_db),
        item_id: int,
        item_in: update_schema,
        current_user: Agent = Depends(dependencies.get_current_active_user)
        if require_auth
        else None,
    ):
        obj = service.get_by_id(db, id=item_id)
        if not obj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{model_name} not found")

        if require_auth:
            _workspace_guard(obj.workspace_id, current_user)  # type: ignore[attr-defined]

        updated = service.update(db, db_obj=obj, obj_in=item_in)
        return updated

    @router.delete("/{item_id}", response_model=schema)
    def delete_item(
        *,
        db: Session = Depends(dependencies.get_db),
        item_id: int,
        current_user: Agent = Depends(dependencies.get_current_active_user)
        if require_auth
        else None,
    ):
        obj = service.get_by_id(db, id=item_id)
        if not obj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{model_name} not found")

        if require_auth:
            _workspace_guard(obj.workspace_id, current_user)  # type: ignore[attr-defined]

        service.delete(db, db_obj=obj)
        return obj

    return router