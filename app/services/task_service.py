from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session, joinedload 
from datetime import datetime
import threading
import re
import asyncio
from uuid import UUID

from app.models.task import Task, TicketBody  
from app.models.microsoft import EmailTicketMapping
from app.schemas.task import TicketCreate, TicketUpdate
from app.schemas.microsoft import EmailInfo
from app.utils.logger import logger, log_important
from app.database.session import SessionLocal 
from app.models.agent import Agent
from app.models.microsoft import MailboxConnection, MicrosoftToken
from app.core.config import settings
from app.services.email_service import send_ticket_assignment_email, send_team_ticket_notification_email
from app.services.microsoft_service import MicrosoftGraphService


def get_tasks(db: Session, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get all tasks"""
    return db.query(Task).options(joinedload(Task.user)).filter(Task.is_deleted == False).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


def get_task_by_id(db: Session, task_id: int) -> Optional[Dict[str, Any]]:
    """Get a task by ID with email info if available"""
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        return None
    email_mapping = db.query(EmailTicketMapping).filter(
        EmailTicketMapping.ticket_id == task.id
    ).first()
    
    task_dict = task.__dict__.copy()
    task_dict['is_from_email'] = email_mapping is not None
    
    if email_mapping:
        task_dict['email_info'] = EmailInfo(
            id=email_mapping.id,
            email_id=email_mapping.email_id,
            email_conversation_id=email_mapping.email_conversation_id,
            email_subject=email_mapping.email_subject,
            email_sender=email_mapping.email_sender,
            email_received_at=email_mapping.email_received_at
        )
    else:
        task_dict['email_info'] = None
    
    return task_dict


def create_task(db: Session, task_in: TicketCreate, current_user_id: int = None) -> Task: 
    """Create a new task"""
    task_data = task_in.dict()

    if not task_data.get('sent_from_id') and current_user_id:
        task_data['sent_from_id'] = current_user_id
    
    task = Task(**task_data)
    db.add(task)
    db.commit()
    db.refresh(task) 
    db.refresh(task, attribute_names=['user']) 
    
    # Ejecutar workflows para el evento 'ticket.created'
    try:
        from app.services.workflow_service import WorkflowService
        context = {'ticket': task}
        executed_workflows = WorkflowService.execute_workflows(
            db=db,
            trigger='ticket.created',
            workspace_id=task.workspace_id,
            context=context
        )
        if executed_workflows:
            logger.info(f"Executed workflows for ticket creation {task.id}: {executed_workflows}")
    except Exception as e:
        logger.error(f"Error executing workflows for ticket creation {task.id}: {str(e)}")

    return task

def _mark_email_read_bg(task_id: int): 
    """Marcar email como leído en segundo plano usando una nueva sesión de DB."""
    db: Session = None 
    try:
        db = SessionLocal()
        if db is None:
             logger.error(f"Failed to create DB session for background task (ticket #{task_id})")
             return

        from app.services.microsoft_service import mark_email_as_read_by_task_id
        success = mark_email_as_read_by_task_id(db, task_id)
        if success:
            log_important(f"Email successfully marked as read in background for ticket #{task_id}")
        else:
            logger.error(f"Could not mark email as read in background for ticket #{task_id}")
    except Exception as e:
        logger.error(f"Error in background email marking for ticket #{task_id}: {str(e)}")
    finally:
        if db:
            db.close()


def update_task(db: Session, task_id: int, task_in: TicketUpdate, request_origin: Optional[str] = None) -> Optional[Dict[str, Any]]: 
    """Update a task - optimizada para respuesta rápida"""
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        return None
    old_assignee_id = task.assignee_id
    old_status = task.status
    old_priority = task.priority

    update_data = task_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    # ✅ OPTIMIZACIÓN: Commit inmediato para respuesta rápida
    db.commit()
    db.refresh(task)
    db.refresh(task, attribute_names=['user', 'assignee', 'sent_from', 'sent_to', 'team', 'company', 'workspace', 'body', 'category']) 
    
    # ✅ OPTIMIZACIÓN: Ejecutar procesos pesados en background usando threading
    try:
        # Ejecutar workflows en background thread
        threading.Thread(
            target=_execute_workflows_thread,
            args=(task_id, task.workspace_id, old_assignee_id, old_status, old_priority, update_data),
            daemon=True
        ).start()
        
        # Enviar notificaciones en background thread
        if 'assignee_id' in update_data and old_assignee_id != task.assignee_id and task.assignee_id is not None:
            threading.Thread(
                target=_send_assignment_notification_thread,
                args=(task_id, request_origin),
                daemon=True
            ).start()
        
        if ('team_id' in update_data or 'assignee_id' in update_data) and task.team_id and not task.assignee_id:
            threading.Thread(
                target=_send_team_notification_thread,
                args=(task_id, request_origin),
                daemon=True
            ).start()
        
        if 'status' in update_data and old_status != task.status and task.status == 'Closed':
            threading.Thread(
                target=_send_closure_notification_thread,
                args=(task_id,),
                daemon=True
            ).start()
            
        logger.info(f"🚀 Background processes queued for ticket {task_id}")
            
    except Exception as e:
        logger.error(f"Error iniciando procesos background para ticket {task_id}: {str(e)}")
    
    # ✅ RESPUESTA RÁPIDA: Procesar solo la información esencial para la respuesta
    email_mapping = db.query(EmailTicketMapping).filter(
        EmailTicketMapping.ticket_id == task.id
    ).first()
    task_dict = task.__dict__.copy()
    task_dict['is_from_email'] = email_mapping is not None
    
    if email_mapping:
        task_dict['email_info'] = EmailInfo(
            id=email_mapping.id,
            email_id=email_mapping.email_id,
            email_conversation_id=email_mapping.email_conversation_id,
            email_subject=email_mapping.email_subject,
            email_sender=email_mapping.email_sender,
            email_received_at=email_mapping.email_received_at
        )
    else:
        task_dict['email_info'] = None
    
    return task_dict


def _execute_workflows_thread(task_id: int, workspace_id: int, old_assignee_id, old_status, old_priority, update_data):
    """Ejecutar workflows en background thread"""
    try:
        from app.services.workflow_service import WorkflowService
        # Crear nueva sesión para background task
        background_db = SessionLocal()
        
        try:
            # Reload task for background processing
            task = background_db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return
                
            context = {'ticket': task, 'old_values': {'assignee_id': old_assignee_id, 'status': old_status, 'priority': old_priority}}
            executed_workflows = []
            
            # Workflow general de actualización
            executed_workflows.extend(WorkflowService.execute_workflows(
                db=background_db,
                trigger='ticket.updated',
                workspace_id=workspace_id,
                context=context
            ))
            
            # Workflows específicos según el tipo de cambio
            if 'status' in update_data and old_status != task.status:
                executed_workflows.extend(WorkflowService.execute_workflows(
                    db=background_db,
                    trigger='ticket.status_changed',
                    workspace_id=workspace_id,
                    context=context
                ))
            
            if 'priority' in update_data and old_priority != task.priority:
                executed_workflows.extend(WorkflowService.execute_workflows(
                    db=background_db,
                    trigger='ticket.priority_changed',
                    workspace_id=workspace_id,
                    context=context
                ))
            
            if 'assignee_id' in update_data:
                if old_assignee_id != task.assignee_id:
                    if task.assignee_id is not None:
                        executed_workflows.extend(WorkflowService.execute_workflows(
                            db=background_db,
                            trigger='ticket.assigned',
                            workspace_id=workspace_id,
                            context=context
                        ))
                    else:
                        executed_workflows.extend(WorkflowService.execute_workflows(
                            db=background_db,
                            trigger='ticket.unassigned',
                            workspace_id=workspace_id,
                            context=context
                        ))
            
            if executed_workflows:
                logger.info(f"✅ Background workflows executed for ticket {task_id}: {executed_workflows}")
                background_db.commit()
                
        finally:
            background_db.close()
            
    except Exception as e:
        logger.error(f"❌ Error in background workflows for ticket {task_id}: {str(e)}")


def _send_closure_notification_thread(task_id: int):
    """Enviar notificación de cierre en background thread"""
    try:
        from app.services.notification_service import send_notification
        import asyncio
        # Crear nueva sesión para background task
        background_db = SessionLocal()
        
        try:
            # Reload task with user relationship
            task_with_user = background_db.query(Task).options(joinedload(Task.user)).filter(Task.id == task_id).first()
            
            if task_with_user and task_with_user.user and task_with_user.user.email:
                # Preparar variables de plantilla
                template_vars = {
                    "user_name": task_with_user.user.name,
                    "ticket_id": task_with_user.id,
                    "ticket_title": task_with_user.title
                }
                
                # Crear event loop para la función async
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Ejecutar la función async de notificación
                    loop.run_until_complete(send_notification(
                        db=background_db,
                        workspace_id=task_with_user.workspace_id,
                        category="users",
                        notification_type="ticket_closed",
                        recipient_email=task_with_user.user.email,
                        recipient_name=task_with_user.user.name,
                        template_vars=template_vars,
                        task_id=task_with_user.id
                    ))
                    logger.info(f"✅ Background notification sent for closed ticket {task_id} to user {task_with_user.user.name}")
                finally:
                    loop.close()
        finally:
            background_db.close()
            
    except Exception as e:
        logger.error(f"❌ Error sending background notification for ticket {task_id}: {str(e)}", exc_info=True)


def _send_assignment_notification_thread(task_id: int, request_origin: Optional[str] = None):
    """Enviar notificación de asignación en background thread"""
    try:
        import asyncio
        # Crear nueva sesión para background task
        background_db = SessionLocal()
        
        try:
            # Reload task
            task = background_db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return
                
            # Crear event loop para la función async
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Ejecutar la función async de notificación
                loop.run_until_complete(send_assignment_notification(background_db, task, request_origin))
                logger.info(f"✅ Background assignment notification sent for ticket {task_id}")
            finally:
                loop.close()
        finally:
            background_db.close()
            
    except Exception as e:
        logger.error(f"❌ Error sending background assignment notification for ticket {task_id}: {str(e)}", exc_info=True)


def _send_team_notification_thread(task_id: int, request_origin: Optional[str] = None):
    """Enviar notificación de equipo en background thread"""
    try:
        import asyncio
        # Crear nueva sesión para background task
        background_db = SessionLocal()
        
        try:
            # Reload task
            task = background_db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return
                
            # Crear event loop para la función async
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Ejecutar la función async de notificación
                loop.run_until_complete(send_team_notification(background_db, task, request_origin))
                logger.info(f"✅ Background team notification sent for ticket {task_id}")
            finally:
                loop.close()
        finally:
            background_db.close()
            
    except Exception as e:
        logger.error(f"❌ Error sending background team notification for ticket {task_id}: {str(e)}", exc_info=True)


def delete_task(db: Session, task_id: int) -> Optional[Task]:
    """Soft delete a task"""
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        return None
    task.is_deleted = True
    task.deleted_at = datetime.utcnow()
    
    db.commit()
    db.refresh(task)
    
    return task


def get_user_tasks(db: Session, user_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks for a specific user"""
    return db.query(Task).filter(
        Task.user_id == user_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


def get_assigned_tasks(db: Session, agent_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks assigned to a specific agent"""
    return db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


def get_team_tasks(db: Session, team_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks for a specific team"""
    return db.query(Task).filter(
        Task.team_id == team_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


async def send_assignment_notification(db: Session, task: Task, request_origin: Optional[str] = None):
    """
    Envía una notificación por correo al agente asignado a un ticket.
    Usa el mailbox específico del ticket si está disponible.
    """
    try:
        if not task.assignee_id or not task.assignee:
            logger.warning(f"No se pudo enviar notificación para el ticket {task.id}: No hay asignado")
            return

        # Intentar usar el mailbox específico del ticket primero
        preferred_mailbox = None
        preferred_token = None
        
        if task.mailbox_connection_id:
            # El ticket tiene un mailbox específico, intentar usarlo
            logger.info(f"Ticket {task.id} tiene mailbox específico ID: {task.mailbox_connection_id}")
            
            # Buscar el token válido para este mailbox específico
            mailbox_token_info = db.query(MailboxConnection, MicrosoftToken)\
                .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
                .filter(
                    MailboxConnection.id == task.mailbox_connection_id,
                    MailboxConnection.is_active == True,
                    MicrosoftToken.access_token.isnot(None)
                ).first()
            
            if mailbox_token_info:
                preferred_mailbox, preferred_token = mailbox_token_info
                logger.info(f"Usando mailbox específico del ticket: {preferred_mailbox.email}")
            else:
                logger.warning(f"No se encontró token válido para el mailbox específico del ticket {task.id}")

        # Si no hay mailbox específico o no tiene token válido, usar fallback
        if not preferred_mailbox or not preferred_token:
            logger.info(f"Buscando mailbox fallback para ticket {task.id}")
            admin_sender_info = db.query(Agent, MailboxConnection, MicrosoftToken)\
                .join(MailboxConnection, Agent.id == MailboxConnection.created_by_agent_id)\
                .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
                .filter(
                    Agent.workspace_id == task.workspace_id,
                    Agent.role.in_(['admin', 'manager']),
                    MailboxConnection.is_active == True,
                    MicrosoftToken.access_token.isnot(None)
                ).order_by(Agent.role.desc()).first()
            
            if not admin_sender_info:
                logger.warning(f"No hay administradores con buzón conectado para enviar notificación del ticket {task.id}")
                return
                
            admin, preferred_mailbox, preferred_token = admin_sender_info
            logger.info(f"Usando mailbox fallback: {preferred_mailbox.email}")

        # Determinar el origen de la solicitud
        if not request_origin:
            workspace_domain_info = db.query(Agent).filter(
                Agent.workspace_id == task.workspace_id,
                Agent.last_login_origin.isnot(None)
            ).order_by(Agent.last_login.desc()).first()
            
            if workspace_domain_info and workspace_domain_info.last_login_origin:
                request_origin = workspace_domain_info.last_login_origin
                logger.info(f"Usando último dominio de login para la notificación: {request_origin}")
            else:
                request_origin = settings.FRONTEND_URL
                logger.info(f"Usando dominio predeterminado para la notificación: {request_origin}")

        # Verificar y refrescar token si es necesario
        current_access_token = preferred_token.access_token
        if preferred_token.expires_at < datetime.utcnow():
            try:
                logger.info(f"Refrescando token para el buzón {preferred_mailbox.email}")
                graph_service = MicrosoftGraphService(db=db)
                refreshed_ms_token = await graph_service.refresh_token_async(preferred_token)
                current_access_token = refreshed_ms_token.access_token
            except Exception as e:
                logger.error(f"Error al refrescar token para enviar notificación: {e}")
                return

        # Enviar la notificación usando el mailbox correcto
        sent = await send_ticket_assignment_email(
            db=db,
            to_email=task.assignee.email,
            agent_name=task.assignee.name,
            ticket_id=task.id,
            ticket_title=task.title,
            sender_mailbox_email=preferred_mailbox.email,
            sender_mailbox_display_name=preferred_mailbox.display_name,  # Nuevo parámetro
            user_access_token=current_access_token,
            request_origin=request_origin
        )
        
        if sent:
            logger.info(f"Notificación enviada al agente {task.assignee.name} ({task.assignee.email}) para el ticket {task.id} desde {preferred_mailbox.email}")
        else:
            logger.error(f"Error al enviar notificación para el ticket {task.id} al agente {task.assignee.email}")
            
    except Exception as e:
        logger.error(f"Error inesperado al enviar notificación para el ticket {task.id}: {e}", exc_info=True)


async def send_team_notification(db: Session, task: Task, request_origin: Optional[str] = None):
    """
    Envía notificación a todos los miembros de un equipo cuando se crea un ticket 
    asignado al equipo pero sin agente específico asignado.
    """
    try:
        # Solo enviar si el ticket tiene team_id pero NO tiene assignee_id
        if not task.team_id or task.assignee_id:
            return
            
        # Verificar si las notificaciones de equipo están habilitadas
        from app.services.notification_service import is_team_notification_enabled
        if not is_team_notification_enabled(db, task.workspace_id):
            logger.info(f"Team notifications are disabled for workspace {task.workspace_id}, skipping notification for ticket {task.id}")
            return
            
        # Obtener todos los miembros del equipo
        from app.models.team import TeamMember
        team_members = db.query(TeamMember).join(Agent).filter(
            TeamMember.team_id == task.team_id,
            Agent.is_active == True,
            Agent.email.isnot(None),
            Agent.email != ""
        ).all()
        
        if not team_members:
            logger.info(f"No active team members found for team {task.team_id}")
            return
            
        # Obtener información del equipo
        from app.models.team import Team
        team = db.query(Team).filter(Team.id == task.team_id).first()
        team_name = team.name if team else f"Team {task.team_id}"
        
        logger.info(f"Sending team notification for ticket {task.id} to {len(team_members)} members of team '{team_name}'")
        
        # Obtener el primer mailbox disponible para enviar notificaciones
        from app.models.microsoft import MailboxConnection
        preferred_mailbox = db.query(MailboxConnection).filter(
            MailboxConnection.workspace_id == task.workspace_id,
            MailboxConnection.is_active == True
        ).first()
        
        if not preferred_mailbox:
            logger.error(f"No active mailbox found for workspace {task.workspace_id}")
            return
            
        # Obtener el token más reciente para el mailbox
        from app.models.microsoft import MicrosoftToken
        preferred_token = db.query(MicrosoftToken).filter(
            MicrosoftToken.mailbox_connection_id == preferred_mailbox.id
        ).order_by(MicrosoftToken.created_at.desc()).first()
        
        if not preferred_token:
            logger.error(f"No token found for mailbox {preferred_mailbox.email}")
            return
            
        current_access_token = preferred_token.access_token
        
        # Refrescar token si está expirado
        if preferred_token.expires_at < datetime.utcnow():
            try:
                logger.info(f"Refrescando token para el buzón {preferred_mailbox.email}")
                graph_service = MicrosoftGraphService(db=db)
                refreshed_ms_token = await graph_service.refresh_token_async(preferred_token)
                current_access_token = refreshed_ms_token.access_token
            except Exception as e:
                logger.error(f"Error al refrescar token para enviar notificación de equipo: {e}")
                return
        
        # Enviar notificación a cada miembro del equipo
        for team_member in team_members:
            try:
                sent = await send_team_ticket_notification_email(
                    db=db,
                    to_email=team_member.agent.email,
                    agent_name=team_member.agent.name,
                    team_name=team_name,
                    ticket_id=task.id,
                    ticket_title=task.title,
                    sender_mailbox_email=preferred_mailbox.email,
                    sender_mailbox_display_name=preferred_mailbox.display_name,
                    user_access_token=current_access_token,
                    request_origin=request_origin
                )
                
                if sent:
                    logger.info(f"Team notification sent to {team_member.agent.name} ({team_member.agent.email}) for ticket {task.id}")
                else:
                    logger.error(f"Failed to send team notification to {team_member.agent.email} for ticket {task.id}")
                    
            except Exception as e:
                logger.error(f"Error sending team notification to {team_member.agent.email}: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error inesperado al enviar notificaciones de equipo para el ticket {task.id}: {e}", exc_info=True)
