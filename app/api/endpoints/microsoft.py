from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.api.dependencies import get_db, get_current_active_user
from app.models.agent import Agent
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

router = APIRouter()


@router.get("/auth/authorize", response_model=dict)
def get_microsoft_auth_url(
    request: OAuthRequest = Depends(),
    db: Session = Depends(get_db)
):
    """
    Get Microsoft OAuth authorization URL
    """
    try:
        microsoft_service = MicrosoftGraphService(db)
        auth_url = microsoft_service.get_auth_url(request.redirect_uri)
        return {"auth_url": auth_url}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/auth/callback", response_model=TokenResponse)
def microsoft_auth_callback_get(
    code: Optional[str] = None,
    state: Optional[str] = None,
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Admin consent error: {error} - {error_description}"
            )
    
    # Flujo normal de autenticación de usuario
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error: {error} - {error_description}"
        )
    
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No authorization code provided"
        )
    
    try:
        # Usar la URL correcta fija
        redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        logger.info(f"GET callback using fixed redirect_uri: {redirect_uri}")
        
        microsoft_service = MicrosoftGraphService(db)
        token = microsoft_service.exchange_code_for_token(
            code=code,
            redirect_uri=redirect_uri
        )
        
        return TokenResponse(
            access_token=token.access_token,
            token_type=token.token_type,
            expires_in=(token.expires_at - token.created_at).seconds,
            refresh_token=token.refresh_token,
            scope=microsoft_service.integration.scope if microsoft_service.integration else ""
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


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