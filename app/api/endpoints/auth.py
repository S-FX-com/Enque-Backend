from datetime import datetime, timedelta 
from typing import Any, Optional, Dict, List 

from fastapi import APIRouter, Depends, HTTPException, status, Request, Header, Query 
from fastapi.responses import RedirectResponse 
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload 
from jose import jwt, JWTError
from app.models.workspace import Workspace

from app.core.config import settings
from app.core.security import create_access_token, verify_password, get_password_hash
from app.database.session import get_db
from app.models.agent import Agent
from app.models.microsoft import MailboxConnection, MicrosoftToken 
from app.services.microsoft_service import MicrosoftGraphService 
import secrets 
from app.schemas.token import Token
from app.schemas.agent import Agent as AgentSchema, AgentCreate, AgentPasswordResetRequest, AgentResetPassword 
from app.api.dependencies import get_current_active_user
from app.services.email_service import send_password_reset_email 
import logging 
import json 
import base64 

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/login", response_model=Token)
async def login_access_token(
    request: Request,
    db: Session = Depends(get_db), 
    form_data: OAuth2PasswordRequestForm = Depends(),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID") 
) -> Any:
    logger.info(f"Login attempt for user: {form_data.username} with X-Workspace-ID: {x_workspace_id or 'Not Provided'}")
    requested_workspace_id: Optional[int] = None
    if x_workspace_id:
        try:
            requested_workspace_id = int(x_workspace_id)
        except ValueError:
            logger.warning(f"Invalid X-Workspace-ID format provided: {x_workspace_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Workspace-ID header format.",
            )
    user = db.query(Agent).filter(Agent.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password):
        logger.warning(f"Authentication failed for user: {form_data.username} (User not found or incorrect password)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logger.info(f"User {user.email} (ID: {user.id}) found with matching password. Belongs to workspace {user.workspace_id}.")
    if requested_workspace_id is not None and user.workspace_id != requested_workspace_id:
        logger.error(f"ACCESS DENIED: User {user.email} (Workspace {user.workspace_id}) attempted login via Workspace {requested_workspace_id}. Header provided, but mismatch. Raising 403.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail=f"User not authorized for workspace ID {requested_workspace_id}",
        )
    logger.info(f"User {user.email} successfully authenticated and authorized for workspace {user.workspace_id}.")
    
    user.last_login = datetime.utcnow()
    origin = None

    origin_header = request.headers.get("origin")
    if origin_header:
        origin = origin_header
        logger.info(f"Setting origin from header for user {user.email}: {origin}")
    elif request.headers.get("host"):
        scheme = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("host")
        origin = f"{scheme}://{host}"
        logger.info(f"Constructed origin from headers for user {user.email}: {origin}")
    elif request.headers.get("referer"):
        origin = request.headers.get("referer")
        logger.info(f"Using referer as origin for user {user.email}: {origin}")
    if origin:
        user.last_login_origin = origin
    
    db.add(user)
    db.commit()
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    workspace_id_str = str(user.workspace_id)
    token_payload = {
        "role": user.role,
        "workspace_id": workspace_id_str,
        "name": user.name,
        "email": user.email
    }
    access_token = create_access_token(
        subject=str(user.id),
        extra_data=token_payload,
        expires_delta=access_token_expires,
    )
    logger.info(f"Generated token for user {user.email} (ID: {user.id}, Workspace: {workspace_id_str})")
    return {
        "access_token": access_token,
        "token_type": "bearer",
    }

@router.get("/me", response_model=AgentSchema)
async def get_current_user(current_user: Agent = Depends(get_current_active_user)) -> Any:
    return current_user

@router.post("/register/agent", response_model=AgentSchema)
async def register_agent(user_in: AgentCreate, db: Session = Depends(get_db)) -> Any:
    user = db.query(Agent).filter(Agent.email == user_in.email).first()
    if user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    workspace = db.query(Workspace).filter(Workspace.id == user_in.workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Workspace with ID {user_in.workspace_id} not found")
    try:
        user = Agent(
            name=user_in.name, email=user_in.email,
            password=get_password_hash(user_in.password),
            role=user_in.role, is_active=user_in.is_active,
            workspace_id=user_in.workspace_id
        )
        db.add(user); db.commit(); db.refresh(user)
        return user
    except Exception as e:
        db.rollback()
        logger.error(f"Error registrando agente: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating agent: {str(e)}")

@router.post("/verify-token", response_model=Dict[str, Any])
async def verify_token(request: Request, token: str = Header(..., description="JWT Token to verify")) -> Dict[str, Any]:
    try:
        unverified_payload = jwt.decode(token, key="", options={"verify_signature": False})
        verified_payload = None
        try:
            verified_payload = jwt.decode(token, key=settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except JWTError: pass
        user_info = None
        if 'sub' in unverified_payload:
            try:
                db_session = next(get_db())
                user_id = unverified_payload.get('sub')
                user = db_session.query(Agent).filter(Agent.id == user_id).first()
                if user:
                    user_info = {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "workspace_id": user.workspace_id, "is_active": user.is_active}
            except Exception as e: user_info = {"error": f"Error fetching user data: {str(e)}"}
        return {"token": token, "unverified_payload": unverified_payload, "verified": verified_payload is not None, "verified_payload": verified_payload, "user_info": user_info}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid token format: {str(e)}")

@router.post("/request-password-reset")
async def request_password_reset(request_data: AgentPasswordResetRequest, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.email == request_data.email, Agent.is_active == True).first()
    if not agent:
        logger.info(f"Password reset requested for non-existent or inactive email: {request_data.email}")
        return {"message": "If an account with that email exists, a password reset link has been sent."}

    token = secrets.token_urlsafe(32)
    agent.password_reset_token = token
    agent.password_reset_token_expires_at = datetime.utcnow() + timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
    db.add(agent); db.commit()
    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    admin_sender_mailbox_info = db.query(Agent, MailboxConnection, MicrosoftToken)\
        .join(MailboxConnection, Agent.id == MailboxConnection.created_by_agent_id)\
        .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
        .filter(
            Agent.workspace_id == agent.workspace_id,
            Agent.role.in_(['admin', 'manager']),
            MailboxConnection.is_active == True,
            MicrosoftToken.access_token.isnot(None)
        ).order_by(Agent.role.desc()).first()

    if not admin_sender_mailbox_info:
        logger.error(f"No admin/manager with an active and tokenized mailbox found in workspace {agent.workspace_id} to send password reset for {agent.email}.")
        return {"message": "If an account with that email exists and a configured sender is available, a password reset link has been sent."}

    admin_sender, admin_mailbox_connection, ms_token = admin_sender_mailbox_info
    
    graph_service = MicrosoftGraphService(db=db)
    current_access_token = ms_token.access_token
    if ms_token.expires_at < datetime.utcnow():
        try:
            logger.info(f"Token for admin mailbox {admin_mailbox_connection.email} expired, attempting refresh.")
            refreshed_ms_token = await graph_service.refresh_token_async(ms_token)
            current_access_token = refreshed_ms_token.access_token
        except HTTPException as e:
            logger.error(f"Failed to refresh token for admin mailbox {admin_mailbox_connection.email}: {e.detail}")
            return {"message": "If an account with that email exists and a configured sender is available, a password reset link has been sent."}
    
    email_sent = await send_password_reset_email(
        db=db, to_email=agent.email, agent_name=agent.name, reset_link=reset_link,
        sender_mailbox_email=admin_mailbox_connection.email, user_access_token=current_access_token
    )
    if not email_sent:
        logger.error(f"Failed to send password reset email to {agent.email} from {admin_mailbox_connection.email}")
    
    logger.info(f"Password reset email initiated for {agent.email} from {admin_mailbox_connection.email}. Token: {token}")
    return {"message": "If an account with that email exists, a password reset link has been sent."}

@router.post("/reset-password", response_model=Token)
async def reset_password(reset_data: AgentResetPassword, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.password_reset_token == reset_data.token).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset token.")
    if not agent.is_active:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account is not active. Please contact support.")
    if agent.password_reset_token_expires_at and agent.password_reset_token_expires_at < datetime.utcnow():
        agent.password_reset_token = None
        agent.password_reset_token_expires_at = None
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset token has expired. Please request a new one.")

    agent.password = get_password_hash(reset_data.new_password)
    agent.password_reset_token = None
    agent.password_reset_token_expires_at = None
    db.add(agent); db.commit(); db.refresh(agent)
    logger.info(f"Password successfully reset for agent {agent.email} (ID: {agent.id})")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {"role": agent.role, "workspace_id": str(agent.workspace_id), "name": agent.name, "email": agent.email}
    access_token = create_access_token(subject=str(agent.id), extra_data=token_payload, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}
