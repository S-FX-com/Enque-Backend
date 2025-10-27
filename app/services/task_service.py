from typing import List, Optional, Dict, Any, Tuple
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.future import select
from datetime import datetime
import threading
import re
import asyncio
import logging
from uuid import UUID

from app.models.task import Task, TicketBody
from app.models.microsoft import EmailTicketMapping
from app.schemas.task import TicketCreate, TicketUpdate
from app.schemas.microsoft import EmailInfo
from app.utils.logger import logger, log_important
from app.database.session import AsyncSessionLocal, get_background_db_session
from app.core.exceptions import DatabaseException, MicrosoftAPIException
from app.models.agent import Agent
from app.models.microsoft import MailboxConnection, MicrosoftToken
from app.core.config import settings
from app.services.email_service import send_ticket_assignment_email, send_team_ticket_notification_email
from app.services.microsoft_service import MicrosoftGraphService


def _run_async_in_new_loop(coro_func, *args):
    """
    Wrapper to run a coroutine in a new thread with its own event loop.
    This is a synchronous function intended to be the target of a threading.Thread.
    """
    try:
        asyncio.run(coro_func(*args))
    except Exception as e:
        # Using a generic logger as this is a top-level function
        logging.getLogger(__name__).error(f"Error in background task {coro_func.__name__}: {e}", exc_info=True)


