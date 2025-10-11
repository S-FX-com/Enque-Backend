from typing import Any, List, Optional
from datetime import datetime, timedelta 
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request 
from fastapi.responses import RedirectResponse 
from sqlalchemy.orm import Session, joinedload
from app.api.dependencies import get_db, get_current_active_user
from app.models.agent import Agent
from app.core.config import settings 
from app.models.user import User 
from app.models.workspace import Workspace 
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailSyncConfig, EmailTicketMapping, MailboxConnection
from app.schemas.microsoft import (
    OAuthRequest, OAuthCallback, TokenResponse, 
    MicrosoftIntegration as MicrosoftIntegrationSchema,
    MicrosoftIntegrationCreate, MicrosoftIntegrationUpdate,
    EmailSyncConfig as EmailSyncConfigSchema,
    EmailSyncConfigCreate, EmailSyncConfigUpdate,
    EmailTicketMapping as EmailTicketMappingSchema,
    MailboxConnection as MailboxConnectionSchema,
    MailboxConnectionUpdate
)
from app.services.microsoft_service import MicrosoftGraphService
from app.core.security import create_access_token # Importar la función para crear tokens
from app.utils.logger import ms_logger as logger
import urllib.parse
import base64 
import json 
from pydantic import BaseModel, Field

router = APIRouter()

@router.get("/signin/auth/url")
async def get_microsoft_signin_auth_url(
    request: Request,
    workspace_id: Optional[int] = Query(None, description="Workspace ID for signin authentication"),
    origin_url: Optional[str] = Query(None, description="Frontend origin URL for redirect"),
    db: Session = Depends(get_db)
):
    """
    Generate Microsoft 365 auth URL for signin (unified login)
    This endpoint is specifically for the signin flow and doesn't require authentication
    """
    try:
        # Get original hostname from origin_url parameter or referer first
        original_hostname = None
        if origin_url:
            from urllib.parse import urlparse
            parsed = urlparse(origin_url)
            original_hostname = parsed.netloc
            logger.info(f"Using original_hostname from origin_url parameter: {original_hostname}")
        else:
            referer = request.headers.get("referer", "")
            if referer:
                from urllib.parse import urlparse
                parsed = urlparse(referer)
                original_hostname = parsed.netloc
                logger.info(f"Extracted original_hostname from referer: {original_hostname}")
            else:
                logger.warning("No origin_url or referer found, original_hostname will be None")

        # Determine workspace from hostname if not provided
        if not workspace_id and original_hostname:
            # Extract subdomain from hostname (e.g., "sfx" from "sfx.enque.cc")
            if original_hostname.endswith('.enque.cc'):
                subdomain = original_hostname.replace('.enque.cc', '')
                workspace = db.query(Workspace).filter(Workspace.subdomain == subdomain).first()
                if workspace:
                    workspace_id = workspace.id
                    logger.info(f"🎯 Found workspace {workspace_id} for subdomain '{subdomain}' from hostname '{original_hostname}'")
                else:
                    logger.warning(f"⚠️ No workspace found for subdomain '{subdomain}' from hostname '{original_hostname}'")
            
        # Default workspace if still not found
        if not workspace_id:
            workspace = db.query(Workspace).first()
            if not workspace:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No workspace available"
                )
            workspace_id = workspace.id
            logger.warning(f"🔄 Using default workspace {workspace_id} as fallback")
            
        # Validate workspace exists
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Workspace with ID {workspace_id} not found"
            )
        
        # Create state data for signin flow
        state_data = {
            "workspace_id": str(workspace_id),
            "flow": "auth",  # This identifies it as an authentication flow (signin)
            "original_hostname": original_hostname
        }
        state_json_string = json.dumps(state_data)
        base64_state = base64.urlsafe_b64encode(state_json_string.encode()).decode('utf-8')
        base64_state = base64_state.replace('+', '-').replace('/', '_').rstrip('=')
        
        # Build Microsoft OAuth URL
        auth_url_params = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "response_mode": "query",
            "scope": "offline_access User.Read Mail.Read",  # Added User.Read for profile info including avatar
            "state": base64_state,
            "prompt": "select_account"  # This allows users to select which account to use
        }
        
        import urllib.parse
        auth_url_params_encoded = urllib.parse.urlencode(auth_url_params)
        auth_url = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize?{auth_url_params_encoded}"
        
        logger.info(f"Generated Microsoft signin auth URL for workspace {workspace_id}")
        
        return {
            "auth_url": auth_url,
            "message": "Microsoft signin authorization URL generated successfully"
        }
        
    except Exception as e:
        logger.error(f"Error generating Microsoft signin auth URL: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating signin authorization URL: {str(e)}"
        )

