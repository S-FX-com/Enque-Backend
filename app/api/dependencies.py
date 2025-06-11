from typing import Generator, Optional
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import ValidationError
from sqlalchemy.orm import Session, noload

from app.core.config import settings
from app.database.session import get_db
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.schemas.token import TokenPayload
from app.core.cache import user_cache, create_user_from_cache

# OAuth2 bearer token for authentication
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)


def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> Agent:
    """
    Get the current authenticated user from the token
    Implementa caché para evitar consultas repetitivas durante 5 minutos
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
    
    # INTENTAR OBTENER DESDE CACHÉ PRIMERO
    cached_user_data = user_cache.get(user_id)
    if cached_user_data:
        return create_user_from_cache(cached_user_data)
    
    # SI NO ESTÁ EN CACHÉ, CONSULTAR BASE DE DATOS
    # OPTIMIZACIÓN: Consulta sin relaciones pesadas para mejorar velocidad
    user = db.query(Agent).filter(Agent.id == user_id).options(
        noload(Agent.assigned_tasks),
        noload(Agent.sent_tasks),
        noload(Agent.teams),
        noload(Agent.comments),
        noload(Agent.activities),
        noload(Agent.created_mailboxes),
        noload(Agent.microsoft_tokens),
        noload(Agent.created_canned_replies)
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="User not found",
        )
    
    # GUARDAR EN CACHÉ PARA PRÓXIMAS SOLICITUDES
    user_cache.set(user)
    
    return user


def get_current_active_user(
    current_user: Agent = Depends(get_current_user),
) -> Agent:
    """
    Get the current active user
    """
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def get_current_active_admin(
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


def get_current_active_admin_or_manager(
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


def get_current_workspace(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
) -> Workspace:
    """
    Dependency function that returns the current workspace based on the user's workspace_id
    """
    workspace = db.query(Workspace).filter(Workspace.id == current_user.workspace_id).first()
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
