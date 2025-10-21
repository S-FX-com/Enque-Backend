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
    db: Session = Depends(get_db), 
    form_data: OAuth2PasswordRequestForm = Depends(),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID") 
) -> Any:
    logger.info(f"Login attempt for user: {form_data.username} with X-Workspace-ID: {x_workspace_id or 'Not Provided'}")
    
    if not x_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Workspace-ID header is required for login.",
        )

    try:
        requested_workspace_id = int(x_workspace_id)
    except (ValueError, TypeError):
        logger.warning(f"Invalid X-Workspace-ID format provided: {x_workspace_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Workspace-ID header format.",
        )

    user = db.query(Agent).filter(
        Agent.email == form_data.username,
        Agent.workspace_id == requested_workspace_id
    ).first()
    
    # Verificar contraseña con manejo robusto de errores
    password_valid = False
    try:
        if user:
            password_valid = verify_password(form_data.password, user.password)
            logger.info(f"Password verification result for {form_data.username}: {password_valid}")
    except Exception as pwd_error:
        logger.error(f"Error during password verification for {form_data.username}: {pwd_error}")
        password_valid = False
    
    if not user or not password_valid:
        logger.warning(f"Authentication failed for user: {form_data.username} (User not found or incorrect password)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
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
async def register_agent(user_in: AgentCreate, db: Session = Depends(get_db)) -> Any:
    user = db.query(Agent).filter(
        Agent.email == user_in.email, 
        Agent.workspace_id == user_in.workspace_id
    ).first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Email already registered in workspace {user_in.workspace_id}"
        )
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
@limiter.limit("10/minute")
async def request_password_reset(
    request: Request,
    request_data: AgentPasswordResetRequest, 
    db: Session = Depends(get_db),
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
        agent = db.query(Agent).filter(
            Agent.email == request_data.email, 
            Agent.workspace_id == requested_workspace_id,
            Agent.is_active == True
        ).first()
        logger.info(f"Password reset requested for {request_data.email} in workspace {requested_workspace_id}: {'Found' if agent else 'Not found'}")
    else:
        # Si no se proporciona workspace_id, buscar solo por email (comportamiento original)
        agent = db.query(Agent).filter(Agent.email == request_data.email, Agent.is_active == True).first()
        logger.info(f"Password reset requested for {request_data.email} without workspace restriction: {'Found' if agent else 'Not found'}")
    
    if not agent:
        logger.info(f"Password reset requested for non-existent or inactive email: {request_data.email}")
        return {"message": "If an account with that email exists, a password reset link has been sent."}

    # Get the workspace information to construct the correct reset link
    workspace = db.query(Workspace).filter(Workspace.id == agent.workspace_id).first()
    if not workspace:
        logger.error(f"Workspace not found for agent {agent.email} (workspace_id: {agent.workspace_id})")
        return {"message": "If an account with that email exists, a password reset link has been sent."}

    token = secrets.token_urlsafe(32)
    agent.password_reset_token = token
    agent.password_reset_token_expires_at = datetime.utcnow() + timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
    db.add(agent); db.commit()
    
    # Construct reset link using workspace subdomain, similar to invitation links
    reset_link = f"https://{workspace.subdomain}.enque.cc/reset-password?token={token}"
    
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
@limiter.limit("10/minute")
async def reset_password(request: Request, reset_data: AgentResetPassword, db: Session = Depends(get_db)):
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

@router.post("/microsoft/login", response_model=Token)
@limiter.limit("10/minute")
async def microsoft_login(
    request: Request,
    microsoft_data: AgentMicrosoftLogin, 
    db: Session = Depends(get_db)
) -> Any:
    logger.info(f"Microsoft login attempt for user: {microsoft_data.microsoft_email}")
    workspace_id = microsoft_data.workspace_id
    if not workspace_id:
        workspace = db.query(Workspace).first()
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No workspace available. Please contact support."
            )
        workspace_id = workspace.id
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workspace with ID {workspace_id} not found"
        )
    logger.info(f"🔍 Searching for agent with microsoft_id: {microsoft_data.microsoft_id} in workspace: {workspace_id}")
    agent = db.query(Agent).filter(
        Agent.microsoft_id == microsoft_data.microsoft_id,
        Agent.workspace_id == workspace_id
    ).first()
    agent_any_workspace = db.query(Agent).filter(
        Agent.microsoft_id == microsoft_data.microsoft_id
    ).first()
    
    if agent_any_workspace and agent_any_workspace.workspace_id != workspace_id:
        logger.warning(f"⚠️ Found agent with microsoft_id in different workspace: {agent_any_workspace.workspace_id} (expected: {workspace_id})")
    
    if agent:
        logger.info(f"Existing Microsoft agent found: {agent.email}")
        agent.microsoft_email = microsoft_data.microsoft_email
        agent.microsoft_tenant_id = microsoft_data.microsoft_tenant_id
        agent.microsoft_profile_data = microsoft_data.microsoft_profile_data
        agent.last_login = datetime.utcnow()
        agent.last_login_origin = "Microsoft 365"
        
    else:
        agent = db.query(Agent).filter(
            Agent.email == microsoft_data.microsoft_email,
            Agent.workspace_id == workspace_id
        ).first()
        
        if agent:
            logger.info(f"Linking Microsoft account to existing agent: {agent.email}")
            agent.microsoft_id = microsoft_data.microsoft_id
            agent.microsoft_email = microsoft_data.microsoft_email
            agent.microsoft_tenant_id = microsoft_data.microsoft_tenant_id
            agent.microsoft_profile_data = microsoft_data.microsoft_profile_data
            agent.auth_method = "both"
            agent.last_login = datetime.utcnow()
            agent.last_login_origin = "Microsoft 365"
            
        else:
            logger.info(f"Creating new Microsoft agent: {microsoft_data.microsoft_email}")
            try:
                profile_data = json.loads(microsoft_data.microsoft_profile_data) if microsoft_data.microsoft_profile_data else {}
                display_name = profile_data.get("displayName", microsoft_data.microsoft_email.split("@")[0])
            except:
                display_name = microsoft_data.microsoft_email.split("@")[0]
                
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
        db.commit()
        db.refresh(agent)
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
    db: Session = Depends(get_db)
) -> Any:
    logger.info(f"Linking Microsoft account {microsoft_data.microsoft_email} to agent {current_agent.email}")
    existing_microsoft_agent = db.query(Agent).filter(
        Agent.microsoft_id == microsoft_data.microsoft_id,
        Agent.workspace_id == current_agent.workspace_id,
        Agent.id != current_agent.id
    ).first()
    
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
        db.commit()
        db.refresh(current_agent)
        logger.info(f"Successfully linked Microsoft account to agent {current_agent.email}")
        
        return {
            "message": "Microsoft account linked successfully",
            "auth_method": current_agent.auth_method,
            "microsoft_email": current_agent.microsoft_email
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error linking Microsoft account: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error linking Microsoft account: {str(e)}"
        )