@router.get("/profile/test")
async def test_microsoft_profile_endpoint(
    current_agent: Agent = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    try:
        agent_id = current_agent.id
        fresh_agent = db.query(Agent).filter(Agent.id == agent_id).first()
        microsoft_tokens = db.query(MicrosoftToken).filter(
            MicrosoftToken.agent_id == agent_id
        ).all()
        
        return {
            "message": "Microsoft profile endpoint is working", 
            "status": "ok",
            "agent_id": fresh_agent.id,
            "agent_email": fresh_agent.email,
            "auth_method": getattr(fresh_agent, 'auth_method', 'FIELD_NOT_FOUND'),
            "microsoft_id": getattr(fresh_agent, 'microsoft_id', None),
            "microsoft_email": getattr(fresh_agent, 'microsoft_email', None),
            "microsoft_profile_data": bool(getattr(fresh_agent, 'microsoft_profile_data', None)),
            "microsoft_tokens_count": len(microsoft_tokens),
            "tokens_info": [
                {
                    "id": token.id,
                    "mailbox_connection_id": token.mailbox_connection_id,
                    "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                    "is_expired": token.is_expired() if hasattr(token, 'is_expired') else None
                } for token in microsoft_tokens
            ]
        }
    except Exception as e:
        return {
            "message": "Error testing agent model",
            "status": "error",
            "error": str(e)
        }
@router.get("/profile/auth/url")
async def get_microsoft_profile_auth_url(
    request: Request,
    origin_url: Optional[str] = Query(None, description="Frontend origin URL for redirect"),
    current_agent: Agent = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    logger.info(f"🔗 Microsoft profile auth URL endpoint called with origin_url: {origin_url}")
    logger.info(f"🔗 Current agent: {current_agent.id if current_agent else 'None'} - {current_agent.email if current_agent else 'No email'}")
    
    try:
        if not current_agent or not current_agent.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        if origin_url:
            from urllib.parse import urlparse
            parsed = urlparse(origin_url)
            host = parsed.netloc or parsed.path.split('/')[0]
        else:
            referer = request.headers.get("referer", "")
            if referer:
                from urllib.parse import urlparse
                parsed = urlparse(referer)
                host = parsed.netloc
            else:
                host = "app.enque.cc"
        state_data = {
            "workspace_id": str(current_agent.workspace_id),
            "agent_id": str(current_agent.id),
            "original_hostname": host,
            "flow": "profile_link"
        }
        state_json_string = json.dumps(state_data)
        base64_state = base64.urlsafe_b64encode(state_json_string.encode()).decode('utf-8')
        base64_state = base64_state.replace('+', '-').replace('/', '_').rstrip('=')
        auth_url_params = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "response_mode": "query",
            "scope": "User.Read openid profile", 
            "state": base64_state,
            "prompt": "select_account"
        }
        
        import urllib.parse
        auth_url_params_encoded = urllib.parse.urlencode(auth_url_params)
        auth_url = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize?{auth_url_params_encoded}"
        
        logger.info(f"Generated Microsoft profile linking URL for agent {current_agent.id}")
        
        return {
            "auth_url": auth_url,
            "message": "Profile linking authorization URL generated successfully"
        }
        
    except Exception as e:
        logger.error(f"Error generating Microsoft profile auth URL: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating profile authorization URL: {str(e)}"
        )

@router.post("/auth/unlink")
async def unlink_microsoft_account(
    current_agent: Agent = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    try:
        fresh_agent = db.query(Agent).filter(Agent.id == current_agent.id).first()
        if not fresh_agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        
        if not fresh_agent.microsoft_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent does not have Microsoft account linked"
            )
        fresh_agent.microsoft_id = None
        fresh_agent.microsoft_email = None
        fresh_agent.microsoft_tenant_id = None
        fresh_agent.microsoft_profile_data = None
        if fresh_agent.auth_method == "both":
            fresh_agent.auth_method = "password"
        elif fresh_agent.auth_method == "microsoft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot unlink Microsoft account without setting a password first"
            )
        microsoft_tokens = db.query(MicrosoftToken).filter(
            MicrosoftToken.agent_id == fresh_agent.id
        ).all()
        
        for token in microsoft_tokens:
            db.delete(token)
        
        db.commit()
        from app.core.cache import user_cache
        user_cache.delete(fresh_agent.id)
        
        logger.info(f"Successfully unlinked Microsoft account for agent {fresh_agent.email}")
        
        return {
            "message": "Microsoft account unlinked successfully",
            "agent_id": fresh_agent.id,
            "auth_method": fresh_agent.auth_method
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error unlinking Microsoft account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error unlinking Microsoft account: {str(e)}"
        )

