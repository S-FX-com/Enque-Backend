import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from app.models.notification import NotificationTemplate, NotificationSetting
from app.models.workspace import Workspace
from app.models.microsoft import MailboxConnection, MicrosoftToken
from app.models.agent import Agent
from app.schemas.notification import (
    NotificationSettingsResponse,
    AgentNotificationsConfig,
    UserNotificationsConfig,
    NotificationTypeConfig,
    AgentEmailNotificationsConfig,
    AgentEnquePopupConfig,
    AgentTeamsConfig,
    UserEmailNotificationsConfig,
)
from app.services.microsoft_service import MicrosoftGraphService
from app.core.config import settings

logger = logging.getLogger(__name__)


def get_notification_templates(db: Session, workspace_id: int) -> List[NotificationTemplate]:
    """Get all notification templates for a workspace."""
    return db.query(NotificationTemplate).filter(
        NotificationTemplate.workspace_id == workspace_id
    ).all()


def get_notification_template(db: Session, template_id: int) -> Optional[NotificationTemplate]:
    """Get a notification template by ID."""
    return db.query(NotificationTemplate).filter(
        NotificationTemplate.id == template_id
    ).first()


def create_notification_template(
    db: Session, workspace_id: int, type: str, name: str, subject: str, template: str
) -> NotificationTemplate:
    """Create a notification template."""
    db_template = NotificationTemplate(
        workspace_id=workspace_id,
        type=type,
        name=name,
        subject=subject,
        template=template,
        is_enabled=True
    )
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template


def update_notification_template(
    db: Session, template_id: int, template_content: str
) -> Optional[NotificationTemplate]:
    """Update a notification template."""
    db_template = get_notification_template(db, template_id)
    if not db_template:
        return None
    
    db_template.template = template_content
    db_template.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_template)
    return db_template


def get_notification_settings(db: Session, workspace_id: int) -> List[NotificationSetting]:
    """Get all notification settings for a workspace."""
    return db.query(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id
    ).all()


def get_notification_setting(db: Session, setting_id: int) -> Optional[NotificationSetting]:
    """Get a notification setting by ID."""
    return db.query(NotificationSetting).filter(
        NotificationSetting.id == setting_id
    ).first()


def toggle_notification_setting(
    db: Session, setting_id: int, enabled: bool
) -> Optional[NotificationSetting]:
    """Toggle a notification setting."""
    db_setting = get_notification_setting(db, setting_id)
    if not db_setting:
        return None
    
    db_setting.is_enabled = enabled
    db_setting.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_setting)
    return db_setting


def connect_notification_channel(
    db: Session, workspace_id: int, channel: str, config: Dict[str, Any]
) -> Optional[NotificationSetting]:
    """Connect a notification channel."""
    db_setting = db.query(NotificationSetting).filter(
        NotificationSetting.workspace_id == workspace_id,
        NotificationSetting.category == "agents",
        NotificationSetting.type == channel
    ).first()
    
    if not db_setting:
        # Create a new setting if it doesn't exist
        channels = json.dumps([channel])
        db_setting = NotificationSetting(
            workspace_id=workspace_id,
            category="agents",
            type=channel,
            is_enabled=True,
            channels=channels
        )
        db.add(db_setting)
    else:
        # Update existing setting
        db_setting.is_enabled = True
        # Add configuration data if needed
        if channel == "teams" and "webhook_url" in config:
            # Store Teams webhook URL or other configuration
            current_channels = json.loads(db_setting.channels) if isinstance(db_setting.channels, str) else db_setting.channels
            # Add or update teams in the channels
            if "teams" not in current_channels:
                current_channels.append("teams")
            db_setting.channels = json.dumps(current_channels)
    
    db_setting.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_setting)
    return db_setting