@router.get("/microsoft/auth/url")
async def get_microsoft_auth_url(
    request: Request,
    workspace_id: Optional[int] = Query(None, description="Workspace ID for authentication"),
    db: Session = Depends(get_db)
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
                workspace = db.query(Workspace).filter(Workspace.subdomain == subdomain).first()
                if workspace:
                    workspace_id = workspace.id
            
        # Default workspace if still not found
        if not workspace_id:
            workspace = db.query(Workspace).first()
            if not workspace:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No workspace available"
                )
            workspace_id = workspace.id
            
        # Validate workspace exists
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
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
    db: Session = Depends(get_db)
) -> Any:
    """
    Check available authentication methods for a user by email.
    Returns the auth methods available and whether Microsoft is required.
    """
    logger.info(f"Checking auth methods for email: {email} with X-Workspace-ID: {x_workspace_id or 'Not Provided'}")
    
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
    
    # Search for user
    user = None
    if requested_workspace_id is not None:
        user = db.query(Agent).filter(
            Agent.email == email,
            Agent.workspace_id == requested_workspace_id
        ).first()
        logger.info(f"Searching for user {email} in workspace {requested_workspace_id}: {'Found' if user else 'Not found'}")
    else:
        user = db.query(Agent).filter(Agent.email == email).first()
        logger.info(f"Searching for user {email} without workspace restriction: {'Found' if user else 'Not found'}")
    
    if not user:
        # User not found - return default auth methods (password only)
        logger.info(f"User {email} not found, returning default auth methods")
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
    auth_method = user.auth_method
    has_microsoft = bool(user.microsoft_id and user.microsoft_email)
    has_password = bool(user.password)
    
    auth_methods = []
    if auth_method == "password":
        auth_methods = ["password"]
    elif auth_method == "microsoft":
        auth_methods = ["microsoft"]
    elif auth_method == "both":
        auth_methods = ["password", "microsoft"]
    
    requires_microsoft = auth_method == "microsoft"
    can_use_password = auth_method in ["password", "both"] and has_password
    can_use_microsoft = auth_method in ["microsoft", "both"] and has_microsoft
    
    logger.info(f"User {email} found with auth_method: {auth_method}, has_microsoft: {has_microsoft}, has_password: {has_password}")
    
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
