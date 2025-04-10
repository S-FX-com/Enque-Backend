from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from sqlalchemy.orm import Session
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.models.agent import Agent
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailSyncConfig, EmailTicketMapping
from app.schemas.microsoft import (
    OAuthRequest, OAuthCallback, TokenResponse, 
    MicrosoftIntegration as MicrosoftIntegrationSchema,
    MicrosoftIntegrationCreate, MicrosoftIntegrationUpdate,
    EmailSyncConfig as EmailSyncConfigSchema,
    EmailSyncConfigCreate, EmailSyncConfigUpdate,
    EmailTicketMapping as EmailTicketMappingSchema
)
from app.services.microsoft import MicrosoftGraphService
from app.utils.logger import ms_logger as logger
from app.core.config import settings

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


@router.post("/auth/callback", response_model=TokenResponse)
def microsoft_auth_callback_post(
    callback: OAuthCallback,
    db: Session = Depends(get_db)
):
    """
    Handle Microsoft OAuth callback (POST method)
    """
    if callback.error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error: {callback.error} - {callback.error_description}"
        )
    
    if not callback.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No authorization code provided"
        )
    
    try:
        microsoft_service = MicrosoftGraphService(db)
        token = microsoft_service.exchange_code_for_token(
            code=callback.code,
            redirect_uri=callback.redirect_uri or settings.MICROSOFT_REDIRECT_URI
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


@router.get("/auth/callback", response_model=TokenResponse)
def microsoft_auth_callback_get(
    code: str,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Handle Microsoft OAuth callback (GET method, for redirects from Microsoft)
    """
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
        microsoft_service = MicrosoftGraphService(db)
        token = microsoft_service.exchange_code_for_token(
            code=code,
            redirect_uri=settings.MICROSOFT_REDIRECT_URI
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
    
    # Create new integration
    new_integration = MicrosoftIntegration(
        tenant_id=integration.tenant_id,
        client_id=integration.client_id,
        client_secret=integration.client_secret,
        redirect_uri=integration.redirect_uri,
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
    for key, value in update_data.items():
        setattr(existing, key, value)
    
    db.commit()
    db.refresh(existing)
    
    return existing


@router.delete("/integration/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_microsoft_integration(
    integration_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a Microsoft integration and its associated tokens
    """
    # Get existing integration
    integration = db.query(MicrosoftIntegration).filter(MicrosoftIntegration.id == integration_id).first()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Microsoft integration not found"
        )
    
    # Remove associated tokens
    db.query(MicrosoftToken).filter(MicrosoftToken.integration_id == integration_id).delete()
    
    # Remove associated email configs
    email_configs = db.query(EmailSyncConfig).filter(EmailSyncConfig.integration_id == integration_id).all()
    for config in email_configs:
        # Remove email-to-ticket mappings for this config
        db.query(EmailTicketMapping).filter(EmailTicketMapping.sync_config_id == config.id).delete()
        # Delete the config
        db.delete(config)
    
    # Delete integration
    db.delete(integration)
    db.commit()
    
    logger.info(f"Microsoft integration {integration_id} deleted with all associated data")
    return None


@router.get("/sync-config", response_model=List[EmailSyncConfigSchema])
def get_sync_configs(
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
) -> Any:
    """Get email synchronization configurations"""
    if not current_agent.is_admin:
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    configs = db.query(EmailSyncConfig).all()
    return configs


@router.post("/sync-config", response_model=EmailSyncConfigSchema)
def create_sync_config(
    config: EmailSyncConfigCreate,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
) -> Any:
    """Create email synchronization configuration"""
    if not current_agent.role == "Admin":
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    # Check if integration exists
    integration = db.query(MicrosoftIntegration).filter(
        MicrosoftIntegration.id == config.integration_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Microsoft integration not found")
        
    # Create config
    db_config = EmailSyncConfig(**config.dict())
    db.add(db_config)
    db.commit()
    db.refresh(db_config)
    
    return db_config


@router.put("/sync-config/{config_id}", response_model=EmailSyncConfigSchema)
def update_sync_config(
    config_id: int,
    config: EmailSyncConfigUpdate,
    db: Session = Depends(get_db),
    current_agent: Agent = Depends(get_current_active_user)
) -> Any:
    """Update email synchronization configuration"""
    if not current_agent.is_admin:
        raise HTTPException(status_code=403, detail="Not enough permissions")
        
    # Get existing config
    db_config = db.query(EmailSyncConfig).filter(
        EmailSyncConfig.id == config_id
    ).first()
    
    if not db_config:
        raise HTTPException(status_code=404, detail="Sync configuration not found")
        
    # Update fields
    for field, value in config.dict(exclude_unset=True).items():
        setattr(db_config, field, value)
        
    db.commit()
    db.refresh(db_config)
    
    return db_config


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


@router.get("/email-mappings", response_model=List[EmailTicketMappingSchema])
def get_email_ticket_mappings(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get email to ticket mappings with pagination
    """
    skip = (page - 1) * limit
    mappings = db.query(EmailTicketMapping).offset(skip).limit(limit).all()
    return mappings


@router.get("/email-config", response_model=List[EmailSyncConfigSchema])
def get_email_sync_configs(
    db: Session = Depends(get_db)
):
    """
    Get all email synchronization configurations
    """
    configs = db.query(EmailSyncConfig).all()
    return configs


@router.post("/email-config", response_model=EmailSyncConfigSchema)
def create_email_sync_config(
    config: EmailSyncConfigCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new email synchronization configuration
    """
    # Get the active integration
    integration = db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active Microsoft integration found"
        )
    
    # Create new config
    new_config = EmailSyncConfig(
        integration_id=integration.id,
        folder_name=config.folder_name,
        sync_interval=config.sync_interval,
        default_priority=config.default_priority,
        auto_assign=config.auto_assign,
        default_assignee_id=config.default_assignee_id,
        is_active=config.is_active
    )
    
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    
    return new_config


@router.put("/email-config/{config_id}", response_model=EmailSyncConfigSchema)
def update_email_sync_config(
    config_id: int,
    config: EmailSyncConfigUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing email synchronization configuration
    """
    # Get existing config
    existing = db.query(EmailSyncConfig).filter(EmailSyncConfig.id == config_id).first()
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email sync configuration not found"
        )
    
    # Update fields
    update_data = config.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(existing, key, value)
    
    db.commit()
    db.refresh(existing)
    
    return existing 