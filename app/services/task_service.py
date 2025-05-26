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
from app.services.email_service import send_ticket_assignment_email
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
    """Update a task"""
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        return None
    old_assignee_id = task.assignee_id
    old_status = task.status
    old_priority = task.priority

    update_data = task_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    db.refresh(task, attribute_names=['user', 'assignee', 'sent_from', 'sent_to', 'team', 'company', 'workspace', 'body', 'category']) 
    
    # Ejecutar workflows basados en los cambios realizados
    try:
        from app.services.workflow_service import WorkflowService
        context = {'ticket': task, 'old_values': {'assignee_id': old_assignee_id, 'status': old_status, 'priority': old_priority}}
        
        # Workflow general de actualización
        executed_workflows = WorkflowService.execute_workflows(
            db=db,
            trigger='ticket.updated',
            workspace_id=task.workspace_id,
            context=context
        )
        
        # Workflows específicos según el tipo de cambio
        if 'status' in update_data and old_status != task.status:
            executed_workflows.extend(WorkflowService.execute_workflows(
                db=db,
                trigger='ticket.status_changed',
                workspace_id=task.workspace_id,
                context=context
            ))
        
        if 'priority' in update_data and old_priority != task.priority:
            executed_workflows.extend(WorkflowService.execute_workflows(
                db=db,
                trigger='ticket.priority_changed',
                workspace_id=task.workspace_id,
                context=context
            ))
        
        if 'assignee_id' in update_data:
            if old_assignee_id != task.assignee_id:
                if task.assignee_id is not None:
                    executed_workflows.extend(WorkflowService.execute_workflows(
                        db=db,
                        trigger='ticket.assigned',
                        workspace_id=task.workspace_id,
                        context=context
                    ))
                else:
                    executed_workflows.extend(WorkflowService.execute_workflows(
                        db=db,
                        trigger='ticket.unassigned',
                        workspace_id=task.workspace_id,
                        context=context
                    ))
        
        if executed_workflows:
            logger.info(f"Executed workflows for ticket update {task.id}: {executed_workflows}")
            
    except Exception as e:
        logger.error(f"Error executing workflows for ticket update {task.id}: {str(e)}")
    
    # Send assignment notification if the assignee has changed
    if 'assignee_id' in update_data and old_assignee_id != task.assignee_id and task.assignee_id is not None:
        asyncio.create_task(send_assignment_notification(db, task, request_origin))
    
    # Send notification when ticket status changes to Closed/Resolved
    if 'status' in update_data and old_status != task.status and task.status == 'Closed':
        try:
            from app.services.notification_service import send_notification
            
            # Si el ticket tiene un usuario, enviarle una notificación
            # Solo se envía cuando el ticket se cierra (resuelve)
            if task.user and task.user.email:
                # Preparar variables de plantilla
                template_vars = {
                    "user_name": task.user.name,
                    "ticket_id": task.id,
                    "ticket_title": task.title
                }
                
                # Enviar la notificación de forma asíncrona
                asyncio.create_task(
                    send_notification(
                        db=db,
                        workspace_id=task.workspace_id,
                        category="users",
                        notification_type="ticket_resolved",
                        recipient_email=task.user.email,
                        recipient_name=task.user.name,
                        template_vars=template_vars,
                        task_id=task.id
                    )
                )
                logger.info(f"Notification queued for resolved ticket {task.id} to user {task.user.name}")
        except Exception as e:
            logger.error(f"Error sending resolved ticket notification for task {task.id}: {str(e)}", exc_info=True)
    
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


async def send_assignment_notification(db: Session, task: Task, request_origin: Optional[str] = None):
    """
    Envía una notificación por correo al agente asignado a un ticket.
    """
    try:

        if not task.assignee_id or not task.assignee:
            logger.warning(f"No se pudo enviar notificación para el ticket {task.id}: No hay asignado")
            return
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
        
        admin, mailbox_connection, ms_token = admin_sender_info
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
        current_access_token = ms_token.access_token
        if ms_token.expires_at < datetime.utcnow():
            try:
                logger.info(f"Refrescando token para el buzón {mailbox_connection.email}")
                graph_service = MicrosoftGraphService(db=db)
                refreshed_ms_token = await graph_service.refresh_token_async(ms_token)
                current_access_token = refreshed_ms_token.access_token
            except Exception as e:
                logger.error(f"Error al refrescar token para enviar notificación: {e}")
                return
        sent = await send_ticket_assignment_email(
            db=db,
            to_email=task.assignee.email,
            agent_name=task.assignee.name,
            ticket_id=task.id,
            ticket_title=task.title,
            sender_mailbox_email=mailbox_connection.email,
            user_access_token=current_access_token,
            request_origin=request_origin
        )
        
        if sent:
            logger.info(f"Notificación enviada al agente {task.assignee.name} ({task.assignee.email}) para el ticket {task.id}")
        else:
            logger.error(f"Error al enviar notificación para el ticket {task.id} al agente {task.assignee.email}")
    
    except Exception as e:
        logger.error(f"Error inesperado al enviar notificación para el ticket {task.id}: {e}", exc_info=True)


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
