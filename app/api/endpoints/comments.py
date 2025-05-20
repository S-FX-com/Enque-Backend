from typing import Any, List, Dict
from datetime import datetime # Import datetime
import asyncio
from threading import Thread

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.orm import Session, joinedload # Re-import joinedload
from pydantic import BaseModel

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
# Use aliases for clarity if needed, or use original names
from app.models.agent import Agent as AgentModel
from app.models.comment import Comment as CommentModel
from app.models.task import Task as TaskModel # Keep TaskModel alias
from app.models.microsoft import MailboxConnection # Import MailboxConnection
# CommentSchema now includes the agent object due to previous edit
from app.schemas.comment import Comment as CommentSchema, CommentCreate, CommentUpdate
from app.schemas.task import TaskStatus, Task as TaskSchema, TicketWithDetails # Import Task schema and detailed schema
from app.services.microsoft_service import get_microsoft_service, MicrosoftGraphService
from app.services.task_service import send_assignment_notification
from app.utils.logger import logger
from app.core.config import settings

router = APIRouter()

# Create a response model for the comment creation endpoint
class CommentResponseModel(BaseModel):
    comment: CommentSchema
    task: TicketWithDetails
    assignee_changed: bool

    model_config = {
        "from_attributes": True
    }


@router.get("/tasks/{task_id}/comments", response_model=List[CommentSchema])
async def read_comments(
    task_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Retrieve all comments for a task, ensuring the task belongs to the user's workspace.
    Includes agent details for each comment.
    """
    # Verificar que la tarea existe y pertenece al workspace del usuario (using model alias)
    task = db.query(TaskModel).filter(
        TaskModel.id == task_id,
        TaskModel.workspace_id == current_user.workspace_id, # Check workspace
        TaskModel.is_deleted == False
    ).first()

    if not task:
        # Log corrected message
        logger.error(f"Endpoint read_comments: Query failed to find active Task with id={task_id} in workspace {current_user.workspace_id}. Raising 404.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found", # Keep detail generic for security
        )

    # Query comments and explicitly load the 'agent' relationship
    # because the updated CommentSchema now expects it.
    comments_orm = db.query(CommentModel).options(
        joinedload(CommentModel.agent), # Eager load agente
        joinedload(CommentModel.attachments) # Eager load adjuntos
    ).filter(
        CommentModel.ticket_id == task_id # Use correct column name
    )

    # Filter out private comments if the user is not an agent or admin
    #if current_user.role != "admin":
    #    comments_orm = comments_orm.filter(CommentModel.is_private == False)

    comments_orm = comments_orm.order_by(
        CommentModel.created_at.asc()  # Order ascending for conversation flow
    ).offset(skip).limit(limit).all()

    # Return the ORM objects directly. Pydantic's from_attributes=True
    return comments_orm


@router.post("/tasks/{task_id}/comments", response_model=CommentResponseModel)
async def create_comment(
    task_id: int,
    comment_in: CommentCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Create a new comment on a task.
    The comment can be private (visible only to agents) or public.
    """
    
    # Fetch the task ensuring it belongs to the user's workspace
    task = db.query(TaskModel).filter(
        TaskModel.id == task_id,
        TaskModel.workspace_id == current_user.workspace_id,
        TaskModel.is_deleted == False
    ).first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    # Verificar si hay un cambio de assignee
    previous_assignee_id = task.assignee_id
    assignee_changed = False
    
    # Para respuestas externas, auto-establecer status="With User" si no es "Closed"
    if not comment_in.is_private and task.status != "Closed":
        task.status = "With User"
        db.add(task)
    
    # Lógica para asignar ticket al agente que comenta (si no está asignado)
    if task.assignee_id is None and not comment_in.preserve_assignee:
        # Solo asignar al usuario actual si no tiene un assignee_id explícito en request
        # y si no es una carga de adjunto (is_attachment_upload)
        if comment_in.assignee_id is None and not comment_in.is_attachment_upload:
            task.assignee_id = current_user.id
            assignee_changed = True
        # Si se proporciona explícitamente un assignee_id, usar ese
        elif comment_in.assignee_id is not None:
            task.assignee_id = comment_in.assignee_id
            assignee_changed = previous_assignee_id != comment_in.assignee_id
    
    # Si hay un assignee_id explícito (y no estamos preservando el actual)
    elif comment_in.assignee_id is not None and not comment_in.preserve_assignee:
        task.assignee_id = comment_in.assignee_id
        assignee_changed = previous_assignee_id != comment_in.assignee_id
    
    # Update last_update field on the task
    task.last_update = datetime.utcnow()  # Use import
    db.add(task)

    # Create the comment
    comment = CommentModel(
        ticket_id=task_id,
        agent_id=current_user.id,
        workspace_id=current_user.workspace_id,
        content=comment_in.content,
        is_private=comment_in.is_private
    )
    db.add(comment)
    
    # Procesar attachment_ids si están presentes
    processed_attachment_ids = []
    if comment_in.attachment_ids:
        from app.models.ticket_attachment import TicketAttachment
        
        logger.info(f"Processing {len(comment_in.attachment_ids)} attachment IDs for comment ID {comment.id}: {comment_in.attachment_ids}")
        
        # Commit para asegurar que tengamos un comment ID válido antes de asociar adjuntos
        db.commit()
        db.refresh(comment)
        
        # Buscar y actualizar attachments
        for attachment_id in comment_in.attachment_ids:
            attachment = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
            if attachment:
                # Verificar si el adjunto está en un comentario temporal (placeholder)
                prev_comment = db.query(CommentModel).filter(CommentModel.id == attachment.comment_id).first()
                if prev_comment and prev_comment.content == "TEMP_ATTACHMENT_PLACEHOLDER":
                    # Actualizar la relación del adjunto al nuevo comentario
                    attachment.comment_id = comment.id
                    db.add(attachment)
                    processed_attachment_ids.append(attachment_id)
                    logger.info(f"Adjunto {attachment_id} asociado al comentario {comment.id}")
                else:
                    logger.warning(f"Adjunto {attachment_id} ya está asociado a un comentario no temporal")
            else:
                logger.warning(f"Adjunto {attachment_id} no encontrado al crear el comentario {comment.id}")
    
    # Si es una respuesta externa, procesar el email
    if not comment_in.is_private and comment_in.content and len(comment_in.content) > 0:
        # Si hay un reply_to_email especificado, se debe enviar a ese correo
        # En caso contrario, se determina a partir del ticket
        if not comment_in.is_attachment_upload:
            from app.core.config import settings
            db_path = settings.DATABASE_URI

            # Verificar si task tiene email_mappings o mailbox_connection_id
            email_from_mailbox = True
            if hasattr(task, 'mailbox_connection_id') and task.mailbox_connection_id:
                email_from_mailbox = True
                logger.info(f"Task {task_id} has mailbox_connection_id {task.mailbox_connection_id}. Will send reply.")
            elif hasattr(task, 'email_mappings') and task.email_mappings:
                email_from_mailbox = True
                logger.info(f"Task {task_id} has email_mappings. Will send reply.")
            else:
                # Verificar directamente en la base de datos
                from app.models.microsoft import EmailTicketMapping
                email_mapping = db.query(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task_id).first()
                if email_mapping:
                    email_from_mailbox = True
                    logger.info(f"Task {task_id} has email mapping in database. Will send reply.")
                else:
                    email_from_mailbox = False
                    logger.info(f"Task {task_id} has no email mapping or mailbox connection. Will send notification.")

            # Add task to background tasks for email sending
            try:
                # Iniciar un thread para procesar el email en segundo plano
                thread = Thread(
                    target=send_email_in_background,
                    args=(
                        task_id,
                        comment.id,
                        comment.content,
                        current_user.id,
                        current_user.email,
                        current_user.name,
                        comment.is_private,
                        processed_attachment_ids,
                        db_path
                    )
                )
                thread.daemon = True
                thread.start()
                logger.info(f"Started background thread for email sending for comment {comment.id} on task {task_id}")
            except Exception as e:
                logger.error(f"Error queuing email for task {task_id}: {e}", exc_info=True)
    
    db.commit()
    db.refresh(task)  # Ensure the task is fresh
    db.refresh(comment)  # Ensure comment is fresh with relationships
    
    # Si hubo un cambio de asignación y hay un nuevo asignado, enviar la notificación
    if assignee_changed and task.assignee_id is not None:
        # Obtener la URL de origen para usar el subdominio correcto
        origin_url = None
        
        # 1. Intenta obtener origin de los headers
        origin_header = request.headers.get("origin")
        if origin_header:
            origin_url = origin_header
            logger.info(f"Using origin header for notification: {origin_url}")
        
        # 2. Si no hay origin en headers, intenta obtener host y esquema
        elif request.headers.get("host"):
            scheme = request.headers.get("x-forwarded-proto", "https")
            host = request.headers.get("host")
            origin_url = f"{scheme}://{host}"
            logger.info(f"Constructed origin from host header: {origin_url}")
        
        # 3. Si todo falla, usa la URL frontend de settings
        if not origin_url:
            origin_url = settings.FRONTEND_URL
            logger.info(f"Using settings.FRONTEND_URL as fallback: {origin_url}")
            
        # Lanzar la tarea en segundo plano
        asyncio.create_task(send_assignment_notification(db, task, request_origin=origin_url))
    
    # Ensure all necessary relationships are eagerly loaded
    db.refresh(task, attribute_names=['user', 'assignee', 'sent_from', 'sent_to', 'team', 'company', 'workspace', 'body', 'category'])
    db.refresh(comment, attribute_names=['agent', 'ticket', 'attachments'])
    
    # Return the new comment in the response
    return CommentResponseModel(
        comment=comment,
        task=task,
        assignee_changed=assignee_changed
    )


@router.get("/comments/{comment_id}", response_model=CommentSchema)
async def read_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Get comment by ID, ensuring it belongs to the user's workspace.
    """
    # Load agent relationship as the response model includes it
    comment = db.query(CommentModel).options(
        joinedload(CommentModel.agent)
    ).filter(
        CommentModel.id == comment_id
    ).first()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )
    # Check workspace access
    if comment.workspace_id != current_user.workspace_id:
         raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, # Treat as not found for security
            detail="Comment not found" # Remove duplicated detail argument
        )
    # Correct indentation for the return statement
    return comment


@router.put("/comments/{comment_id}", response_model=CommentSchema)
async def update_comment(
    comment_id: int,
    comment_in: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Update a comment, ensuring it belongs to the user's workspace.
    """
    # Load agent relationship as the response model includes it
    comment = db.query(CommentModel).options(
        joinedload(CommentModel.agent)
    ).filter(
        CommentModel.id == comment_id
    ).first()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )

    # Verificar que el agente actual es el propietario del comentario o es admin
    # Corrected: Check against agent_id, not user_id
    if comment.agent_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this comment",
        )

    # Check if the comment belongs to the current user's workspace before updating
    # Although agent check above might suffice, this adds an explicit layer.
    if comment.workspace_id != current_user.workspace_id:
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update comment from another workspace",
        )

    # Actualizar el comentario
    update_data = comment_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(comment, field, value)
    
    db.commit()
    db.refresh(comment)
    
    return comment


