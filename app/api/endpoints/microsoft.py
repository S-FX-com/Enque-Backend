from typing import Any, List, Optional
from datetime import datetime, timedelta # Import datetime and timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request # Added Request
from fastapi.responses import RedirectResponse # Added RedirectResponse
from sqlalchemy.orm import Session
from app.api.dependencies import get_db, get_current_active_user
from app.models.agent import Agent
from app.core.config import settings # Import settings
from app.models.user import User # Import User if needed for agent context
from app.models.workspace import Workspace # Import Workspace if needed for context
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
from app.utils.logger import ms_logger as logger
import urllib.parse
import base64 # Ensure base64 is imported
import json # Ensure json is imported

router = APIRouter()

# Updated helper function to construct frontend URL using original hostname if provided
def get_frontend_redirect_url(path: str, original_hostname: Optional[str] = None) -> str:
    """Constructs the full frontend URL for redirection."""
    if original_hostname:
        # Use https scheme by default
        base_url = f"https://{original_hostname}"
        logger.info(f"Using original_hostname for redirect base: {base_url}")
    else:
        # Fallback to settings or default
        base_url = settings.FRONTEND_URL.strip('/') if settings.FRONTEND_URL else "https://app.enque.cc" # Default fallback
        logger.warning(f"Original hostname not provided or invalid in state, falling back to: {base_url}")
    return f"{base_url}{path}"