@router.post("/auth/sync-avatar")
async def sync_microsoft_avatar(
    current_agent: Agent = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Sincroniza manualmente el avatar desde Microsoft 365.
    Útil para actualizar el avatar cuando el usuario lo haya cambiado en M365.
    """
    try:
        # Verificar que el agente tenga cuenta Microsoft vinculada
        fresh_agent = db.query(Agent).filter(Agent.id == current_agent.id).first()
        if not fresh_agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        
        if not fresh_agent.microsoft_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent does not have Microsoft account linked"
            )
        
        # Obtener token válido para la sincronización
        microsoft_token = db.query(MicrosoftToken).filter(
            MicrosoftToken.agent_id == fresh_agent.id,
            MicrosoftToken.mailbox_connection_id.is_(None)  # Token de perfil, no de mailbox
        ).order_by(MicrosoftToken.created_at.desc()).first()
        
        if not microsoft_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Microsoft profile token found. Please re-link your account."
            )
        
        # Verificar si el token es válido
        if microsoft_token.expires_at <= datetime.utcnow():
            # TODO: Implementar refresh token logic si es necesario
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Microsoft token expired. Please re-link your account."
            )
        
        # Sincronizar avatar
        microsoft_service = MicrosoftGraphService(db)
        
        try:
            logger.info(f"🔄 Manual avatar sync requested for agent {fresh_agent.id}")
            photo_bytes = microsoft_service._get_user_profile_photo(microsoft_token.access_token)
            
            if photo_bytes:
                logger.info(f"📸 Profile photo found ({len(photo_bytes)} bytes), uploading to S3...")
                avatar_url = microsoft_service._upload_avatar_to_s3(photo_bytes, fresh_agent.id)
                
                if avatar_url:
                    # Actualizar avatar_url del agente
                    old_avatar_url = fresh_agent.avatar_url
                    fresh_agent.avatar_url = avatar_url
                    db.commit()
                    
                    # Invalidar caché
                    from app.core.cache import user_cache
                    user_cache.delete(fresh_agent.id)
                    
                    logger.info(f"✅ Successfully synced avatar for agent {fresh_agent.id}: {avatar_url}")
                    
                    return {
                        "message": "Avatar synchronized successfully",
                        "avatar_url": avatar_url,
                        "previous_avatar_url": old_avatar_url,
                        "agent_id": fresh_agent.id
                    }
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to upload avatar to S3"
                    )
            else:
                return {
                    "message": "No profile photo available in Microsoft 365",
                    "avatar_url": None,
                    "agent_id": fresh_agent.id
                }
                
        except Exception as sync_error:
            logger.error(f"❌ Error during avatar sync for agent {fresh_agent.id}: {str(sync_error)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error synchronizing avatar: {str(sync_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error in sync avatar endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error synchronizing avatar: {str(e)}"
        )

@router.get("/auth/profile")
async def get_microsoft_profile(
    current_agent: Agent = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    try:
        fresh_agent = db.query(Agent).filter(Agent.id == current_agent.id).first()
        if not fresh_agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        
        if not fresh_agent.microsoft_id or not fresh_agent.microsoft_profile_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent does not have Microsoft profile data"
            )
        
        profile_data = json.loads(fresh_agent.microsoft_profile_data)
        response_data = profile_data.copy()
        response_data.update({
            "microsoft_id": fresh_agent.microsoft_id,
            "microsoft_email": fresh_agent.microsoft_email,
            "tenantId": fresh_agent.microsoft_tenant_id, 
        })
        
        return response_data
        
    except HTTPException:
        raise
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error parsing Microsoft profile data"
        )
    except Exception as e:
        logger.error(f"Error getting Microsoft profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting Microsoft profile: {str(e)}"
        )

@router.get("/auth/status")
async def get_microsoft_auth_status(
    current_agent: Agent = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    try:
        agent_id = current_agent.id
        current_agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not current_agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )
        is_connected = bool(
            current_agent.microsoft_id and 
            current_agent.microsoft_email and 
            current_agent.auth_method in ['microsoft', 'both']
        )
        microsoft_profile = None
        if current_agent.microsoft_profile_data:
            try:
                import json
                microsoft_profile = json.loads(current_agent.microsoft_profile_data)
            except (json.JSONDecodeError, TypeError):
                microsoft_profile = None
        has_password = bool(current_agent.password)
        can_use_password = has_password
        can_use_microsoft = is_connected
        
        return {
            "agent_id": current_agent.id,
            "is_linked": is_connected, 
            "is_connected": is_connected,
            "microsoft_email": current_agent.microsoft_email,
            "microsoft_id": current_agent.microsoft_id,
            "auth_method": current_agent.auth_method,
            "has_password": has_password,
            "can_use_password": can_use_password,
            "can_use_microsoft": can_use_microsoft,
            "profile": microsoft_profile
        }
        
    except Exception as e:
        logger.error(f"Error getting Microsoft auth status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting Microsoft auth status: {str(e)}"
        )

def get_frontend_redirect_url(path: str, original_hostname: Optional[str] = None) -> str:
    if original_hostname:
        base_url = f"https://{original_hostname}"
        logger.info(f"Using original_hostname for redirect base: {base_url}")
    else:
        base_url = settings.FRONTEND_URL.strip('/') if settings.FRONTEND_URL else "https://app.enque.cc" # Default fallback
        logger.warning(f"Original hostname not provided or invalid in state, falling back to: {base_url}")
    return f"{base_url}{path}"
@router.get("/connections", response_model=List[MailboxConnectionSchema])
def get_connections( 
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    if not current_agent or not current_agent.workspace_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    connections = db.query(MailboxConnection).options(
        joinedload(MailboxConnection.teams)
    ).filter(
        MailboxConnection.workspace_id == current_agent.workspace_id,
        MailboxConnection.is_active == True
    ).all()

    # Convert to response format with team_ids
    result = []
    for conn in connections:
        conn_dict = {
            "id": conn.id,
            "email": conn.email,
            "display_name": conn.display_name,
            "workspace_id": conn.workspace_id,
            "created_by_agent_id": conn.created_by_agent_id,
            "is_global": conn.is_global,
            "is_active": conn.is_active,
            "created_at": conn.created_at,
            "updated_at": conn.updated_at,
            "team_ids": [team.id for team in conn.teams],
            "teams": [{"id": team.id, "name": team.name, "icon_name": team.icon_name} for team in conn.teams]
        }
        result.append(conn_dict)

    logger.info(f"Found {len(connections)} active connections for workspace {current_agent.workspace_id}")
    return result
@router.delete("/connection/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_mailbox(
    connection_id: int, # Added path parameter
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    if not current_agent or not current_agent.workspace_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    workspace_id = current_agent.workspace_id
    logger.info(f"Attempting to disconnect mailbox connection ID {connection_id} for workspace {workspace_id}")
    connection = db.query(MailboxConnection).filter(
        MailboxConnection.id == connection_id,
        MailboxConnection.workspace_id == workspace_id
    ).first()

    if not connection:
        logger.warning(f"Mailbox connection ID {connection_id} not found or does not belong to workspace {workspace_id}.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox connection not found.")
    if not connection.is_active:
        logger.info(f"Mailbox connection ID {connection_id} is already inactive.")
        return None 

    try:
        token = db.query(MicrosoftToken).filter(MicrosoftToken.mailbox_connection_id == connection.id).order_by(MicrosoftToken.created_at.desc()).first()
        sync_config = db.query(EmailSyncConfig).filter(EmailSyncConfig.mailbox_connection_id == connection.id).first()
        if sync_config:
            db.delete(sync_config)
            logger.info(f"Deleting EmailSyncConfig ID: {sync_config.id}")
        if token:
            db.delete(token)
            logger.info(f"Deleting MicrosoftToken ID: {token.id}")
        db.delete(connection)
        logger.info(f"Deleting MailboxConnection ID: {connection.id}")

        db.commit()
        logger.info(f"Successfully deleted mailbox connection {connection.email} (ID: {connection_id}) for workspace {workspace_id}")
        return None 

    except Exception as e:
        db.rollback()
        logger.error(f"Error disconnecting mailbox for workspace {workspace_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to disconnect mailbox.")
class ReconnectMailboxRequest(BaseModel):
    state: Optional[str] = Field(None, description="Base64 encoded state from frontend containing workspace_id, agent_id, and original_hostname")
@router.post("/connection/{connection_id}/reconnect", response_model=dict)
def reconnect_mailbox(
    connection_id: int,
    request_data: ReconnectMailboxRequest,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    if not current_agent or not current_agent.workspace_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    
    workspace_id = current_agent.workspace_id
    logger.info(f"Attempting to reconnect mailbox connection ID {connection_id} for workspace {workspace_id}")
    connection = db.query(MailboxConnection).filter(
        MailboxConnection.id == connection_id,
        MailboxConnection.workspace_id == workspace_id
    ).first()
    
    if not connection:
        logger.warning(f"Mailbox connection ID {connection_id} not found or does not belong to workspace {workspace_id}.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox connection not found.")
    
    try:
        original_hostname = None
        if request_data.state:
            try:
                missing_padding = len(request_data.state) % 4
                if missing_padding:
                    padded_state = request_data.state + ('=' * (4 - missing_padding))
                else:
                    padded_state = request_data.state
                
                decoded_state = base64.urlsafe_b64decode(padded_state).decode('utf-8')
                state_data = json.loads(decoded_state)
                original_hostname = state_data.get("original_hostname")
                logger.info(f"Extracted original_hostname from state: {original_hostname}")
            except Exception as e:
                logger.warning(f"Could not decode state parameter: {e}")
        
        # Generate state parameter with connection_id included
        state_data = {
            "workspace_id": str(workspace_id),
            "agent_id": str(current_agent.id),
            "connection_id": str(connection_id),
            "is_reconnect": "true",
            "original_hostname": original_hostname
        }
        
        state_json_string = json.dumps(state_data)
        base64_state = base64.urlsafe_b64encode(state_json_string.encode()).decode('utf-8')
        base64_state = base64_state.replace('+', '-').replace('/', '_').rstrip('=')
        
        logger.info(f"Generated reconnect state for Microsoft auth: {base64_state}")
        
        microsoft_service = MicrosoftGraphService(db)
        email_sync_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        email_sync_scopes = ["offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared", "User.Read"]
        auth_url = microsoft_service.get_auth_url(
            redirect_uri=email_sync_redirect_uri,
            scopes=email_sync_scopes,
            state=base64_state,
            prompt="consent"  
        )
        
        return {"auth_url": auth_url}
    except Exception as e:
        logger.error(f"Error generating reconnection URL for mailbox {connection_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate reconnection URL: {str(e)}"
        )
@router.get("/auth/authorize", response_model=dict)
def get_microsoft_auth_url(
    state: Optional[str] = Query(None, description="State parameter received from frontend, includes workspace_id, agent_id, and original_hostname"), # Added state query param
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user) # Keep for validation if needed, but don't use for state generation
):
    try:
        if not current_agent or not current_agent.workspace_id:
             raise HTTPException(
                 status_code=status.HTTP_401_UNAUTHORIZED,
                 detail="Could not determine active user or workspace."
             )
        if not state:
             logger.error("State parameter is missing in the request to /auth/authorize")
             raise HTTPException(
                 status_code=status.HTTP_400_BAD_REQUEST,
                 detail="State parameter is required."
             )

        logger.info(f"Received state from frontend: {state}")

        microsoft_service = MicrosoftGraphService(db)
        email_sync_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        email_sync_scopes = ["offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared", "User.Read"]
        auth_url = microsoft_service.get_auth_url(
            redirect_uri=email_sync_redirect_uri,
            scopes=email_sync_scopes,
            prompt="consent", 
            state=state 
        )
        logger.info(f"Generated auth URL for email sync flow with redirect_uri: {email_sync_redirect_uri} and state: {state}")
        return {"auth_url": auth_url}
    except Exception as e:
        logger.error(f"Error generating email sync auth URL: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
@router.get("/auth/callback")
async def microsoft_auth_callback_get(
    request: Request, 
    code: Optional[str] = None,
    state: Optional[str] = None, # State now includes workspace_id, agent_id, original_hostname
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    admin_consent: Optional[str] = None,
    db: Session = Depends(get_db)
):
    if state == "admin_flow":
        if admin_consent == "True" or (not error and not code):
            logger.info("[MICROSOFT AUTH] Admin consent successful!")
            return {
                "access_token": "",
                "token_type": "Bearer",
                "expires_in": 0,
                "refresh_token": "",
                "scope": "",
                "message": "Admin consent granted successfully for the organization",
                "success": True
            }
        elif error:
            logger.error(f"Admin consent error: {error} - {error_description}")
            error_message = urllib.parse.quote(f"Admin consent error: {error} - {error_description}")
            redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}")
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    original_hostname: Optional[str] = None
    state_data: Optional[dict] = None 
    if state:
        try:
            missing_padding = len(state) % 4
            if missing_padding:
                state += '=' * (4 - missing_padding)
            logger.debug(f"Attempting to decode Base64 state (with padding added if needed): {state}")
            decoded_state_bytes = base64.urlsafe_b64decode(state)
            decoded_state_json = decoded_state_bytes.decode('utf-8')
            state_data = json.loads(decoded_state_json)

            original_hostname = state_data.get('original_hostname')
            if original_hostname:
                logger.info(f"Extracted original_hostname from Base64 state: {original_hostname}")
            else:
                logger.warning(f"original_hostname not found in parsed Base64 state data: {state_data}")
        except Exception as decode_err:
            logger.error(f"Failed to decode/parse Base64 state parameter '{state}': {decode_err}")
    if error:
        logger.error(f"OAuth error during user auth: {error} - {error_description}")
        error_message = urllib.parse.quote(f"OAuth error: {error} - {error_description}")
        if state_data and state_data.get('flow') == 'auth':
            redirect_url = get_frontend_redirect_url(f"/signin?error={error}&error_description={error_description or ''}", original_hostname)
        elif state_data and state_data.get('flow') == 'profile_link':
            redirect_url = get_frontend_redirect_url(f"/settings/profile?microsoft_link=true&status=error&message={error_message}", original_hostname)
        else:
            redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}", original_hostname)
        
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    # Handle missing code by redirecting using original_hostname if available
    if not code:
        logger.error("Missing authorization code in Microsoft user auth callback.")
        
        # Determine error redirect based on flow type
        if state_data and state_data.get('flow') == 'auth':
            redirect_url = get_frontend_redirect_url("/signin?error=missing_code", original_hostname)
        elif state_data and state_data.get('flow') == 'profile_link':
            redirect_url = get_frontend_redirect_url("/settings/profile?microsoft_link=true&status=error&message=Missing%20authorization%20code", original_hostname)
        else:
            redirect_url = get_frontend_redirect_url("/configuration/mailbox?status=error&message=Missing%20authorization%20code", original_hostname)
        
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    try:
        flow_type = state_data.get('flow') if state_data else None

        # --- UNIFIED FLOW START ---
        if flow_type in ['auth', 'profile_link']:
            redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
            
            microsoft_service = MicrosoftGraphService(db)
            # This now calls the service that correctly saves the refresh token
            token_response = microsoft_service.exchange_code_for_token(
                code=code,
                redirect_uri=redirect_uri,
                state=state
            )

            if flow_type == 'auth':
                # If it's a login flow, we need to generate a session token and redirect
                agent = db.query(Agent).filter(Agent.id == token_response.agent_id).first()
                if not agent:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found after Microsoft auth.")

                access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
                token_payload = {
                    "role": agent.role,
                    "workspace_id": str(agent.workspace_id),
                    "name": agent.name,
                    "email": agent.email,
                    "auth_method": agent.auth_method
                }
                session_token = create_access_token(
                    subject=str(agent.id),
                    extra_data=token_payload,
                    expires_delta=access_token_expires,
                )
                logger.info(f"Microsoft login successful, generated session token for agent {agent.id}")
                redirect_url = get_frontend_redirect_url(f"/signin?microsoft_token={session_token}&success=true", original_hostname)
            
            else: # flow_type == 'profile_link'
                success_message = urllib.parse.quote("Microsoft account linked successfully!")
                redirect_url = get_frontend_redirect_url(f"/settings/profile?microsoft_link=true&status=success&message={success_message}", original_hostname)

        # --- UNIFIED FLOW END ---
        
        elif state_data and state_data.get('flow') == 'mailbox_reconnect':
            logger.info("📝 Processing as mailbox token regeneration flow")
            # Profile linking flow - use exchange_code_for_token with profile linking
            redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
            logger.info(f"Profile linking callback using redirect_uri: {redirect_uri}")
            
            microsoft_service = MicrosoftGraphService(db)
            microsoft_service.exchange_code_for_token(
                code=code,
                redirect_uri=redirect_uri,
                state=state
            )
            
            success_message = urllib.parse.quote("Microsoft account linked successfully!")
            redirect_url = get_frontend_redirect_url(f"/settings/profile?microsoft_link=true&status=success&message={success_message}", original_hostname)
        elif state_data and state_data.get('flow') == 'mailbox_reconnect':
            logger.info("📝 Processing as mailbox token regeneration flow")
            mailbox_id = int(state_data.get('mailbox_id'))
            
            # Regenerate token for specific mailbox
            redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
            logger.info(f"Mailbox reconnect callback for mailbox {mailbox_id} using redirect_uri: {redirect_uri}")
            
            microsoft_service = MicrosoftGraphService(db)
            
            # Verify mailbox exists
            mailbox = db.query(MailboxConnection).filter(MailboxConnection.id == mailbox_id).first()
            if not mailbox:
                logger.error(f"Mailbox {mailbox_id} not found for token regeneration")
                error_message = urllib.parse.quote(f"Mailbox not found")
                redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}", original_hostname)
                return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
            
            try:
                # Para el flow de regeneración, necesitamos actualizar el state con información del agente
                # Obtener workspace del mailbox para determinar el agente
                workspace_id = mailbox.workspace_id
                
                # Obtener el agente que creó este mailbox o cualquier admin del workspace
                agent = db.query(Agent).filter(
                    Agent.workspace_id == workspace_id,
                    Agent.role.in_(['admin', 'manager']),
                    Agent.is_active == True
                ).first()
                
                if not agent:
                    # Si no hay admin, usar el agente que creó el mailbox
                    agent = db.query(Agent).filter(Agent.id == mailbox.created_by_agent_id).first()
                
                if not agent:
                    logger.error(f"No suitable agent found for mailbox {mailbox_id} token regeneration")
                    error_message = urllib.parse.quote("No suitable agent found for token regeneration")
                    redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}", original_hostname)
                    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
                
                # Crear un state actualizado con la información del agente
                updated_state_data = {
                    "workspace_id": str(workspace_id),
                    "agent_id": str(agent.id),
                    "connection_id": str(mailbox_id),
                    "is_reconnect": "true",
                    "flow": "mailbox_reconnect"
                }
                
                updated_state_json = json.dumps(updated_state_data)
                updated_state = base64.b64encode(updated_state_json.encode()).decode()
                
                # Exchange code for token and update the existing mailbox
                new_token = microsoft_service.exchange_code_for_token(
                    code=code,
                    redirect_uri=redirect_uri,
                    state=updated_state
                )
                
                logger.info(f"Successfully regenerated token for mailbox {mailbox.email} (ID: {mailbox_id})")
                success_message = urllib.parse.quote(f"Token regenerated successfully for {mailbox.email}")
                redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=success&message={success_message}", original_hostname)
                
            except Exception as e:
                logger.error(f"Failed to regenerate token for mailbox {mailbox_id}: {str(e)}")
                error_message = urllib.parse.quote(f"Failed to regenerate token: {str(e)}")
                redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}", original_hostname)
                return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        else:
            logger.info("📝 Processing as mailbox configuration flow (DEFAULT) - This should NOT happen for agent login!")
            redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
            logger.info(f"Mailbox configuration callback using redirect_uri: {redirect_uri}")

            microsoft_service = MicrosoftGraphService(db)
            microsoft_service.exchange_code_for_token(
                code=code,
                redirect_uri=redirect_uri,
                state=state
            )
            
            success_message = urllib.parse.quote("Microsoft account connected successfully!")
            redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=success&message={success_message}", original_hostname)
        
        logger.info(f"Successfully processed token, redirecting to: {redirect_url}")
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        logger.error(f"Error during Microsoft callback processing: {e}", exc_info=True)
        error_message = urllib.parse.quote(f"Failed to process Microsoft callback: {str(e)}")
        
        # Determine error redirect URL based on flow type
        if state_data and state_data.get('flow') == 'profile_link':
            redirect_url = get_frontend_redirect_url(f"/settings/profile?microsoft_link=true&status=error&message={error_message}", original_hostname)
        else:
            redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}", original_hostname)
        
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.get("/integration", response_model=Optional[MicrosoftIntegrationSchema])
def get_microsoft_integration(
    db: Session = Depends(get_db)
):
    integration = db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active Microsoft integration found"
        )
    return integration


@router.post("/integration", response_model=MicrosoftIntegrationSchema)
def create_microsoft_integration(
    integration: MicrosoftIntegrationCreate,
    db: Session = Depends(get_db)
):
    existing = db.query(MicrosoftIntegration).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Microsoft integration already exists. Use PUT to update it."
        )
    correct_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
    logger.info(f"Creating integration with forced redirect_uri: {correct_redirect_uri}")
    new_integration = MicrosoftIntegration(
        tenant_id=integration.tenant_id,
        client_id=integration.client_id,
        client_secret=integration.client_secret,
        redirect_uri=correct_redirect_uri,
        scope=integration.scope,
        is_active=integration.is_active
    )
    
    db.add(new_integration)
    db.commit()
    db.refresh(new_integration)
    
    return new_integration


@router.put("/integration/{integration_id}", response_model=MicrosoftIntegrationSchema)
def update_microsoft_integration(
    integration_id: int,
    integration: MicrosoftIntegrationUpdate,
    db: Session = Depends(get_db)
):
    existing = db.query(MicrosoftIntegration).filter(MicrosoftIntegration.id == integration_id).first()
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Microsoft integration not found"
        )
    update_data = integration.dict(exclude_unset=True)
    if "redirect_uri" in update_data:
        correct_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        logger.info(f"Updating integration with forced redirect_uri: {correct_redirect_uri}")
        update_data["redirect_uri"] = correct_redirect_uri
    
    for key, value in update_data.items():
        setattr(existing, key, value)
    
    db.commit()
    db.refresh(existing)
    
    return existing


@router.post("/sync/{config_id}", response_model=List[EmailTicketMappingSchema])
def sync_emails(
    config_id: int,
    db: Session = Depends(get_db)
):
    config = db.query(EmailSyncConfig).filter(EmailSyncConfig.id == config_id).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email sync configuration not found"
        )
    
    try:
        microsoft_service = MicrosoftGraphService(db)
        tasks = microsoft_service.sync_emails(config)
        task_ids = [task.id for task in tasks]
        mappings = db.query(EmailTicketMapping).filter(EmailTicketMapping.task_id.in_(task_ids)).all()
        
        return mappings
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync emails: {str(e)}"
        )


@router.get("/mailboxes", response_model=List[MailboxConnectionSchema])
def get_mailbox_connections(
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
) -> Any:
    mailboxes = db.query(MailboxConnection).filter(
        MailboxConnection.workspace_id == current_agent.workspace_id
    ).all()
    return mailboxes


@router.get("/email-config", response_model=List[EmailSyncConfigSchema])
def get_email_sync_configs(
    db: Session = Depends(get_db)
):
    configs = db.query(EmailSyncConfig).all()
    return configs


@router.get("/auth/admin-consent")
def get_admin_consent_url(
    db: Session = Depends(get_db)
):
    try:
        microsoft_service = MicrosoftGraphService(db)
        if not microsoft_service.integration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Microsoft integration not configured"
            )
        tenant_id = microsoft_service.integration.tenant_id
        client_id = microsoft_service.integration.client_id
        redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        admin_consent_url = (
            f"https://login.microsoftonline.com/{tenant_id}/adminconsent"
            f"?client_id={client_id}"
            f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
            f"&state=admin_flow"
        )
        
        logger.info("[MICROSOFT AUTH] Created admin consent URL using /adminconsent endpoint")
        logger.info(f"Admin consent URL: {admin_consent_url}")
        
        return {
            "admin_consent_url": admin_consent_url,
            "message": "Use this URL for an administrator to provide consent for the entire organization. You must be a Global Administrator, Application Administrator, or Cloud Application Administrator in your Microsoft 365 tenant."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.put("/connection/{connection_id}", response_model=MailboxConnectionSchema)
def update_mailbox_connection(
    connection_id: int,
    connection_update: MailboxConnectionUpdate,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    if not current_agent or not current_agent.workspace_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    connection = db.query(MailboxConnection).options(
        joinedload(MailboxConnection.teams)
    ).filter(
        MailboxConnection.id == connection_id,
        MailboxConnection.workspace_id == current_agent.workspace_id
    ).first()

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Mailbox connection not found"
        )

    try:
        # Update basic fields
        update_data = connection_update.dict(exclude_unset=True, exclude={'team_ids'})
        
        for field, value in update_data.items():
            setattr(connection, field, value)
        if connection_update.team_ids is not None:
            connection.teams.clear()
            if not connection_update.is_global and connection_update.team_ids:
                from app.models.team import Team
                teams = db.query(Team).filter(
                    Team.id.in_(connection_update.team_ids),
                    Team.workspace_id == current_agent.workspace_id
                ).all()
                
                if len(teams) != len(connection_update.team_ids):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="One or more team IDs are invalid"
                    )
                
                connection.teams.extend(teams)

        db.commit()
        db.refresh(connection)
        result = {
            "id": connection.id,
            "email": connection.email,
            "display_name": connection.display_name,
            "workspace_id": connection.workspace_id,
            "created_by_agent_id": connection.created_by_agent_id,
            "is_global": connection.is_global,
            "is_active": connection.is_active,
            "created_at": connection.created_at,
            "updated_at": connection.updated_at,
            "team_ids": [team.id for team in connection.teams],
            "teams": [{"id": team.id, "name": team.name, "icon_name": team.icon_name} for team in connection.teams]
        }
        
        logger.info(f"Updated mailbox connection {connection_id}: global={connection.is_global}, teams={[t.id for t in connection.teams]}")
        return result
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating mailbox connection {connection_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update mailbox connection"
        )

@router.post("/mailboxes/{mailbox_id}/auto-regenerate-token")
async def auto_regenerate_mailbox_token(
    mailbox_id: int,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    """
    Regenera automáticamente el token de Microsoft para un mailbox usando refresh token
    o copiando un token válido existente del workspace
    """
    try:
        # Verificar que el mailbox existe y el agente tiene acceso
        mailbox = db.query(MailboxConnection).filter(
            MailboxConnection.id == mailbox_id,
            MailboxConnection.workspace_id == current_agent.workspace_id
        ).first()
        
        if not mailbox:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mailbox not found or access denied"
            )
        
        # Buscar un token existente para este mailbox
        existing_token = db.query(MicrosoftToken).filter(
            MicrosoftToken.mailbox_connection_id == mailbox_id
        ).first()
        
        microsoft_service = MicrosoftGraphService(db)
        
        # Método 1: Intentar renovar con refresh token si existe
        if existing_token and existing_token.refresh_token:
            try:
                logger.info(f"Attempting to refresh existing token for mailbox {mailbox.email}")
                refreshed_token = await microsoft_service.refresh_token_async(existing_token)
                
                if refreshed_token:
                    logger.info(f"Successfully refreshed token for mailbox {mailbox.email}")
                    return {
                        "success": True,
                        "method": "refresh_token",
                        "mailbox_email": mailbox.email,
                        "token_expires_at": refreshed_token.expires_at.isoformat(),
                        "message": f"Token refreshed successfully for {mailbox.email}"
                    }
            except Exception as refresh_error:
                logger.warning(f"Failed to refresh token for mailbox {mailbox_id}: {refresh_error}")
        
        # Método 2: Copiar token válido de otro agente del workspace
        logger.info(f"Attempting to clone token from workspace agents for mailbox {mailbox.email}")
        
        # Buscar tokens válidos de agentes en el mismo workspace
        valid_agent_tokens = db.query(Agent, MicrosoftToken)\
            .join(MicrosoftToken, MicrosoftToken.agent_id == Agent.id)\
            .filter(
                Agent.workspace_id == current_agent.workspace_id,
                Agent.microsoft_id.isnot(None),
                MicrosoftToken.access_token.isnot(None),
                MicrosoftToken.expires_at > datetime.utcnow()
            ).all()
        
        if valid_agent_tokens:
            # Usar el primer token válido encontrado
            source_agent, source_token = valid_agent_tokens[0]
            logger.info(f"Cloning token from agent {source_agent.email} to mailbox {mailbox.email}")
            
            # Obtener o crear integración
            integration = db.query(MicrosoftIntegration).first()
            if not integration:
                integration = MicrosoftIntegration(
                    tenant_id=settings.MICROSOFT_TENANT_ID,
                    client_id=settings.MICROSOFT_CLIENT_ID,
                    client_secret=settings.MICROSOFT_CLIENT_SECRET
                )
                db.add(integration)
                db.commit()
                db.refresh(integration)
            
            # Crear/actualizar token para el mailbox basado en el token del agente
            if existing_token:
                # Actualizar token existente
                existing_token.access_token = source_token.access_token
                existing_token.expires_at = source_token.expires_at
                existing_token.updated_at = datetime.utcnow()
                logger.info(f"Updated existing token for mailbox {mailbox.email}")
            else:
                # Crear nuevo token
                new_token = MicrosoftToken(
                    integration_id=integration.id,
                    agent_id=None,  # No agent_id for mailbox tokens
                    mailbox_connection_id=mailbox_id,
                    access_token=source_token.access_token,
                    refresh_token="",  # Mailbox tokens usually don't have refresh tokens
                    token_type="Bearer",
                    expires_at=source_token.expires_at
                )
                db.add(new_token)
                logger.info(f"Created new token for mailbox {mailbox.email}")
            
            db.commit()
            
            return {
                "success": True,
                "method": "token_clone",
                "mailbox_email": mailbox.email,
                "source_agent": source_agent.email,
                "token_expires_at": source_token.expires_at.isoformat(),
                "message": f"Token cloned successfully from {source_agent.email} to {mailbox.email}"
            }
        
        # Método 3: Si no hay tokens válidos, devolver URL de autorización manual
        logger.warning(f"No valid tokens found in workspace for cloning. Manual authorization required.")
        
        return {
            "success": False,
            "method": "manual_required",
            "mailbox_email": mailbox.email,
            "message": f"No valid tokens available for automatic regeneration. Manual authorization required.",
            "manual_auth_endpoint": f"/v1/microsoft/mailboxes/{mailbox_id}/regenerate-token"
        }
        
    except Exception as e:
        logger.error(f"Error auto-regenerating token for mailbox {mailbox_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to auto-regenerate token: {str(e)}"
        )

@router.post("/mailboxes/auto-regenerate-all")
async def auto_regenerate_all_missing_tokens(
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    """
    Regenera automáticamente todos los tokens faltantes para mailboxes del workspace
    """
    try:
        from datetime import datetime
        
        # Obtener todos los mailboxes del workspace que necesitan tokens
        mailboxes = db.query(MailboxConnection).filter(
            MailboxConnection.workspace_id == current_agent.workspace_id,
            MailboxConnection.is_active == True
        ).all()
        
        results = []
        
        for mailbox in mailboxes:
            # Verificar si necesita token
            token = db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox.id
            ).first()
            
            needs_regeneration = not token or token.expires_at < datetime.utcnow()
            
            if needs_regeneration:
                try:
                    # Llamar al endpoint de auto-regeneración para este mailbox
                    result = await auto_regenerate_mailbox_token(mailbox.id, db, current_agent)
                    results.append({
                        "mailbox_id": mailbox.id,
                        "mailbox_email": mailbox.email,
                        **result
                    })
                except Exception as e:
                    results.append({
                        "mailbox_id": mailbox.id,
                        "mailbox_email": mailbox.email,
                        "success": False,
                        "error": str(e)
                    })
            else:
                results.append({
                    "mailbox_id": mailbox.id,
                    "mailbox_email": mailbox.email,
                    "success": True,
                    "method": "no_action_needed",
                    "message": "Token is already valid"
                })
        
        successful = len([r for r in results if r.get("success")])
        total = len(results)
        
        logger.info(f"Auto-regeneration completed: {successful}/{total} successful")
        
        return {
            "workspace_id": current_agent.workspace_id,
            "total_mailboxes": total,
            "successful_regenerations": successful,
            "failed_regenerations": total - successful,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Error auto-regenerating all tokens: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to auto-regenerate all tokens: {str(e)}"
        )

@router.post("/mailboxes/{mailbox_id}/regenerate-token")
async def regenerate_mailbox_token(
    mailbox_id: int,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    """
    Regenera el token de Microsoft para un mailbox específico
    Útil cuando el token ha expirado o no existe
    """
    try:
        # Verificar que el mailbox existe y el agente tiene acceso
        mailbox = db.query(MailboxConnection).filter(
            MailboxConnection.id == mailbox_id,
            MailboxConnection.workspace_id == current_agent.workspace_id
        ).first()
        
        if not mailbox:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mailbox not found or access denied"
            )
        
        # Generar URL de autorización para reconectar el mailbox
        state_data = {
            "workspace_id": str(current_agent.workspace_id),
            "flow": "mailbox_reconnect",
            "mailbox_id": str(mailbox_id),
            "original_hostname": "app.enque.cc"  # Default hostname
        }
        
        # Encode state data
        state_json = json.dumps(state_data)
        encoded_state = base64.b64encode(state_json.encode()).decode()
        
        # Build authorization URL
        auth_url = (
            f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
            f"?client_id={settings.MICROSOFT_CLIENT_ID}"
            f"&response_type=code"
            f"&redirect_uri={urllib.parse.quote(settings.MICROSOFT_REDIRECT_URI)}"
            f"&response_mode=query"
            f"&scope={urllib.parse.quote('offline_access User.Read Mail.Read Mail.ReadWrite Mail.Send TeamMember.ReadWrite.All TeamsActivity.Send')}"
            f"&state={encoded_state}"
        )
        
        logger.info(f"Generated token regeneration URL for mailbox {mailbox.email} (ID: {mailbox_id})")
        
        return {
            "auth_url": auth_url,
            "mailbox_email": mailbox.email,
            "message": f"Use this URL to regenerate token for mailbox {mailbox.email}"
        }
        
    except Exception as e:
        logger.error(f"Error generating token regeneration URL for mailbox {mailbox_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate regeneration URL: {str(e)}"
        )

@router.get("/mailboxes/missing-tokens")
async def get_mailboxes_missing_tokens(
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    """
    Lista todos los mailboxes que no tienen tokens válidos
    """
    try:
        from datetime import datetime
        
        # Obtener todos los mailboxes del workspace
        mailboxes = db.query(MailboxConnection).filter(
            MailboxConnection.workspace_id == current_agent.workspace_id,
            MailboxConnection.is_active == True
        ).all()
        
        missing_tokens = []
        
        for mailbox in mailboxes:
            # Verificar si tiene token válido
            token = db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox.id
            ).first()
            
            status_info = {
                "mailbox_id": mailbox.id,
                "email": mailbox.email,
                "display_name": mailbox.display_name,
                "has_token": token is not None,
                "token_expired": False,
                "needs_regeneration": False
            }
            
            if token:
                token_expired = token.expires_at < datetime.utcnow()
                status_info["token_expired"] = token_expired
                status_info["token_expires_at"] = token.expires_at.isoformat()
                status_info["needs_regeneration"] = token_expired
            else:
                status_info["needs_regeneration"] = True
            
            if status_info["needs_regeneration"]:
                missing_tokens.append(status_info)
        
        logger.info(f"Found {len(missing_tokens)} mailboxes needing token regeneration in workspace {current_agent.workspace_id}")
        
        return {
            "workspace_id": current_agent.workspace_id,
            "mailboxes_missing_tokens": missing_tokens,
            "total_count": len(missing_tokens)
        }
        
    except Exception as e:
        logger.error(f"Error getting mailboxes missing tokens: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get mailboxes missing tokens: {str(e)}"
        )
