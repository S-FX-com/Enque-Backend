from datetime import timedelta
from typing import Any, Optional, Dict

from datetime import timedelta
from typing import Any, Optional, Dict, List # Added List

from fastapi import APIRouter, Depends, HTTPException, status, Request, Header, Query # Added Query
from fastapi.responses import RedirectResponse # Added RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import jwt, JWTError
# Import Workspace model if needed for validation
from app.models.workspace import Workspace

from app.core.config import settings
from app.core.security import create_access_token, verify_password, get_password_hash
from app.database.session import get_db
from app.models.agent import Agent
from app.schemas.token import Token
from app.schemas.agent import Agent as AgentSchema, AgentCreate
from app.api.dependencies import get_current_active_user
# Removed MS Service imports as they are no longer needed here
# from app.services.microsoft_service import MicrosoftGraphService, get_microsoft_service 
import logging # Import logging
# Removed uuid import as it's likely only used for state which is removed
# import uuid 
import json # Added json import
import base64 # Added base64 import

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/login", response_model=Token)
async def login_access_token(
    request: Request,
    db: Session = Depends(get_db), 
    form_data: OAuth2PasswordRequestForm = Depends(),
    # Make header optional again for Swagger UI compatibility
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID") 
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    If X-Workspace-ID header is provided, validates the user belongs to that workspace.
    """
    logger.info(f"Login attempt for user: {form_data.username} with X-Workspace-ID: {x_workspace_id or 'Not Provided'}")
    
    requested_workspace_id: Optional[int] = None
    if x_workspace_id:
        # 1. Validate workspace_id format from header IF provided
        try:
            requested_workspace_id = int(x_workspace_id)
        except ValueError:
            logger.warning(f"Invalid X-Workspace-ID format provided: {x_workspace_id}")
            # Return 400 if header is provided but invalid
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Workspace-ID header format.",
            )

    # 2. Find user by email
    user = db.query(Agent).filter(Agent.email == form_data.username).first()

    # 3. Check if user exists and password is correct (Generic error for security)
    if not user or not verify_password(form_data.password, user.password):
        logger.warning(f"Authentication failed for user: {form_data.username} (User not found or incorrect password)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    logger.info(f"User {user.email} (ID: {user.id}) found with matching password. Belongs to workspace {user.workspace_id}.")

    # 4. CRITICAL: Check workspace ONLY if the header was provided
    if requested_workspace_id is not None and user.workspace_id != requested_workspace_id:
        # Log specifically before raising 403
        logger.error(f"ACCESS DENIED: User {user.email} (Workspace {user.workspace_id}) attempted login via Workspace {requested_workspace_id}. Header provided, but mismatch. Raising 403.")
        # User is authenticated but not authorized for the specific workspace requested via header
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail=f"User not authorized for workspace ID {requested_workspace_id}", # Consider a more user-friendly message?
        )

    # 5. User is valid for this workspace, proceed to generate token
    logger.info(f"User {user.email} successfully authenticated and authorized for workspace {requested_workspace_id}.")
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Prepare user data for the token (ensure it uses the validated workspace_id)
    # The token should contain the workspace_id the user logged into
    extra_data = {
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "workspace_id": user.workspace_id, # user.workspace_id and requested_workspace_id are guaranteed to be the same here
        # Add new fields to token payload
        "job_title": user.job_title,
        "phone_number": user.phone_number,
        "email_signature": user.email_signature # Add email_signature
    }

    token = create_access_token(
        subject=str(user.id), # Ensure subject is string
        expires_delta=access_token_expires,
        extra_data=extra_data
    )
    
    logger.info(f"Token generated successfully for user {user.email} in workspace {user.workspace_id}")
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(access_token_expires.total_seconds()) # Return expires_in in seconds
    }


@router.get("/me", response_model=AgentSchema)
async def get_current_user(
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get currently authenticated user
    """
    return current_user


# --- Rutas de autenticación de Microsoft eliminadas ---


@router.post("/register/agent", response_model=AgentSchema)
async def register_agent(
    user_in: AgentCreate, db: Session = Depends(get_db)
) -> Any:
    """
    Register a new agent (public endpoint for initial registration)
    """
    # Check if email already exists
    user = db.query(Agent).filter(Agent.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Verificar que el workspace_id existe
    from app.models.workspace import Workspace
    workspace = db.query(Workspace).filter(Workspace.id == user_in.workspace_id).first()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workspace with ID {user_in.workspace_id} not found",
        )
    
    # Create new agent with workspace_id
    try:
        user = Agent(
            name=user_in.name,
            email=user_in.email,
            password=get_password_hash(user_in.password),
            role=user_in.role,
            is_active=user_in.is_active,
            workspace_id=user_in.workspace_id  # Añadir el workspace_id
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        return user
    except Exception as e:
        db.rollback()
        # Log de error para diagnóstico
        print(f"Error registrando agente: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating agent: {str(e)}",
        )


@router.post("/verify-token", response_model=Dict[str, Any])
async def verify_token(
    request: Request,
    token: str = Header(..., description="JWT Token to verify")
) -> Dict[str, Any]:
    """
    Verifica y decodifica un token JWT, mostrando toda la información que contiene.
    Este endpoint es útil para depuración y para entender cómo se están generando los tokens.
    """
    try:
        # Decodificar el token sin verificación primero para mostrar todo el contenido
        unverified_payload = jwt.decode(
            token, 
            key="", 
            options={"verify_signature": False}
        )
        
        # Ahora intentar verificar correctamente el token
        verified_payload = None
        try:
            verified_payload = jwt.decode(
                token, 
                key=settings.JWT_SECRET, 
                algorithms=[settings.JWT_ALGORITHM]
            )
        except JWTError as e:
            # No devolvemos error para poder mostrar el contenido no verificado
            pass
        
        # Obtener información del usuario si el token contiene un ID válido
        user_info = None
        if 'sub' in unverified_payload:
            try:
                # Obtener la sesión de base de datos
                db = next(get_db())
                user_id = unverified_payload.get('sub')
                
                # Buscar el usuario en la base de datos
                user = db.query(Agent).filter(Agent.id == user_id).first()
                if user:
                    user_info = {
                        "id": user.id,
                        "name": user.name,
                        "email": user.email,
                        "role": user.role,
                        "workspace_id": user.workspace_id,
                        "is_active": user.is_active
                    }
            except Exception as e:
                user_info = {"error": f"Error fetching user data: {str(e)}"}
        
        return {
            "token": token,
            "unverified_payload": unverified_payload,
            "verified": verified_payload is not None,
            "verified_payload": verified_payload,
            "user_info": user_info
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid token format: {str(e)}"
        )