async def get_tasks(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get all tasks"""
    stmt = select(Task).options(joinedload(Task.user)).filter(Task.is_deleted == False).order_by(Task.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_task_by_id(db: AsyncSession, task_id: int) -> Optional[Dict[str, Any]]:
    """Get a task by ID with email info if available"""
    stmt = select(Task).filter(Task.id == task_id, Task.is_deleted == False)
    result = await db.execute(stmt)
    task = result.scalars().first()
    if not task:
        return None
    
    stmt = select(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task.id)
    result = await db.execute(stmt)
    email_mapping = result.scalars().first()
    
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


async def create_task(db: AsyncSession, task_in: TicketCreate, current_user_id: int = None) -> Task: 
    """Create a new task"""
    task_data = task_in.dict()

    if not task_data.get('sent_from_id') and current_user_id:
        task_data['sent_from_id'] = current_user_id
    
    # Initialize last_update when creating new task
    if 'last_update' not in task_data:
        task_data['last_update'] = datetime.utcnow()
    
    task = Task(**task_data)
    db.add(task)
    await db.commit()
    await db.refresh(task) 
    await db.refresh(task, attribute_names=['user']) 
    
    # TODO: Refactor WorkflowService to be async
    # For now, we run it synchronously but this will block the event loop.
    try:
        from app.services.workflow_service import WorkflowService
        context = {'ticket': task}
        # This is a synchronous call and will block. It needs to be refactored.
        executed_workflows = await WorkflowService.execute_workflows(
            db=db, # Passing async session to sync function, might need adjustment
            trigger='ticket.created',
            workspace_id=task.workspace_id,
            context=context
        )
        if executed_workflows:
            logger.info(f"Executed workflows for ticket creation {task.id}: {executed_workflows}")
    except Exception as e:
        logger.error(
            f"Error executing workflows for ticket creation {task.id}: {e}",
            extra={"task_id": task.id, "workspace_id": task.workspace_id, "trigger": "ticket.created"},
            exc_info=True
        )
    return task

async def _mark_email_read_bg(task_id: int):
    """Mark email as read in the background using a new DB session."""
    async with AsyncSessionLocal() as db:
        try:
            from app.services.microsoft_service import mark_email_as_read_by_task_id
            # Assuming mark_email_as_read_by_task_id will also be refactored to be async
            await mark_email_as_read_by_task_id(db, task_id)
        except (DatabaseException, MicrosoftAPIException) as e:
            logger.error(
                f"Error in background email marking for ticket #{task_id}: {e}",
                extra={"task_id": task_id, "error_type": type(e).__name__},
                exc_info=True
            )
        except Exception as e:
            logger.error(
                f"Unexpected error in background email marking for ticket #{task_id}: {e}",
                extra={"task_id": task_id},
                exc_info=True
            )


async def update_task(db: AsyncSession, task_id: int, task_in: TicketUpdate, request_origin: Optional[str] = None) -> Optional[Dict[str, Any]]: 
    """Update a task - optimizada para respuesta rápida"""
    stmt = select(Task).filter(Task.id == task_id, Task.is_deleted == False)
    result = await db.execute(stmt)
    task = result.scalars().first()
    if not task:
        return None
    old_assignee_id = task.assignee_id
    old_status = task.status
    old_priority = task.priority

    update_data = task_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    # ✅ OPTIMIZACIÓN: Commit inmediato para respuesta rápida
    await db.commit()
    await db.refresh(task)
    await db.refresh(task, attribute_names=['user', 'assignee', 'sent_from', 'sent_to', 'team', 'company', 'workspace', 'body', 'category']) 
    
    # ✅ OPTIMIZACIÓN: Ejecutar procesos pesados en background usando threading.Thread
    try:
        # Ejecutar workflows en un hilo separado
        threading.Thread(target=_run_async_in_new_loop, args=(_execute_workflows_thread, task_id, task.workspace_id, old_assignee_id, old_status, old_priority, update_data)).start()

        # Las notificaciones también pueden ser pesadas, las movemos a hilos
        if 'assignee_id' in update_data and old_assignee_id != task.assignee_id and task.assignee_id is not None:
            threading.Thread(target=_run_async_in_new_loop, args=(_send_assignment_notification_thread, task_id, request_origin)).start()
        
        if ('team_id' in update_data or 'assignee_id' in update_data) and task.team_id and not task.assignee_id:
            threading.Thread(target=_run_async_in_new_loop, args=(_send_team_notification_thread, task_id, request_origin)).start()
        
        if 'status' in update_data and old_status != task.status and task.status == 'Closed':
            threading.Thread(target=_run_async_in_new_loop, args=(_send_closure_notification_thread, task_id)).start()
            
        logger.info(f"🚀 Background workflow processes queued for ticket {task_id}")
            
    except Exception as e:
        logger.error(
            f"Error starting background processes for ticket {task_id}: {e}",
            extra={"task_id": task_id},
            exc_info=True
        )
    
    # ✅ RESPUESTA RÁPIDA: Procesar solo la información esencial para la respuesta
    stmt = select(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task.id)
    result = await db.execute(stmt)
    email_mapping = result.scalars().first()
    
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


async def _execute_workflows_thread(task_id: int, workspace_id: int, old_assignee_id, old_status, old_priority, update_data):
    """Ejecutar workflows en background"""
    try:
        from app.services.workflow_service import WorkflowService
        async with get_background_db_session() as background_db:
            stmt = select(Task).filter(Task.id == task_id)
            result = await background_db.execute(stmt)
            task = result.scalars().first()
            if not task:
                return
                
            context = {'ticket': task, 'old_values': {'assignee_id': old_assignee_id, 'status': old_status, 'priority': old_priority}}
            executed_workflows = []
            
            # Execute workflows for ticket updates
            executed_workflows.extend(await WorkflowService.execute_workflows(
                db=background_db, trigger='ticket.updated', workspace_id=workspace_id, context=context
            ))
            if 'status' in update_data and old_status != task.status:
                executed_workflows.extend(await WorkflowService.execute_workflows(
                    db=background_db, trigger='ticket.status_changed', workspace_id=workspace_id, context=context
                ))
            if 'priority' in update_data and old_priority != task.priority:
                executed_workflows.extend(await WorkflowService.execute_workflows(
                    db=background_db, trigger='ticket.priority_changed', workspace_id=workspace_id, context=context
                ))
            if 'assignee_id' in update_data:
                if old_assignee_id != task.assignee_id:
                    if task.assignee_id is not None:
                        executed_workflows.extend(await WorkflowService.execute_workflows(
                            db=background_db, trigger='ticket.assigned', workspace_id=workspace_id, context=context
                        ))
                    else:
                        executed_workflows.extend(await WorkflowService.execute_workflows(
                            db=background_db, trigger='ticket.unassigned', workspace_id=workspace_id, context=context
                        ))
            
            if executed_workflows:
                logger.info(f"✅ Background workflows executed for ticket {task_id}: {executed_workflows}")
                await background_db.commit()
                
    except Exception as e:
        logger.error(
            f"Error in background workflows for ticket {task_id}: {e}",
            extra={"task_id": task_id, "workspace_id": workspace_id},
            exc_info=True
        )


async def _send_closure_notification_thread(task_id: int):
    """Enviar notificación de cierre en background"""
    try:
        from app.services.notification_service import send_notification
        async with get_background_db_session() as background_db:
            stmt = select(Task).options(joinedload(Task.user)).filter(Task.id == task_id)
            result = await background_db.execute(stmt)
            task_with_user = result.scalars().first()
            
            if task_with_user and task_with_user.user and task_with_user.user.email:
                template_vars = {
                    "user_name": task_with_user.user.name,
                    "ticket_id": task_with_user.id,
                    "ticket_title": task_with_user.title
                }
                await send_notification(
                    db=background_db,
                    workspace_id=task_with_user.workspace_id,
                    category="users",
                    notification_type="ticket_closed",
                    recipient_email=task_with_user.user.email,
                    recipient_name=task_with_user.user.name,
                    template_vars=template_vars,
                    task_id=task_with_user.id
                )
                logger.info(f"✅ Background notification sent for closed ticket {task_id} to user {task_with_user.user.name}")
    except Exception as e:
        logger.error(
            f"Error sending background closure notification for ticket {task_id}: {e}",
            extra={"task_id": task_id},
            exc_info=True
        )


async def _send_assignment_notification_thread(task_id: int, request_origin: Optional[str] = None):
    """Enviar notificación de asignación en background"""
    try:
        async with get_background_db_session() as background_db:
            stmt = select(Task).options(joinedload(Task.assignee)).filter(Task.id == task_id)
            result = await background_db.execute(stmt)
            task = result.scalars().first()
            if not task:
                return
            await send_assignment_notification(background_db, task, request_origin)
            logger.info(f"✅ Background assignment notification sent for ticket {task_id}")
    except Exception as e:
        logger.error(
            f"Error sending background assignment notification for ticket {task_id}: {e}",
            extra={"task_id": task_id},
            exc_info=True
        )


async def _send_team_notification_thread(task_id: int, request_origin: Optional[str] = None):
    """Enviar notificación de equipo en background"""
    try:
        async with get_background_db_session() as background_db:
            stmt = select(Task).filter(Task.id == task_id)
            result = await background_db.execute(stmt)
            task = result.scalars().first()
            if not task:
                return
            await send_team_notification(background_db, task, request_origin)
            logger.info(f"✅ Background team notification sent for ticket {task_id}")
    except Exception as e:
        logger.error(
            f"Error sending background team notification for ticket {task_id}: {e}",
            extra={"task_id": task_id},
            exc_info=True
        )


async def delete_task(db: AsyncSession, task_id: int) -> Optional[Task]:
    """Soft delete a task"""
    stmt = select(Task).filter(Task.id == task_id, Task.is_deleted == False)
    result = await db.execute(stmt)
    task = result.scalars().first()
    if not task:
        return None
    task.is_deleted = True
    task.deleted_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(task)
    
    return task


async def get_user_tasks(db: AsyncSession, user_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks for a specific user"""
    stmt = select(Task).filter(
        Task.user_id == user_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_assigned_tasks(db: AsyncSession, agent_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks assigned to a specific agent"""
    stmt = select(Task).filter(
        Task.assignee_id == agent_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_team_tasks(db: AsyncSession, team_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks for a specific team"""
    stmt = select(Task).filter(
        Task.team_id == team_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def send_assignment_notification(db: AsyncSession, task: Task, request_origin: Optional[str] = None):
    """
    Envía una notificación por correo al agente asignado a un ticket.
    Usa el mailbox específico del ticket si está disponible.
    """
    try:
        if not task.assignee_id:
            logger.warning(f"Could not send notification for the ticket {task.id}")
            return

        preferred_mailbox = None
        preferred_token = None
        
        if task.mailbox_connection_id:
            logger.info(f"Ticket {task.id} tiene mailbox específico ID: {task.mailbox_connection_id}")
            stmt = select(MailboxConnection, MicrosoftToken)\
                .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
                .filter(
                    MailboxConnection.id == task.mailbox_connection_id,
                    MailboxConnection.is_active == True,
                    MicrosoftToken.access_token.isnot(None)
                )
            result = await db.execute(stmt)
            mailbox_token_info = result.first()
            
            if mailbox_token_info:
                preferred_mailbox, preferred_token = mailbox_token_info
                logger.info(f"Usando mailbox específico del ticket: {preferred_mailbox.email}")
            else:
                logger.warning(f"No se encontró token válido para el mailbox específico del ticket {task.id}")

        if not preferred_mailbox or not preferred_token:
            logger.info(f"Buscando mailbox fallback para ticket {task.id}")
            stmt = select(Agent, MailboxConnection, MicrosoftToken)\
                .join(MailboxConnection, Agent.id == MailboxConnection.created_by_agent_id)\
                .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
                .filter(
                    Agent.workspace_id == task.workspace_id,
                    Agent.role.in_(['admin', 'manager']),
                    MailboxConnection.is_active == True,
                    MicrosoftToken.access_token.isnot(None)
                ).order_by(Agent.role.desc())
            result = await db.execute(stmt)
            admin_sender_info = result.first()
            
            if not admin_sender_info:
                logger.warning(f"No hay administradores con buzón conectado para enviar notificación del ticket {task.id}")
                return
                
            admin, preferred_mailbox, preferred_token = admin_sender_info
            logger.info(f"Usando mailbox fallback: {preferred_mailbox.email}")

        if not request_origin:
            stmt = select(Agent).filter(
                Agent.workspace_id == task.workspace_id,
                Agent.last_login_origin.isnot(None)
            ).order_by(Agent.last_login.desc())
            result = await db.execute(stmt)
            workspace_domain_info = result.scalars().first()
            
            if workspace_domain_info and workspace_domain_info.last_login_origin:
                request_origin = workspace_domain_info.last_login_origin
                logger.info(f"Usando último dominio de login para la notificación: {request_origin}")
            else:
                request_origin = settings.FRONTEND_URL
                logger.info(f"Usando dominio predeterminado para la notificación: {request_origin}")

        current_access_token = preferred_token.access_token
        if preferred_token.expires_at < datetime.utcnow():
            try:
                logger.info(f"Refrescando token para el buzón {preferred_mailbox.email}")
                graph_service = MicrosoftGraphService(db=db)
                refreshed_ms_token = await graph_service.refresh_token_async(preferred_token)
                current_access_token = refreshed_ms_token.access_token
            except Exception as e:
                logger.error(f"Error refreshing token for notification: {e}", exc_info=True)
                return

        sent = await send_ticket_assignment_email(
            db=db,
            to_email=task.assignee.email,
            agent_name=task.assignee.name,
            ticket_id=task.id,
            ticket_title=task.title,
            sender_mailbox_email=preferred_mailbox.email,
            sender_mailbox_display_name=preferred_mailbox.display_name,
            user_access_token=current_access_token,
            request_origin=request_origin
        )
        
        if sent:
            logger.info(f"Notificación enviada al agente {task.assignee.name} ({task.assignee.email}) para el ticket {task.id} desde {preferred_mailbox.email}")
        else:
            logger.error(f"Error al enviar notificación para el ticket {task.id} al agente {task.assignee.email}")
            
    except Exception as e:
        logger.error(f"Unexpected error sending assignment notification for ticket {task.id}: {e}", exc_info=True)


async def send_team_notification(db: AsyncSession, task: Task, request_origin: Optional[str] = None):
    """
    Envía notificación a todos los miembros de un equipo cuando se crea un ticket 
    asignado al equipo pero sin agente específico asignado.
    """
    try:
        if not task.team_id or task.assignee_id:
            return
            
        from app.services.notification_service import is_team_notification_enabled
        if not await is_team_notification_enabled(db, task.workspace_id): # Assuming this becomes async
            logger.info(f"Team notifications are disabled for workspace {task.workspace_id}, skipping notification for ticket {task.id}")
            return
            
        from app.models.team import TeamMember
        stmt = select(TeamMember).join(Agent).filter(
            TeamMember.team_id == task.team_id,
            Agent.is_active == True,
            Agent.email.isnot(None),
            Agent.email != ""
        )
        result = await db.execute(stmt)
        team_members = result.scalars().all()
        
        if not team_members:
            logger.info(f"No active team members found for team {task.team_id}")
            return
            
        from app.models.team import Team
        stmt = select(Team).filter(Team.id == task.team_id)
        result = await db.execute(stmt)
        team = result.scalars().first()
        team_name = team.name if team else f"Team {task.team_id}"
        
        logger.info(f"Sending team notification for ticket {task.id} to {len(team_members)} members of team '{team_name}'")
        
        from app.models.microsoft import MailboxConnection
        stmt = select(MailboxConnection).filter(
            MailboxConnection.workspace_id == task.workspace_id,
            MailboxConnection.is_active == True
        )
        result = await db.execute(stmt)
        preferred_mailbox = result.scalars().first()
        
        if not preferred_mailbox:
            logger.error(f"No active mailbox found for workspace {task.workspace_id}")
            return
            
        from app.models.microsoft import MicrosoftToken
        stmt = select(MicrosoftToken).filter(
            MicrosoftToken.mailbox_connection_id == preferred_mailbox.id
        ).order_by(MicrosoftToken.created_at.desc())
        result = await db.execute(stmt)
        preferred_token = result.scalars().first()
        
        if not preferred_token:
            logger.error(f"No token found for mailbox {preferred_mailbox.email}")
            return
            
        current_access_token = preferred_token.access_token
        
        if preferred_token.expires_at < datetime.utcnow():
            try:
                logger.info(f"Refrescando token para el buzón {preferred_mailbox.email}")
                graph_service = MicrosoftGraphService(db=db)
                refreshed_ms_token = await graph_service.refresh_token_async(preferred_token)
                current_access_token = refreshed_ms_token.access_token
            except Exception as e:
                logger.error(f"Error refreshing token for team notification: {e}", exc_info=True)
                return
        
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
                logger.error(f"Error sending team notification to {team_member.agent.email}: {e}", exc_info=True)
                
    except Exception as e:
        logger.error(f"Unexpected error sending team notifications for ticket {task.id}: {e}", exc_info=True)
