from typing import Generator, Optional
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload
from sqlalchemy import select

from app.core.config import settings
from app.database.session import get_db
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.schemas.token import TokenPayload
from app.services.cache_service import cache_service

# OAuth2 bearer token for authentication
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)


async def get_current_user(
    db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> Agent:
    """
    Get the current authenticated user from the token.
    Implements Redis caching to avoid repetitive DB queries.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Could not validate credentials: {str(e)}",
        )

    if token_data.sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user_id = token_data.sub
    cache_key = f"user_agent:{user_id}"

    # Try to get from Redis cache first
    cached_user = await cache_service.get(cache_key)
    if cached_user:
        # Reconstruct the Agent object from cached dictionary
        agent = Agent(**cached_user)
        return agent

    # If not in cache, query the database
    result = await db.execute(
        select(Agent).filter(Agent.id == user_id).options(
            noload(Agent.assigned_tasks),
            noload(Agent.sent_tasks),
            noload(Agent.teams),
            noload(Agent.comments),
            noload(Agent.activities),
            noload(Agent.created_mailboxes),
            noload(Agent.microsoft_tokens),
            noload(Agent.created_canned_replies)
        )
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Save to cache for subsequent requests
    user_data_for_cache = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "workspace_id": user.workspace_id,
        "is_active": user.is_active,
        "avatar_url": user.avatar_url
    }
    await cache_service.set(cache_key, user_data_for_cache, ttl=300)  # Cache for 5 minutes

    return user


async def get_current_active_user(
    current_user: Agent = Depends(get_current_user),
) -> Agent:
    """
    Get the current active user
    """
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_active_admin(
    current_user: Agent = Depends(get_current_active_user),
) -> Agent:
    """
    Get the current active admin user
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have sufficient privileges",
        )
    return current_user


async def get_current_active_admin_or_manager(
    current_user: Agent = Depends(get_current_active_user),
) -> Agent:
    """
    Get the current active user, ensuring they are an admin or manager.
    """
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have sufficient privileges (Admin or Manager required)",
        )
    return current_user


async def get_current_workspace(
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
) -> Workspace:
    """
    Dependency function that returns the current workspace based on the user's workspace_id
    """
    result = await db.execute(select(Workspace).filter(Workspace.id == current_user.workspace_id))
    workspace = result.scalars().first()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )
    
    return workspace

def check_workspace_access(user: Agent, workspace_id: int) -> None:
    """
    Check if a user has access to a specific workspace.
    """
    if user.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have access to this workspace"
        )
    return None