def format_notification_settings_response(
    db: Session, workspace_id: int
) -> NotificationSettingsResponse:
    """Format notification settings for response."""
    settings = get_notification_settings(db, workspace_id)
    
    # Initialize default configs
    response = NotificationSettingsResponse()
    
    # Process all settings
    for setting in settings:
        # Convert channels from JSON string to list if needed
        channels = json.loads(setting.channels) if isinstance(setting.channels, str) else setting.channels
        
        # Get template content if applicable
        template_content = None
        if setting.template_id:
            template = db.query(NotificationTemplate).filter(
                NotificationTemplate.id == setting.template_id
            ).first()
            if template:
                template_content = template.template
        
        # Process based on category and type
        if setting.category == "agents":
            if setting.type == "new_ticket_created" and "email" in channels:
                response.agents.email.new_ticket_created.is_enabled = setting.is_enabled
                response.agents.email.new_ticket_created.id = setting.id
                response.agents.email.new_ticket_created.template = template_content
            elif setting.type == "new_response" and "email" in channels:
                response.agents.email.new_response.is_enabled = setting.is_enabled
                response.agents.email.new_response.id = setting.id
                response.agents.email.new_response.template = template_content
            elif setting.type == "ticket_assigned" and "email" in channels:
                response.agents.email.ticket_assigned.is_enabled = setting.is_enabled
                response.agents.email.ticket_assigned.id = setting.id
                response.agents.email.ticket_assigned.template = template_content
            elif setting.type == "new_ticket_created" and "enque_popup" in channels:
                response.agents.enque_popup.new_ticket_created.is_enabled = setting.is_enabled
                response.agents.enque_popup.new_ticket_created.id = setting.id
            elif setting.type == "new_response" and "enque_popup" in channels:
                response.agents.enque_popup.new_response.is_enabled = setting.is_enabled
                response.agents.enque_popup.new_response.id = setting.id
            elif setting.type == "ticket_assigned" and "enque_popup" in channels:
                response.agents.enque_popup.ticket_assigned.is_enabled = setting.is_enabled
                response.agents.enque_popup.ticket_assigned.id = setting.id
            elif setting.type == "teams":
                response.agents.teams.is_enabled = setting.is_enabled
                response.agents.teams.is_connected = True  # Assuming if it exists, it's connected
                response.agents.teams.id = setting.id
        
        elif setting.category == "users":
            if setting.type == "new_ticket_created" and "email" in channels:
                response.users.email.new_ticket_created.is_enabled = setting.is_enabled
                response.users.email.new_ticket_created.id = setting.id
                response.users.email.new_ticket_created.template = template_content
            elif setting.type == "ticket_resolved" and "email" in channels:
                response.users.email.ticket_resolved.is_enabled = setting.is_enabled
                response.users.email.ticket_resolved.id = setting.id
                response.users.email.ticket_resolved.template = template_content
            elif setting.type == "new_agent_response" and "email" in channels:
                response.users.email.new_agent_response.is_enabled = setting.is_enabled
                response.users.email.new_agent_response.id = setting.id
                response.users.email.new_agent_response.template = template_content
    
    return response


