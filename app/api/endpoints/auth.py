from datetime import datetime, timedelta 
from typing import Any, Optional, Dict, List 
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header, Query 
from fastapi.responses import RedirectResponse 
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
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
from app.schemas.agent import Agent as AgentSchema, AgentCreate, AgentPasswordResetRequest, AgentResetPassword, AgentMicrosoftLogin, AgentMicrosoftLinkRequest 
from app.api.dependencies import get_current_active_user
from app.services.email_service import send_password_reset_email 
import logging 
import json 
import base64 
from app.core.rate_limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login_access_token(
    request: Request,
    db: AsyncSession = Depends(get_db), 
    form_data: OAuth2PasswordRequestForm = Depends(),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID") 
) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    logger.info(f"🔑 LOGIN ATTEMPT - User: {form_data.username}, X-Workspace-ID: {x_workspace_id or 'Not Provided'}, IP: {client_ip}, User-Agent: {user_agent[:100]}")
    
    # Manejar workspace ID - puede ser proporcionado o inferido
    requested_workspace_id = None
    user = None
    
    if x_workspace_id:
        try:
            requested_workspace_id = int(x_workspace_id)
            logger.debug(f"🔍 LOGIN DEBUG - Parsed workspace ID: {requested_workspace_id} for user: {form_data.username}")
            
            # Buscar usuario en el workspace especificado
            result = await db.execute(
                select(Agent).filter(
                    Agent.email == form_data.username,
                    Agent.workspace_id == requested_workspace_id
                )
            )
            user = result.scalars().first()
            
            if user:
                logger.info(f"� LOGIN DEBUG - User {form_data.username} found in specified workspace {requested_workspace_id}")
            else:
                logger.warning(f"❌ LOGIN WARNING - User {form_data.username} not found in workspace {requested_workspace_id}")
                
        except (ValueError, TypeError):
            logger.warning(f"⚠️ LOGIN WARNING - Invalid X-Workspace-ID format '{x_workspace_id}' for user: {form_data.username}, IP: {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Workspace-ID header format.",
            )
    else:
        # No X-Workspace-ID proporcionado - buscar usuario en todos los workspaces
        logger.info(f"🔍 LOGIN DEBUG - No X-Workspace-ID provided, searching for {form_data.username} in all workspaces")
        result = await db.execute(select(Agent).filter(Agent.email == form_data.username))
        users_found = result.scalars().all()
        
        if len(users_found) == 0:
            logger.warning(f"❌ LOGIN WARNING - User {form_data.username} not found in any workspace")
        elif len(users_found) == 1:
            user = users_found[0]
            requested_workspace_id = user.workspace_id
            logger.info(f"✅ LOGIN DEBUG - User {form_data.username} found in single workspace {requested_workspace_id}")
        else:
            # Usuario existe en múltiples workspaces - requerir X-Workspace-ID
            workspace_ids = [u.workspace_id for u in users_found]
            logger.warning(f"⚠️ LOGIN WARNING - User {form_data.username} exists in multiple workspaces {workspace_ids}, X-Workspace-ID required")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User exists in multiple workspaces. X-Workspace-ID header is required to specify which workspace to authenticate against.",
            )
    
    if user:
        logger.info(f"👤 LOGIN DEBUG - User {form_data.username} (ID: {user.id}) found with auth_method: {user.auth_method}, has_password: {bool(user.password)}, workspace_id: {user.workspace_id}")
    else:
        logger.warning(f"❌ LOGIN WARNING - User {form_data.username} not found")
    
    # Verificar contraseña con manejo robusto de errores
    password_valid = False
    try:
        if user:
            if not user.password:
                logger.warning(f"⚠️ LOGIN WARNING - User {form_data.username} has no password set (auth_method: {user.auth_method})")
                password_valid = False
            else:
                password_valid = verify_password(form_data.password, user.password)
                logger.info(f"🔐 LOGIN DEBUG - Password verification result for {form_data.username}: {password_valid}")
        else:
            logger.debug(f"🔍 LOGIN DEBUG - Skipping password verification - user not found")
    except Exception as pwd_error:
        logger.error(f"💥 LOGIN ERROR - Error during password verification for {form_data.username}: {pwd_error}")
        password_valid = False
    
    if not user or not password_valid:
        auth_failure_reason = "User not found" if not user else "Incorrect password"
        logger.warning(f"❌ LOGIN FAILED - Authentication failed for user: {form_data.username} - Reason: {auth_failure_reason}, IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.info(f"✅ LOGIN SUCCESS - User {user.email} (ID: {user.id}) authenticated successfully. Workspace: {user.workspace_id}, Auth method: {user.auth_method}")
    logger.info(f"🔐 LOGIN SUCCESS - User {user.email} successfully authenticated and authorized for workspace {user.workspace_id}")
    
    user.last_login = datetime.utcnow()
    origin = None

    origin_header = request.headers.get("origin")
    if origin_header:
        origin = origin_header
        logger.info(f"🌐 LOGIN DEBUG - Setting origin from header for user {user.email}: {origin}")
    else:
        logger.debug(f"🌐 LOGIN DEBUG - No origin header found for user {user.email}")

    user.last_login_origin = origin
    db.add(user)
    await db.commit()
    
    logger.debug(f"🔑 LOGIN DEBUG - Generating token for user {user.email} (ID: {user.id}, Workspace: {user.workspace_id})")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {
        "role": user.role,
        "workspace_id": str(user.workspace_id),
        "name": user.name,
        "email": user.email,
        "auth_method": user.auth_method
    }
    access_token = create_access_token(
        subject=str(user.id),
        extra_data=token_payload,
        expires_delta=access_token_expires
    )
    logger.info(f"🎫 LOGIN SUCCESS - Generated token for user {user.email} (ID: {user.id}, Workspace: {user.workspace_id})")
    return {"access_token": access_token, "token_type": "bearer"}
    
    logger.info(f"User {user.email} (ID: {user.id}) found with matching password. Belongs to workspace {user.workspace_id}.")
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
async def register_agent(user_in: AgentCreate, db: AsyncSession = Depends(get_db)) -> Any:
    result = await db.execute(
        select(Agent).filter(
            Agent.email == user_in.email,
            Agent.workspace_id == user_in.workspace_id
        )
    )
    user = result.scalars().first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Email already registered in workspace {user_in.workspace_id}"
        )
    result = await db.execute(select(Workspace).filter(Workspace.id == user_in.workspace_id))
    workspace = result.scalars().first()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Workspace with ID {user_in.workspace_id} not found")
    try:
        user = Agent(
            name=user_in.name, email=user_in.email,
            password=get_password_hash(user_in.password),
            role=user_in.role, is_active=user_in.is_active,
            workspace_id=user_in.workspace_id
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
    except Exception as e:
        await db.rollback()
        logger.error(f"Error registrando agente: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating agent: {str(e)}")

@router.post("/verify-token", response_model=Dict[str, Any])
async def verify_token(request: Request, db: AsyncSession = Depends(get_db), token: str = Header(..., description="JWT Token to verify")) -> Dict[str, Any]:
    try:
        unverified_payload = jwt.decode(token, key="", options={"verify_signature": False})
        verified_payload = None
        try:
            verified_payload = jwt.decode(token, key=settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except JWTError: pass
        user_info = None
        if 'sub' in unverified_payload:
            try:
                user_id = unverified_payload.get('sub')
                result = await db.execute(select(Agent).filter(Agent.id == user_id))
                user = result.scalars().first()
                if user:
                    user_info = {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "workspace_id": user.workspace_id, "is_active": user.is_active}
            except Exception as e: user_info = {"error": f"Error fetching user data: {str(e)}"}
        return {"token": token, "unverified_payload": unverified_payload, "verified": verified_payload is not None, "verified_payload": verified_payload, "user_info": user_info}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid token format: {str(e)}")

@router.post("/request-password-reset")
@limiter.limit("10/minute")
async def request_password_reset(
    request: Request,
    request_data: AgentPasswordResetRequest, 
    db: AsyncSession = Depends(get_db),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID")
):
    requested_workspace_id: Optional[int] = None
    if x_workspace_id:
        try:
            requested_workspace_id = int(x_workspace_id)
        except ValueError:
            logger.warning(f"Invalid X-Workspace-ID format provided in password reset: {x_workspace_id}")
            return {"message": "If an account with that email exists, a password reset link has been sent."}
    
    # Buscar el agente en el workspace específico si se proporciona
    if requested_workspace_id is not None:
        result = await db.execute(
            select(Agent).filter(
                Agent.email == request_data.email,
                Agent.workspace_id == requested_workspace_id,
                Agent.is_active == True
            )
        )
        agent = result.scalars().first()
        logger.info(f"Password reset requested for {request_data.email} in workspace {requested_workspace_id}: {'Found' if agent else 'Not found'}")
    else:
        # Si no se proporciona workspace_id, buscar solo por email (comportamiento original)
        result = await db.execute(select(Agent).filter(Agent.email == request_data.email, Agent.is_active == True))
        agent = result.scalars().first()
        logger.info(f"Password reset requested for {request_data.email} without workspace restriction: {'Found' if agent else 'Not found'}")
    
    if not agent:
        logger.info(f"Password reset requested for non-existent or inactive email: {request_data.email}")
        return {"message": "If an account with that email exists, a password reset link has been sent."}

    # Get the workspace information to construct the correct reset link
    result = await db.execute(select(Workspace).filter(Workspace.id == agent.workspace_id))
    workspace = result.scalars().first()
    if not workspace:
        logger.error(f"Workspace not found for agent {agent.email} (workspace_id: {agent.workspace_id})")
        return {"message": "If an account with that email exists, a password reset link has been sent."}

    token = secrets.token_urlsafe(32)
    agent.password_reset_token = token
    agent.password_reset_token_expires_at = datetime.utcnow() + timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
    db.add(agent)
    await db.commit()
    
    # Construct reset link using workspace subdomain, similar to invitation links
    reset_link = f"https://{workspace.subdomain}.enque.cc/reset-password?token={token}"
    
    result = await db.execute(
        select(Agent, MailboxConnection, MicrosoftToken)
        .join(MailboxConnection, Agent.id == MailboxConnection.created_by_agent_id)
        .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)
        .filter(
            Agent.workspace_id == agent.workspace_id,
            Agent.role.in_(['admin', 'manager']),
            MailboxConnection.is_active == True,
            MicrosoftToken.access_token.isnot(None)
        ).order_by(Agent.role.desc())
    )
    admin_sender_mailbox_info = result.first()

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
@limiter.limit("10/minute")
async def reset_password(request: Request, reset_data: AgentResetPassword, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).filter(Agent.password_reset_token == reset_data.token))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset token.")
    if not agent.is_active:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account is not active. Please contact support.")
    if agent.password_reset_token_expires_at and agent.password_reset_token_expires_at < datetime.utcnow():
        agent.password_reset_token = None
        agent.password_reset_token_expires_at = None
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset token has expired. Please request a new one.")

    agent.password = get_password_hash(reset_data.new_password)
    agent.password_reset_token = None
    agent.password_reset_token_expires_at = None
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    logger.info(f"Password successfully reset for agent {agent.email} (ID: {agent.id})")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {"role": agent.role, "workspace_id": str(agent.workspace_id), "name": agent.name, "email": agent.email}
    access_token = create_access_token(subject=str(agent.id), extra_data=token_payload, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/microsoft/login", response_model=Token)
@limiter.limit("10/minute")
async def microsoft_login(
    request: Request,
    microsoft_data: AgentMicrosoftLogin, 
    db: AsyncSession = Depends(get_db)
) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    logger.info(f"🔑 MICROSOFT LOGIN ATTEMPT - User: {microsoft_data.microsoft_email}, Workspace ID: {microsoft_data.workspace_id}, IP: {client_ip}, User-Agent: {user_agent[:100]}")
    
    workspace_id = microsoft_data.workspace_id
    if not workspace_id:
        logger.error(f"❌ MICROSOFT LOGIN FAILED - Missing workspace_id for user: {microsoft_data.microsoft_email}, IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace ID is required for Microsoft login. Please specify the workspace."
        )
    
    logger.debug(f"🔍 MICROSOFT LOGIN DEBUG - Validating workspace {workspace_id}")
    result = await db.execute(select(Workspace).filter(Workspace.id == workspace_id))
    workspace = result.scalars().first()
    if not workspace:
        logger.error(f"❌ MICROSOFT LOGIN FAILED - Workspace {workspace_id} not found for user: {microsoft_data.microsoft_email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workspace with ID {workspace_id} not found"
        )
    
    logger.info(f"🔍 MICROSOFT LOGIN DEBUG - Searching for agent with microsoft_id: {microsoft_data.microsoft_id} in workspace: {workspace_id}")
    result = await db.execute(
        select(Agent).filter(
            Agent.microsoft_id == microsoft_data.microsoft_id,
            Agent.workspace_id == workspace_id
        )
    )
    agent = result.scalars().first()
    
    # También buscar en otros workspaces para debugging
    result = await db.execute(select(Agent).filter(Agent.microsoft_id == microsoft_data.microsoft_id))
    agent_any_workspace = result.scalars().first()
    
    if agent_any_workspace and agent_any_workspace.workspace_id != workspace_id:
        logger.warning(f"⚠️ MICROSOFT LOGIN WARNING - Found agent with microsoft_id {microsoft_data.microsoft_id} in different workspace: {agent_any_workspace.workspace_id} (expected: {workspace_id})")
    
    if agent:
        logger.info(f"✅ MICROSOFT LOGIN SUCCESS - Existing Microsoft agent found: {agent.email} (ID: {agent.id}, Workspace: {agent.workspace_id})")
        agent.microsoft_email = microsoft_data.microsoft_email
        agent.microsoft_tenant_id = microsoft_data.microsoft_tenant_id
        agent.microsoft_profile_data = microsoft_data.microsoft_profile_data
        agent.last_login = datetime.utcnow()
        agent.last_login_origin = "Microsoft 365"
        
    else:
        logger.debug(f"🔍 MICROSOFT LOGIN DEBUG - Agent not found by microsoft_id, searching by email: {microsoft_data.microsoft_email}")
        result = await db.execute(
            select(Agent).filter(
                Agent.email == microsoft_data.microsoft_email,
                Agent.workspace_id == workspace_id
            )
        )
        agent = result.scalars().first()
        
        if agent:
            logger.info(f"🔗 MICROSOFT LOGIN LINK - Linking Microsoft account to existing agent: {agent.email} (ID: {agent.id})")
            agent.microsoft_id = microsoft_data.microsoft_id
            agent.microsoft_email = microsoft_data.microsoft_email
            agent.microsoft_tenant_id = microsoft_data.microsoft_tenant_id
            agent.microsoft_profile_data = microsoft_data.microsoft_profile_data
            agent.auth_method = "both"
            agent.last_login = datetime.utcnow()
            agent.last_login_origin = "Microsoft 365"
            
        else:
            logger.info(f"🆕 MICROSOFT LOGIN CREATE - Creating new Microsoft agent: {microsoft_data.microsoft_email} in workspace {workspace_id}")
            try:
                profile_data = json.loads(microsoft_data.microsoft_profile_data) if microsoft_data.microsoft_profile_data else {}
                display_name = profile_data.get("displayName", microsoft_data.microsoft_email.split("@")[0])
                logger.debug(f"🔍 MICROSOFT LOGIN DEBUG - Extracted display name: {display_name} for user: {microsoft_data.microsoft_email}")
            except json.JSONDecodeError:
                display_name = microsoft_data.microsoft_email.split("@")[0]
                logger.warning(f"⚠️ MICROSOFT LOGIN WARNING - Failed to parse profile data for {microsoft_data.microsoft_email}, using fallback display name: {display_name}")
                
            agent = Agent(
                name=display_name,
                email=microsoft_data.microsoft_email,
                password=None, 
                role="agent",
                auth_method="microsoft",
                microsoft_id=microsoft_data.microsoft_id,
                microsoft_email=microsoft_data.microsoft_email,
                microsoft_tenant_id=microsoft_data.microsoft_tenant_id,
                microsoft_profile_data=microsoft_data.microsoft_profile_data,
                workspace_id=workspace_id,
                is_active=True,
                last_login=datetime.utcnow(),
                last_login_origin="Microsoft 365"
            )
            db.add(agent)
    
    try:
        await db.commit()
        await db.refresh(agent)
        logger.info(f"Microsoft authentication successful for agent {agent.email} (ID: {agent.id})")
        
        # Extract and save Microsoft 365 avatar if available
        try:
            from app.services.microsoft_service import MicrosoftGraphService
            
            # Check if agent doesn't have an avatar or if it's a new Microsoft user
            if not agent.avatar_url:
                logger.info(f"🔍 Attempting to download Microsoft 365 avatar for agent {agent.id}")
                microsoft_service = MicrosoftGraphService(db)
                
                # Get the user's profile photo from Microsoft Graph API
                photo_bytes = microsoft_service._get_user_profile_photo(microsoft_data.access_token)
                
                if photo_bytes:
                    logger.info(f"📸 Profile photo found ({len(photo_bytes)} bytes), uploading to S3...")
                    avatar_url = microsoft_service._upload_avatar_to_s3(photo_bytes, agent.id)
                    
                    if avatar_url:
                        # Update agent's avatar URL
                        agent.avatar_url = avatar_url
                        db.commit()
                        
                        # Invalidate cache
                        from app.core.cache import user_cache
                        user_cache.delete(agent.id)
                        
                        logger.info(f"✅ Successfully extracted and saved Microsoft 365 avatar for agent {agent.id}: {avatar_url}")
                    else:
                        logger.warning(f"❌ Failed to upload avatar to S3 for agent {agent.id}")
                else:
                    logger.info(f"📷 No profile photo available in Microsoft 365 for agent {agent.id}")
                    
        except Exception as avatar_error:
            logger.error(f"❌ Error extracting Microsoft 365 avatar for agent {agent.id}: {str(avatar_error)}")
            # Don't fail the login process if avatar extraction fails
            pass
        
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        token_payload = {
            "role": agent.role,
            "workspace_id": str(agent.workspace_id),
            "name": agent.name,
            "email": agent.email,
            "auth_method": agent.auth_method
        }
        access_token = create_access_token(
            subject=str(agent.id),
            extra_data=token_payload,
            expires_delta=access_token_expires,
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error during Microsoft authentication: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing Microsoft authentication: {str(e)}"
        )

@router.post("/microsoft/link")
async def link_microsoft_account(
    microsoft_data: AgentMicrosoftLinkRequest,
    current_agent: Agent = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    logger.info(f"Linking Microsoft account {microsoft_data.microsoft_email} to agent {current_agent.email}")
    result = await db.execute(
        select(Agent).filter(
            Agent.microsoft_id == microsoft_data.microsoft_id,
            Agent.workspace_id == current_agent.workspace_id,
            Agent.id != current_agent.id
        )
    )
    existing_microsoft_agent = result.scalars().first()
    
    if existing_microsoft_agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This Microsoft account is already linked to another agent in this workspace"
        )
    current_agent.microsoft_id = microsoft_data.microsoft_id
    current_agent.microsoft_email = microsoft_data.microsoft_email
    current_agent.microsoft_tenant_id = microsoft_data.microsoft_tenant_id
    current_agent.microsoft_profile_data = microsoft_data.microsoft_profile_data
    if current_agent.auth_method == "password":
        current_agent.auth_method = "both"
    elif current_agent.auth_method == "microsoft":
        pass
    
    try:
        await db.commit()
        await db.refresh(current_agent)
        logger.info(f"Successfully linked Microsoft account to agent {current_agent.email}")
        
        return {
            "message": "Microsoft account linked successfully",
            "auth_method": current_agent.auth_method,
            "microsoft_email": current_agent.microsoft_email
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error linking Microsoft account: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error linking Microsoft account: {str(e)}"
        )



@router.get("/microsoft/auth/url")
async def get_microsoft_auth_url(
    request: Request,
    workspace_id: Optional[int] = Query(None, description="Workspace ID for authentication"),
    db: AsyncSession = Depends(get_db)
):
    try:
        # Get original hostname from referer first
        original_hostname = None
        referer = request.headers.get("referer", "")
        if referer:
            from urllib.parse import urlparse
            parsed = urlparse(referer)
            original_hostname = parsed.netloc

        # Determine workspace from hostname if not provided
        if not workspace_id and original_hostname:
            # Extract subdomain from hostname (e.g., "sfx" from "sfx.enque.cc")
            if original_hostname.endswith('.enque.cc'):
                subdomain = original_hostname.replace('.enque.cc', '')
                result = await db.execute(select(Workspace).filter(Workspace.subdomain == subdomain))
                workspace = result.scalars().first()
                if workspace:
                    workspace_id = workspace.id
            
        # Default workspace if still not found
        if not workspace_id:
            result = await db.execute(select(Workspace))
            workspace = result.scalars().first()
            if not workspace:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No workspace available"
                )
            workspace_id = workspace.id
            
        # Validate workspace exists
        result = await db.execute(select(Workspace).filter(Workspace.id == workspace_id))
        workspace = result.scalars().first()
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Workspace with ID {workspace_id} not found"
            )
        
        state_data = {
            "workspace_id": str(workspace_id),
            "flow": "auth",
            "original_hostname": original_hostname
        }
        state_json_string = json.dumps(state_data)
        base64_state = base64.urlsafe_b64encode(state_json_string.encode()).decode('utf-8')
        base64_state = base64_state.replace('+', '-').replace('/', '_').rstrip('=')
        auth_url_params = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "response_mode": "query",
            "scope": "offline_access User.Read Mail.Read",
            "state": base64_state,
            "prompt": "select_account" 
        }
        
        import urllib.parse
        auth_url_params_encoded = urllib.parse.urlencode(auth_url_params)
        auth_url = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize?{auth_url_params_encoded}"
        
        return {
            "auth_url": auth_url,
            "message": "Authorization URL generated successfully"
        }
        
    except Exception as e:
        logger.error(f"Error generating Microsoft auth URL: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating authorization URL: {str(e)}"
        )