# Renamed endpoint and updated response model
@router.get("/connections", response_model=List[MailboxConnectionSchema])
def get_connections( # Renamed function
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    """
    Get all active MailboxConnections for the current agent's workspace.
    """
    if not current_agent or not current_agent.workspace_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    # Fetch all active connections for the workspace
    connections = db.query(MailboxConnection).filter(
        MailboxConnection.workspace_id == current_agent.workspace_id,
        MailboxConnection.is_active == True
    ).all()

    logger.info(f"Found {len(connections)} active connections for workspace {current_agent.workspace_id}")
    return connections


# Updated DELETE endpoint to accept connection_id
@router.delete("/connection/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_mailbox(
    connection_id: int, # Added path parameter
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
):
    """
    Disconnects a specific mailbox connection by its ID for the current agent's workspace.
    Sets MailboxConnection, associated MicrosoftToken, and EmailSyncConfig to inactive.
    """
    if not current_agent or not current_agent.workspace_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    workspace_id = current_agent.workspace_id
    logger.info(f"Attempting to disconnect mailbox connection ID {connection_id} for workspace {workspace_id}")

    # Find the specific connection by ID and ensure it belongs to the agent's workspace
    connection = db.query(MailboxConnection).filter(
        MailboxConnection.id == connection_id,
        MailboxConnection.workspace_id == workspace_id
    ).first()

    if not connection:
        logger.warning(f"Mailbox connection ID {connection_id} not found or does not belong to workspace {workspace_id}.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox connection not found.")

    # Check if it's already inactive
    if not connection.is_active:
        logger.info(f"Mailbox connection ID {connection_id} is already inactive.")
        return None # Return success as it's already disconnected

    try:
        # Find associated token and config
        token = db.query(MicrosoftToken).filter(MicrosoftToken.mailbox_connection_id == connection.id).order_by(MicrosoftToken.created_at.desc()).first()
        sync_config = db.query(EmailSyncConfig).filter(EmailSyncConfig.mailbox_connection_id == connection.id).first()

        # Delete associated records first (to avoid foreign key issues if applicable)
        if sync_config:
            db.delete(sync_config)
            logger.info(f"Deleting EmailSyncConfig ID: {sync_config.id}")
        if token:
            db.delete(token)
            logger.info(f"Deleting MicrosoftToken ID: {token.id}")

        # Delete the connection itself
        db.delete(connection)
        logger.info(f"Deleting MailboxConnection ID: {connection.id}")

        db.commit()
        logger.info(f"Successfully deleted mailbox connection {connection.email} (ID: {connection_id}) for workspace {workspace_id}")
        # Return No Content on success
        return None # FastAPI handles 204 automatically if no content is returned

    except Exception as e:
        db.rollback()
        logger.error(f"Error disconnecting mailbox for workspace {workspace_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to disconnect mailbox.")


# Removed the old get_connection_status endpoint


@router.get("/auth/authorize", response_model=dict)
def get_microsoft_auth_url(
    state: Optional[str] = Query(None, description="State parameter received from frontend, includes workspace_id, agent_id, and original_hostname"), # Added state query param
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user) # Keep for validation if needed, but don't use for state generation
):
    """
    Get Microsoft OAuth authorization URL specifically for the email sync/integration flow.
    Uses the state parameter provided by the frontend.
    """
    try:
        if not current_agent or not current_agent.workspace_id:
             raise HTTPException(
                 status_code=status.HTTP_401_UNAUTHORIZED,
                 detail="Could not determine active user or workspace."
             )
        
        # Validate the received state parameter is present
        if not state:
             logger.error("State parameter is missing in the request to /auth/authorize")
             raise HTTPException(
                 status_code=status.HTTP_400_BAD_REQUEST,
                 detail="State parameter is required."
             )
        
        # Log the received state
        logger.info(f"Received state from frontend: {state}")

        # --- Removed state regeneration ---
        # state_data = { ... }
        # state_string = urllib.parse.urlencode(state_data)
        # logger.info(f"Generated state for Microsoft auth: {state_string} ...") # Removed log

        microsoft_service = MicrosoftGraphService(db)
        # Explicitly define the correct redirect URI for THIS flow
        email_sync_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        # Explicitly define the scopes needed for email sync
        email_sync_scopes = ["offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared", "User.Read"]

        # Call get_auth_url with the specific redirect_uri, scopes, and the generated state
        auth_url = microsoft_service.get_auth_url(
            redirect_uri=email_sync_redirect_uri,
            scopes=email_sync_scopes,
            prompt="consent", # Ensure prompt is consent for initial setup/re-auth
            state=state # Pass the state received from the frontend query parameter
        )
        # Use the received state in the log message
        logger.info(f"Generated auth URL for email sync flow with redirect_uri: {email_sync_redirect_uri} and state: {state}")
        return {"auth_url": auth_url}
    except Exception as e:
        logger.error(f"Error generating email sync auth URL: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# Changed response_model to RedirectResponse (or remove it if not strictly needed)
@router.get("/auth/callback") # Removed response_model=TokenResponse
def microsoft_auth_callback_get(
    request: Request, # Added Request to potentially get base URL if needed
    code: Optional[str] = None,
    state: Optional[str] = None, # State now includes workspace_id, agent_id, original_hostname
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    admin_consent: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Handle Microsoft OAuth callback (GET method, for redirects from Microsoft)
    """
    # Si estamos en un flujo de consentimiento de administrador
    if state == "admin_flow":
        if admin_consent == "True" or (not error and not code):
            # Caso de éxito en el consentimiento de administrador (no hay código, pero tampoco error)
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
            # Error en el consentimiento de administrador
            # Log the error and redirect (hostname might not be in admin flow state)
            logger.error(f"Admin consent error: {error} - {error_description}")
            error_message = urllib.parse.quote(f"Admin consent error: {error} - {error_description}")
            # Use default redirect for admin flow errors as hostname might be missing
            redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}")
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    # --- Start Normal User Auth Flow ---

    # Parse Base64 encoded state to get original_hostname
    original_hostname: Optional[str] = None
    state_data: Optional[dict] = None # To store parsed state data
    if state:
        try:
            # Add padding if necessary before decoding Base64 URL-safe string
            missing_padding = len(state) % 4
            if missing_padding:
                state += '=' * (4 - missing_padding)
            logger.debug(f"Attempting to decode Base64 state (with padding added if needed): {state}")
            decoded_state_bytes = base64.urlsafe_b64decode(state)
            # Decode bytes to JSON string
            decoded_state_json = decoded_state_bytes.decode('utf-8')
            # Parse JSON string into dictionary
            state_data = json.loads(decoded_state_json)

            original_hostname = state_data.get('original_hostname')
            if original_hostname:
                logger.info(f"Extracted original_hostname from Base64 state: {original_hostname}")
            else:
                logger.warning(f"original_hostname not found in parsed Base64 state data: {state_data}")
        except Exception as decode_err:
            logger.error(f"Failed to decode/parse Base64 state parameter '{state}': {decode_err}")
            # Continue without original_hostname if decoding/parsing fails

    # Handle OAuth errors by redirecting using original_hostname if available
    if error:
        logger.error(f"OAuth error during user auth: {error} - {error_description}")
        error_message = urllib.parse.quote(f"OAuth error: {error} - {error_description}")
        redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}", original_hostname)
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    # Handle missing code by redirecting using original_hostname if available
    if not code:
        logger.error("Missing authorization code in Microsoft user auth callback.")
        redirect_url = get_frontend_redirect_url("/configuration/mailbox?status=error&message=Missing%20authorization%20code", original_hostname)
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    try:
        # Usar la URL correcta fija for token exchange
        redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        logger.info(f"GET callback using fixed redirect_uri: {redirect_uri}")

        microsoft_service = MicrosoftGraphService(db)
        # Pass the state parameter to the service function
        # This function now handles token creation and DB storage based on state
        microsoft_service.exchange_code_for_token(
            code=code,
            redirect_uri=redirect_uri,
            state=state # Pass the state received from the callback
        )

        # Redirect to frontend on success using original_hostname
        success_message = urllib.parse.quote("Microsoft account connected successfully!")
        redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=success&message={success_message}", original_hostname)
        logger.info(f"Successfully processed token, redirecting to: {redirect_url}")
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    except Exception as e:
        logger.error(f"Error during Microsoft callback processing: {e}", exc_info=True)
        # Redirect to frontend on error using original_hostname
        error_message = urllib.parse.quote(f"Failed to process Microsoft callback: {str(e)}")
        redirect_url = get_frontend_redirect_url(f"/configuration/mailbox?status=error&message={error_message}", original_hostname)
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.get("/integration", response_model=Optional[MicrosoftIntegrationSchema])
def get_microsoft_integration(
    db: Session = Depends(get_db)
):
    """
    Get the current Microsoft integration configuration
    """
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
    """
    Create a new Microsoft integration configuration
    """
    # Check if integration already exists
    existing = db.query(MicrosoftIntegration).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Microsoft integration already exists. Use PUT to update it."
        )
    
    # Forzar la URL correcta de redirección
    correct_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
    logger.info(f"Creating integration with forced redirect_uri: {correct_redirect_uri}")
    
    # Create new integration with the correct redirect URI
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
    """
    Update an existing Microsoft integration configuration
    """
    # Get existing integration
    existing = db.query(MicrosoftIntegration).filter(MicrosoftIntegration.id == integration_id).first()
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Microsoft integration not found"
        )
    
    # Update fields
    update_data = integration.dict(exclude_unset=True)
    
    # Forzar siempre la URL correcta de redirección si se está actualizando
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
    """
    Manually trigger email synchronization for a specific configuration
    """
    # Get existing config
    config = db.query(EmailSyncConfig).filter(EmailSyncConfig.id == config_id).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email sync configuration not found"
        )
    
    try:
        # Create service and sync emails
        microsoft_service = MicrosoftGraphService(db)
        tasks = microsoft_service.sync_emails(config)
        
        # Get email mappings for these tasks
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
    """Get all mailbox connections"""
    mailboxes = db.query(MailboxConnection).filter(
        MailboxConnection.workspace_id == current_agent.workspace_id
    ).all()
    return mailboxes


@router.get("/email-config", response_model=List[EmailSyncConfigSchema])
def get_email_sync_configs(
    db: Session = Depends(get_db)
):
    """
    Get all email synchronization configurations
    """
    configs = db.query(EmailSyncConfig).all()
    return configs


@router.get("/auth/admin-consent")
def get_admin_consent_url(
    db: Session = Depends(get_db)
):
    """
    Obtiene la URL para solicitar el consentimiento de administrador para Microsoft Graph API
    Esta URL debe ser visitada por un administrador del tenant de Microsoft para dar consentimiento
    a nivel de organización para la aplicación, permitiendo acceso a todos los buzones.
    """
    try:
        microsoft_service = MicrosoftGraphService(db)
        
        # Obtener los datos básicos de la integración
        if not microsoft_service.integration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Microsoft integration not configured"
            )
    
        # Usar el endpoint específico para consentimiento de administrador
        tenant_id = microsoft_service.integration.tenant_id
        client_id = microsoft_service.integration.client_id
        redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        
        # Construir la URL según la documentación de Microsoft para consentimiento de administrador
        # Ref: https://docs.microsoft.com/en-us/azure/active-directory/develop/v2-admin-consent
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