@router.delete("/comments/{comment_id}", response_model=CommentSchema)
async def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Delete a comment, ensuring it belongs to the user's workspace.
    """
    # No need to load agent for delete, just find the comment
    comment = db.query(CommentModel).filter(CommentModel.id == comment_id).first()
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )

    # Verificar que el agente actual es el propietario del comentario o es admin
    # Corrected: Check against agent_id, not user_id
    if comment.agent_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to delete this comment",
        )

    # Check if the comment belongs to the current user's workspace before deleting
    if comment.workspace_id != current_user.workspace_id:
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete comment from another workspace",
        )

    db.delete(comment)
    db.commit()
    
    return comment

# Función para manejar el envío de correos en segundo plano
def send_email_in_background(
    task_id: int, 
    comment_id: int, 
    comment_content: str, 
    agent_id: int,
    agent_email: str,
    agent_name: str,
    is_private: bool,
    processed_attachment_ids: list,
    db_path: str
):
    """
    Función para enviar correos electrónicos en segundo plano.
    Se ejecuta en un thread separado para no bloquear la respuesta API.
    """
    import time
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, joinedload
    from app.models.task import Task as TaskModel
    from app.models.agent import Agent as AgentModel
    from app.models.microsoft import MailboxConnection
    from app.services.microsoft_service import get_microsoft_service
    
    # Crear una nueva sesión de base de datos
    engine = create_engine(db_path)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        logger.info(f"[BACKGROUND] Iniciando envío de correo para comment_id: {comment_id} en task_id: {task_id}")
        
        # Re-crear el objeto Agent
        agent = db.query(AgentModel).filter(AgentModel.id == agent_id).first()
        if not agent:
            logger.error(f"[BACKGROUND] Agent {agent_id} no encontrado en base de datos")
            return
            
        # Skip for private comments
        if is_private:
            logger.info(f"[BACKGROUND] Skipping email for private comment {comment_id}")
            return
            
        # Re-fetch task with user relationship loaded to get recipient email if needed
        task_with_user = db.query(TaskModel).options(
            joinedload(TaskModel.user)
        ).filter(TaskModel.id == task_id).first()

        if not task_with_user:
            logger.error(f"[BACKGROUND] Task {task_id} not found when attempting to send email for comment {comment_id}.")
            return
        elif task_with_user.mailbox_connection_id:
            # Task originated from email, send a reply
            logger.info(f"[BACKGROUND] Task {task_id} originated from email. Attempting to send comment ID {comment_id} as reply with {len(processed_attachment_ids)} attachments.")
            microsoft_service = get_microsoft_service(db)
            microsoft_service.send_reply_email(task_id=task_id, reply_content=comment_content, agent=agent, attachment_ids=processed_attachment_ids)
        else:
            # Task was created manually, send a new email notification
            logger.info(f"[BACKGROUND] Task {task_id} was manual. Attempting to send comment ID {comment_id} as new email notification.")
            if not task_with_user.user or not task_with_user.user.email:
                logger.warning(f"[BACKGROUND] Cannot send notification for comment {comment_id} on task {task_id}: Task user or user email is missing.")
                return
            
            recipient_email = task_with_user.user.email
            # Find an active mailbox for the workspace to send from
            sender_mailbox_conn = db.query(MailboxConnection).filter(
                MailboxConnection.workspace_id == task_with_user.workspace_id,
                MailboxConnection.is_active == True
            ).first()

            if not sender_mailbox_conn:
                logger.warning(f"[BACKGROUND] Cannot send notification for comment {comment_id} on task {task_id}: No active sender mailbox found for workspace {task_with_user.workspace_id}.")
                return
            
            sender_mailbox = sender_mailbox_conn.email
            subject = f"New comment on ticket #{task_id}: {task_with_user.title}"
            html_body = f"<p><strong>{agent_name} commented:</strong></p>{comment_content}"

            microsoft_service = get_microsoft_service(db)
            logger.info(f"[BACKGROUND] Sending new email notification for comment {comment_id} from {sender_mailbox} to {recipient_email} with {len(processed_attachment_ids)} attachments")
            email_sent = microsoft_service.send_new_email(
                mailbox_email=sender_mailbox,
                recipient_email=recipient_email,
                subject=subject,
                html_body=html_body,
                attachment_ids=processed_attachment_ids,
                task_id=task_id  # Pass the task ID to include in the subject
            )
            if not email_sent:
                logger.error(f"[BACKGROUND] Failed to send new email notification for comment {comment_id} on task {task_id}")
            else:
                logger.info(f"[BACKGROUND] Successfully sent new email notification for comment {comment_id}")
                
    except Exception as e:
        logger.error(f"[BACKGROUND] Error en el envío de correo para comment_id: {comment_id}: {str(e)}", exc_info=True)
    finally:
        db.close()
