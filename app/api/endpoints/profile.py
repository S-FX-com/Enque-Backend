from typing import Any
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.agent import Agent
from app.schemas.agent import Agent as AgentSchema, AgentUpdate
from app.core.security import get_password_hash
from app.services.cache_service import cache_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me", response_model=AgentSchema)
async def read_user_me(
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get current user profile
    """
    return current_user


@router.put("/me", response_model=AgentSchema)
async def update_user_me(
    user_in: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Update current user profile
    """
    # Si se está intentando cambiar el rol, sólo los administradores pueden hacerlo
    if user_in.role is not None and current_user.role != "admin" and user_in.role != current_user.role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to change role",
        )
    
    # Actualizar el usuario
    update_data = user_in.dict(exclude_unset=True)
    
    # Hash de la contraseña si se está actualizando
    if "password" in update_data and update_data["password"]:
        update_data["password"] = get_password_hash(update_data["password"])
    
    for field, value in update_data.items():
        setattr(current_user, field, value)
    
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    
    # Invalidate the user's cache in Redis
    cache_key = f"user_agent:{current_user.id}"
    await cache_service.delete(cache_key)
    logger.info(f"PROFILE UPDATE: User {current_user.id} ({current_user.email}) updated and cache invalidated.")
    
    return current_user
