import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, func, select
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


async def get_notification_templates(db: AsyncSession, workspace_id: int) -> List[NotificationTemplate]:
    """Get all notification templates for a workspace."""
    result = await db.execute(
        select(NotificationTemplate).filter(NotificationTemplate.workspace_id == workspace_id)
    )
    return result.scalars().all()


async def get_notification_template(db: AsyncSession, template_id: int) -> Optional[NotificationTemplate]:
    """Get a notification template by ID."""
    result = await db.execute(select(NotificationTemplate).filter(NotificationTemplate.id == template_id))
    return result.scalars().first()


async def create_notification_template(
    db: AsyncSession, workspace_id: int, type: str, name: str, subject: str, template: str
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
    await db.commit()
    await db.refresh(db_template)
    return db_template


async def update_notification_template(
    db: AsyncSession, template_id: int, template_content: str
) -> Optional[NotificationTemplate]:
    """Update a notification template."""
    db_template = await get_notification_template(db, template_id)
    if not db_template:
        return None
    
    db_template.template = template_content
    db_template.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(db_template)
    return db_template


async def get_notification_settings(db: AsyncSession, workspace_id: int) -> List[NotificationSetting]:
    """Get all notification settings for a workspace."""
    result = await db.execute(select(NotificationSetting).filter(NotificationSetting.workspace_id == workspace_id))
    return result.scalars().all()


async def get_notification_setting(db: AsyncSession, setting_id: int) -> Optional[NotificationSetting]:
    """Get a notification setting by ID."""
    result = await db.execute(select(NotificationSetting).filter(NotificationSetting.id == setting_id))
    return result.scalars().first()


async def toggle_notification_setting(
    db: AsyncSession, setting_id: int, enabled: bool
) -> Optional[NotificationSetting]:
    """Toggle a notification setting."""
    db_setting = await get_notification_setting(db, setting_id)
    if not db_setting:
        return None
    
    db_setting.is_enabled = enabled
    db_setting.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(db_setting)
    return db_setting


async def connect_notification_channel(
    db: AsyncSession, workspace_id: int, channel: str, config: Dict[str, Any]
) -> Optional[NotificationSetting]:
    """Connect a notification channel."""
    result = await db.execute(
        select(NotificationSetting).filter(
            NotificationSetting.workspace_id == workspace_id,
            NotificationSetting.category == "agents",
            NotificationSetting.type == channel
        )
    )
    db_setting = result.scalars().first()
    
    if not db_setting:
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
        db_setting.is_enabled = True
        if channel == "teams" and "webhook_url" in config:
            current_channels = json.loads(db_setting.channels) if isinstance(db_setting.channels, str) else db_setting.channels
            if "teams" not in current_channels:
                current_channels.append("teams")
            db_setting.channels = json.dumps(current_channels)
    
    db_setting.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(db_setting)
    return db_setting


async def format_notification_settings_response(
    db: AsyncSession, workspace_id: int
) -> NotificationSettingsResponse:
    """Format notification settings for response."""
    settings = await get_notification_settings(db, workspace_id)
    
    response = NotificationSettingsResponse()
    
    for setting in settings:
        channels = json.loads(setting.channels) if isinstance(setting.channels, str) else setting.channels
        
        template_content = None
        if setting.template_id:
            result = await db.execute(select(NotificationTemplate).filter(NotificationTemplate.id == setting.template_id))
            template = result.scalars().first()
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
            elif setting.type == "ticket_closed" and "email" in channels:
                response.users.email.ticket_closed.is_enabled = setting.is_enabled
                response.users.email.ticket_closed.id = setting.id
                response.users.email.ticket_closed.template = template_content
            elif setting.type == "new_agent_response" and "email" in channels:
                response.users.email.new_agent_response.is_enabled = setting.is_enabled
                response.users.email.new_agent_response.id = setting.id
                response.users.email.new_agent_response.template = template_content
    
    return response


async def is_team_notification_enabled(db: AsyncSession, workspace_id: int) -> bool:
    """
    Check if team notifications are enabled for a workspace.
    """
    try:
        result = await db.execute(
            select(NotificationSetting).filter(
                NotificationSetting.workspace_id == workspace_id,
                NotificationSetting.category == "agents",
                NotificationSetting.type == "new_ticket_for_team",
                NotificationSetting.is_enabled == True
            )
        )
        notification_setting = result.scalars().first()
        
        if not notification_setting:
            return False
        
        channels = json.loads(notification_setting.channels) if isinstance(notification_setting.channels, str) else notification_setting.channels
        return "email" in channels
        
    except Exception as e:
        logger.error(f"Error checking team notification setting for workspace {workspace_id}: {str(e)}")
        return False


async def send_notification(
    db: AsyncSession,
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
    Uses the specific mailbox of the ticket if available.
    
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
        logger.info(f"[NOTIFY] Iniciando envío de notificación: {category}/{notification_type} para {recipient_email} en workspace {workspace_id}")
        
        result = await db.execute(
            select(NotificationSetting).filter(
                NotificationSetting.workspace_id == workspace_id,
                NotificationSetting.category == category,
                NotificationSetting.type == notification_type,
                NotificationSetting.is_enabled == True
            )
        )
        notification_setting = result.scalars().first()
        
        if not notification_setting:
            logger.warning(f"[NOTIFY] Notificación {notification_type} para {category} no está habilitada en workspace {workspace_id}")
            return False
        
        logger.info(f"[NOTIFY] Configuración de notificación encontrada: ID={notification_setting.id}, template_id={notification_setting.template_id}")
        
        channels = json.loads(notification_setting.channels) if isinstance(notification_setting.channels, str) else notification_setting.channels
        logger.info(f"[NOTIFY] Canales configurados: {channels}")
        
        if "email" not in channels:
            logger.warning(f"[NOTIFY] Canal de email no habilitado para notificación {notification_type} en workspace {workspace_id}")
            return False
        
        template = None
        if notification_setting.template_id:
            result = await db.execute(
                select(NotificationTemplate).filter(
                    NotificationTemplate.id == notification_setting.template_id,
                    NotificationTemplate.is_enabled == True
                )
            )
            template = result.scalars().first()
            logger.info(f"[NOTIFY] Plantilla encontrada: ID={template.id if template else 'None'}")
        
        if not template:
            logger.warning(f"[NOTIFY] No se encontró plantilla para notificación {notification_type} en workspace {workspace_id}")
            return False
        
        success_email = False
        success_teams = False
        
        if "email" in channels:
            logger.info(f"[NOTIFY] Enviando notificación por EMAIL")
            success_email = await _send_email_notification(
                db, workspace_id, template, template_vars, 
                recipient_email, task_id
            )

        if category == "agents":
            result = await db.execute(
                select(Agent).filter(
                    Agent.email == recipient_email,
                    Agent.workspace_id == workspace_id
                )
            )
            agent = result.scalars().first()

            if agent and agent.teams_notifications_enabled:
                logger.info(f"[NOTIFY] Enviando notificación por TEAMS al agente {agent.id}")
                try:
                    result = await db.execute(select(Workspace).filter(Workspace.id == workspace_id))
                    workspace = result.scalars().first()
                    if workspace and task_id:
                        link_to_ticket = f"https://{workspace.subdomain}.enque.cc/tickets/{task_id}"
                        
                        title = template.subject
                        for var_name, var_value in template_vars.items():
                            placeholder = "{{" + var_name + "}}"
                            title = title.replace(placeholder, str(var_value))
                        
                        preview_message = f"Ticket #{task_id}: {template_vars.get('ticket_title', '')}"

                        graph_service = MicrosoftGraphService(db=db)
                        await graph_service.initialize()
                        await graph_service.send_teams_activity_notification(
                            agent_id=agent.id,
                            title=title,
                            message=preview_message,
                            link_to_ticket=link_to_ticket,
                            subdomain=workspace.subdomain
                        )
                        success_teams = True
                    else:
                        logger.warning(f"No se pudo enviar notificación de Teams para el agente {agent.id} porque falta workspace o task_id.")

                except Exception as teams_error:
                    logger.error(f"Error al enviar notificación de Teams: {str(teams_error)}", exc_info=True)
        
        # Considerar exitoso si al menos uno de los canales funcionó
        return success_email or success_teams
            
    except Exception as e:
        logger.error(f"[NOTIFY] Error enviando notificación: {str(e)}", exc_info=True)
        return False


async def _send_email_notification(
    db: AsyncSession,
    workspace_id: int,
    template: NotificationTemplate,
    template_vars: Dict[str, Any],
    recipient_email: str,
    task_id: Optional[int] = None
) -> bool:
    """Envía notificación por email"""
    try:
        
        # Intentar usar el mailbox específico del ticket primero
        preferred_mailbox = None
        preferred_token = None
        
        if task_id:
            from app.models.task import Task
            result = await db.execute(select(Task).filter(Task.id == task_id))
            task = result.scalars().first()
            
            if task and task.mailbox_connection_id:
                logger.info(f"[NOTIFY] Ticket {task_id} tiene mailbox específico ID: {task.mailbox_connection_id}")
                
                result = await db.execute(
                    select(MailboxConnection, MicrosoftToken)
                    .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)
                    .filter(
                        MailboxConnection.id == task.mailbox_connection_id,
                        MailboxConnection.is_active == True,
                        MicrosoftToken.access_token.isnot(None)
                    )
                )
                mailbox_token_info = result.first()
                
                if mailbox_token_info:
                    preferred_mailbox, preferred_token = mailbox_token_info
                    logger.info(f"[NOTIFY] Usando mailbox específico del ticket: {preferred_mailbox.email}")
                else:
                    logger.warning(f"[NOTIFY] No se encontró token válido para el mailbox específico del ticket {task_id}")

        if not preferred_mailbox or not preferred_token:
            logger.info(f"[NOTIFY] Buscando mailbox fallback para workspace {workspace_id}")
            
            try:
                result = await db.execute(
                    select(Agent, MailboxConnection, MicrosoftToken)
                    .join(MailboxConnection, Agent.id == MailboxConnection.created_by_agent_id)
                    .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)
                    .filter(
                        Agent.workspace_id == workspace_id,
                        Agent.role.in_(['admin', 'manager']),
                        MailboxConnection.is_active == True,
                        MicrosoftToken.access_token.isnot(None)
                    ).order_by(Agent.role.desc())
                )
                admin_sender_info = result.first()
                
                logger.info(f"[NOTIFY] Admin con acceso al mailbox encontrado: {admin_sender_info is not None}")
                
                if not admin_sender_info:
                    logger.warning(f"[NOTIFY] No se encontró admin con acceso al mailbox para workspace {workspace_id}")
                    return False
                    
                admin, preferred_mailbox, preferred_token = admin_sender_info
                logger.info(f"[NOTIFY] Usando mailbox fallback: {preferred_mailbox.email}")
                
            except Exception as admin_error:
                logger.error(f"[NOTIFY] Error al buscar admin con acceso al mailbox: {str(admin_error)}", exc_info=True)
                return False
        
        # Apply template variables including mailbox-specific ones
        subject = template.subject
        html_body = template.template
        
        # Add mailbox display name to template variables if available
        if preferred_mailbox and preferred_mailbox.display_name:
            template_vars["mailbox_name"] = preferred_mailbox.display_name
            template_vars["sender_name"] = preferred_mailbox.display_name
        
        # Replace variables in subject and body
        for var_name, var_value in template_vars.items():
            placeholder = "{{" + var_name + "}}"
            subject = subject.replace(placeholder, str(var_value))
            html_body = html_body.replace(placeholder, str(var_value))
        
        logger.info(f"[NOTIFY] Plantilla renderizada con variables: {list(template_vars.keys())}")
        
        # Get current access token (refresh if needed)
        current_access_token = preferred_token.access_token
        
        if preferred_token.expires_at < datetime.utcnow():
            try:
                logger.info(f"[NOTIFY] Refrescando token para mailbox {preferred_mailbox.email}")
                graph_service = MicrosoftGraphService(db=db)
                refreshed_ms_token = await graph_service.refresh_token_async(preferred_token)
                current_access_token = refreshed_ms_token.access_token
                logger.info("[NOTIFY] Token refrescado exitosamente")
            except Exception as token_error:
                logger.error(f"[NOTIFY] Error refrescando token: {str(token_error)}", exc_info=True)
                return False
        
        # Send the email using the correct mailbox
        logger.info(f"[NOTIFY] Intentando enviar email desde {preferred_mailbox.email} a {recipient_email}")
        graph_service = MicrosoftGraphService(db=db)
        success = await graph_service.send_email_with_user_token(
            user_access_token=current_access_token,
            sender_mailbox_email=preferred_mailbox.email,
            recipient_email=recipient_email,
            subject=subject,
            html_body=html_body,
            task_id=task_id
        )
        
        if success:
            logger.info(f"[NOTIFY] Notificación {notification_type} enviada exitosamente a {recipient_email} desde {preferred_mailbox.email}")
            return True
        else:
            logger.error(f"[NOTIFY] Falló el envío de notificación {notification_type} a {recipient_email}")
            return False
            
    except Exception as e:
        logger.error(f"[NOTIFY] Error enviando notificación: {str(e)}", exc_info=True)
        return False