async def send_notification(
    db: Session,
    workspace_id: int,
    category: str,
    notification_type: str,
    recipient_email: str,
    recipient_name: str,
    template_vars: Dict[str, Any],
    task_id: Optional[int] = None
) -> bool:
    """
    Send a notification based on settings and templates.
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        category: Notification category (agents, users)
        notification_type: Type of notification (new_ticket_created, etc.)
        recipient_email: Email of the recipient
        recipient_name: Name of the recipient
        template_vars: Variables to use in the template
        task_id: Optional task/ticket ID
        
    Returns:
        bool: Whether the notification was sent successfully
    """
    try:
        logger.info(f"[NOTIFY] Starting notification sending: {category}/{notification_type} for {recipient_email} in workspace {workspace_id}")
        
        # Check if this notification type is enabled
        notification_setting = db.query(NotificationSetting).filter(
            NotificationSetting.workspace_id == workspace_id,
            NotificationSetting.category == category,
            NotificationSetting.type == notification_type,
            NotificationSetting.is_enabled == True
        ).first()
        
        if not notification_setting:
            logger.warning(f"[NOTIFY] Notification {notification_type} for {category} is not enabled in workspace {workspace_id}")
            return False
        
        logger.info(f"[NOTIFY] Notification settings found: ID={notification_setting.id}, template_id={notification_setting.template_id}")
        
        # Check if email channel is enabled for this notification
        channels = json.loads(notification_setting.channels) if isinstance(notification_setting.channels, str) else notification_setting.channels
        logger.info(f"[NOTIFY] Configured channels: {channels}")
        
        if "email" not in channels:
            logger.warning(f"[NOTIFY] Email channel not enabled for notification {notification_type} in workspace {workspace_id}")
            return False
        
        # Get the template
        template = None
        if notification_setting.template_id:
            template = db.query(NotificationTemplate).filter(
                NotificationTemplate.id == notification_setting.template_id,
                NotificationTemplate.is_enabled == True
            ).first()
            logger.info(f"[NOTIFY] Template found: ID={template.id if template else 'None'}")
        
        if not template:
            logger.warning(f"[NOTIFY] No template found for notification {notification_type} in workspace {workspace_id}")
            return False
        
        # Find an active mailbox for the workspace to send from
        try:
            mailbox_conn = db.query(MailboxConnection).filter(
                MailboxConnection.workspace_id == workspace_id,
                MailboxConnection.is_active == True
            ).first()
            
            logger.info(f"[NOTIFY] Mailbox connection found: {mailbox_conn is not None}")
            
            if not mailbox_conn:
                logger.warning(f"[NOTIFY] No active mailbox connection found for workspace {workspace_id}")
                return False
        except Exception as mailbox_error:
            logger.error(f"[NOTIFY] Error finding mailbox connection: {str(mailbox_error)}", exc_info=True)
            return False
        
        # Apply template variables
        subject = template.subject
        html_body = template.template
        
        # Replace variables in subject and body
        for var_name, var_value in template_vars.items():
            placeholder = "{{" + var_name + "}}"
            subject = subject.replace(placeholder, str(var_value))
            html_body = html_body.replace(placeholder, str(var_value))
        
        logger.info(f"[NOTIFY] Template rendered with variables: {list(template_vars.keys())}")
        
        # Get an admin with access to the mailbox to send the email
        try:
            admin_sender_info = db.query(Agent, MailboxConnection, MicrosoftToken)\
                .join(MailboxConnection, Agent.id == MailboxConnection.created_by_agent_id)\
                .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
                .filter(
                    Agent.workspace_id == workspace_id,
                    Agent.role.in_(['admin', 'manager']),
                    MailboxConnection.is_active == True,
                    MicrosoftToken.access_token.isnot(None)
                ).order_by(Agent.role.desc()).first()
            
            logger.info(f"[NOTIFY] Admin with mailbox access found: {admin_sender_info is not None}")
            
            if not admin_sender_info:
                logger.warning(f"[NOTIFY] No admin with mailbox access found for workspace {workspace_id}")
                return False
        except Exception as admin_error:
            logger.error(f"[NOTIFY] Error finding admin with mailbox access: {str(admin_error)}", exc_info=True)
            return False
        
        # Get current access token (refresh if needed)
        admin, mailbox_connection, ms_token = admin_sender_info
        current_access_token = ms_token.access_token
        
        if ms_token.expires_at < datetime.utcnow():
            try:
                logger.info(f"[NOTIFY] Refreshing token for mailbox {mailbox_connection.email}")
                graph_service = MicrosoftGraphService(db=db)
                refreshed_ms_token = await graph_service.refresh_token_async(ms_token)
                current_access_token = refreshed_ms_token.access_token
                logger.info("[NOTIFY] Token refreshed successfully")
            except Exception as token_error:
                logger.error(f"[NOTIFY] Error refreshing token: {str(token_error)}", exc_info=True)
                return False
        
        # Send the email
        logger.info(f"[NOTIFY] Attempting to send email from {mailbox_connection.email} to {recipient_email}")
        graph_service = MicrosoftGraphService(db=db)
        success = await graph_service.send_email_with_user_token(
            user_access_token=current_access_token,
            sender_mailbox_email=mailbox_connection.email,
            recipient_email=recipient_email,
            subject=subject,
            html_body=html_body,
            task_id=task_id
        )
        
        if success:
            logger.info(f"[NOTIFY] Notification {notification_type} sent successfully to {recipient_email}")
            return True
        else:
            logger.error(f"[NOTIFY] Failed to send notification {notification_type} to {recipient_email}")
            return False
            
    except Exception as e:
        logger.error(f"[NOTIFY] Error sending notification: {str(e)}", exc_info=True)
        return False 