@router.get("/check-auth-methods")
async def check_auth_methods(
    email: str = Query(..., description="Email address to check authentication methods for"),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID"),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Check available authentication methods for a user by email.
    Returns the auth methods available and whether Microsoft is required.
    """
    logger.info(f"🔍 AUTH METHODS CHECK - Email: {email}, X-Workspace-ID: {x_workspace_id or 'Not Provided'}")
    
    requested_workspace_id: Optional[int] = None
    if x_workspace_id:
        try:
            requested_workspace_id = int(x_workspace_id)
            logger.debug(f"🔍 AUTH METHODS DEBUG - Parsed workspace ID: {requested_workspace_id}")
        except ValueError:
            logger.warning(f"⚠️ AUTH METHODS WARNING - Invalid X-Workspace-ID format: {x_workspace_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Workspace-ID header format.",
            )
    
    # Search for user
    user = None
    if requested_workspace_id is not None:
        logger.debug(f"🔍 AUTH METHODS DEBUG - Searching for {email} in workspace {requested_workspace_id}")
        result = await db.execute(
            select(Agent).filter(
                Agent.email == email,
                Agent.workspace_id == requested_workspace_id
            )
        )
        user = result.scalars().first()
        logger.info(f"🔍 AUTH METHODS SEARCH - User {email} in workspace {requested_workspace_id}: {'Found' if user else 'Not found'}")
    else:
        logger.debug(f"🔍 AUTH METHODS DEBUG - Searching for {email} in all workspaces")
        result = await db.execute(select(Agent).filter(Agent.email == email))
        user = result.scalars().first()
        logger.info(f"🔍 AUTH METHODS SEARCH - User {email} without workspace restriction: {'Found' if user else 'Not found'}")
    
    if not user:
        # User not found - return default auth methods (password only)
        logger.info(f"❌ AUTH METHODS WARNING - User {email} not found, returning default auth methods")
        return {
            "email": email,
            "user_exists": False,
            "auth_methods": ["password"],
            "requires_microsoft": False,
            "can_use_password": True,
            "can_use_microsoft": False,
            "message": "User not found, default authentication available"
        }
    
    # User found - analyze their auth method
    logger.info(f"👤 AUTH METHODS SUCCESS - User {email} found: ID={user.id}, Workspace={user.workspace_id}, Auth method={user.auth_method}")
    auth_method = user.auth_method
    has_microsoft = bool(user.microsoft_id and user.microsoft_email)
    has_password = bool(user.password)
    
    logger.debug(f"🔍 AUTH METHODS DEBUG - Has Microsoft: {has_microsoft}, Has Password: {has_password}")
    
    auth_methods = []
    if auth_method == "password":
        logger.debug(f"🔍 AUTH METHODS DEBUG - User {email} configured for password authentication")
        auth_methods = ["password"]
        if has_microsoft:
            auth_methods.append("microsoft")
            logger.debug(f"✅ AUTH METHODS INFO - Microsoft login also available for {email}")
    elif auth_method == "microsoft":
        logger.debug(f"🔍 AUTH METHODS DEBUG - User {email} configured for Microsoft authentication")
        auth_methods = ["microsoft"]
        if has_password:
            auth_methods.append("password")
            logger.debug(f"✅ AUTH METHODS INFO - Password login also available for {email}")
    elif auth_method == "both":
        logger.debug(f"🔍 AUTH METHODS DEBUG - User {email} configured for both authentication methods")
        auth_methods = ["password", "microsoft"]
    else:
        logger.warning(f"⚠️ AUTH METHODS WARNING - User {email} has unknown auth method: {auth_method}")
        # Fallback - try to determine from available data
        if has_password:
            auth_methods.append("password")
        if has_microsoft:
            auth_methods.append("microsoft")
    
    requires_microsoft = auth_method == "microsoft"
    can_use_password = auth_method in ["password", "both"] and has_password
    can_use_microsoft = auth_method in ["microsoft", "both"] and has_microsoft
    
    logger.info(f"✅ AUTH METHODS RESULT - Email: {email}, Methods: {auth_methods}, Requires Microsoft: {requires_microsoft}, Password Available: {can_use_password}, Microsoft Available: {can_use_microsoft}")
    
    return {
        "email": email,
        "user_exists": True,
        "auth_methods": auth_methods,
        "requires_microsoft": requires_microsoft,
        "can_use_password": can_use_password,
        "can_use_microsoft": can_use_microsoft,
        "workspace_id": user.workspace_id,
        "message": f"Authentication methods available for {email}"
    }
