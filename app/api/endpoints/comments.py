from typing import Any, List, Dict
from datetime import datetime 
import asyncio
import base64

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.orm import Session, joinedload 
from pydantic import BaseModel

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.agent import Agent as AgentModel
from app.models.comment import Comment as CommentModel
from app.models.task import Task as TaskModel 
from app.models.activity import Activity 
from app.models.microsoft import MailboxConnection 
from app.schemas.comment import Comment as CommentSchema, CommentCreate, CommentUpdate
from app.schemas.task import TaskStatus, Task as TaskSchema, TicketWithDetails 
from app.services.microsoft_service import get_microsoft_service, MicrosoftGraphService
from app.services.task_service import send_assignment_notification
from app.utils.logger import logger
from app.core.socketio import emit_comment_update_sync 
from app.core.config import settings
from app.services.workflow_service import WorkflowService
from app.services.s3_service import get_s3_service
from app.utils.image_processor import extract_base64_images
from app.models.ticket_attachment import TicketAttachment

router = APIRouter()

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
            detail="Task not found", 
        )


    comments_orm = db.query(CommentModel).options(
        joinedload(CommentModel.agent), # Eager load agente
        joinedload(CommentModel.attachments) # Eager load adjuntos
    ).filter(
        CommentModel.ticket_id == task_id # Use correct column name
    )


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
    Now includes automatic workflow processing for content analysis.
    """

    # Validate other_destinaries (CC) if provided
    cc_recipients = []
    if comment_in.other_destinaries and not comment_in.is_private:
        try:
            from app.services.email_service import parse_other_destinaries
            cc_recipients = parse_other_destinaries(comment_in.other_destinaries)
            logger.info(f"Parsed {len(cc_recipients)} CC recipients for comment on task {task_id}")
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid email addresses in other_destinaries: {str(e)}"
            )
    
    # Validate bcc_recipients if provided
    bcc_recipients = []
    if comment_in.bcc_recipients and not comment_in.is_private:
        try:
            from app.services.email_service import parse_other_destinaries
            bcc_recipients = parse_other_destinaries(comment_in.bcc_recipients)
            logger.info(f"Parsed {len(bcc_recipients)} BCC recipients for comment on task {task_id}")
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid email addresses in bcc_recipients: {str(e)}"
            )
    
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

    previous_assignee_id = task.assignee_id
    assignee_changed = False

    if not comment_in.is_private and task.status != "Closed":
        task.status = "With User"
        db.add(task)

    # Reabrir tickets cerrados cuando agentes responden
    if task.status == "Closed":
        task.status = "In Progress"
        db.add(task)
        logger.info(f"Ticket {task_id} status changed from Closed to In Progress after agent comment")
  
    if task.assignee_id is None and not comment_in.preserve_assignee:
        
        if comment_in.assignee_id is None and not comment_in.is_attachment_upload:
            task.assignee_id = current_user.id
            assignee_changed = True
       
        elif comment_in.assignee_id is not None:
            task.assignee_id = comment_in.assignee_id
            assignee_changed = previous_assignee_id != comment_in.assignee_id
    
 
    elif comment_in.assignee_id is not None and not comment_in.preserve_assignee:
        task.assignee_id = comment_in.assignee_id
        assignee_changed = previous_assignee_id != comment_in.assignee_id
    

    task.last_update = datetime.utcnow()  # Use import
    db.add(task)

    # Update CC recipients on ticket
    if cc_recipients and not comment_in.is_private:
        existing_cc = []
        if task.cc_recipients:
            existing_cc = [email.strip() for email in task.cc_recipients.split(",") if email.strip()]
        
        all_cc = existing_cc.copy()
        for new_cc in cc_recipients:
            if new_cc not in all_cc:
                all_cc.append(new_cc)
    
        if all_cc:
            task.cc_recipients = ", ".join(all_cc)
            logger.info(f"Updated ticket {task_id} CC recipients: {task.cc_recipients}")
        
        db.add(task)
    
    # Update BCC recipients on ticket
    if bcc_recipients and not comment_in.is_private:
        existing_bcc = []
        if task.bcc_recipients:
            existing_bcc = [email.strip() for email in task.bcc_recipients.split(",") if email.strip()]
        
        all_bcc = existing_bcc.copy()
        for new_bcc in bcc_recipients:
            if new_bcc not in all_bcc:
                all_bcc.append(new_bcc)
    
        if all_bcc:
            task.bcc_recipients = ", ".join(all_bcc)
            logger.info(f"Updated ticket {task_id} BCC recipients: {task.bcc_recipients}")
        
        db.add(task)

    content_to_store = comment_in.content
    s3_html_url = None
    
    try:
        if comment_in.content and comment_in.content.strip():
            from app.services.s3_service import get_s3_service
            s3_service = get_s3_service()
            
            
            content_length = len(comment_in.content)
            should_migrate_to_s3 = (
                content_length > 65000 or  
                s3_service.should_store_html_in_s3(comment_in.content)
            )
            
            if should_migrate_to_s3:
                logger.info(f"🚀 Pre-migrating large comment content ({content_length} chars) to S3...")
                
                # Generar un ID temporal para el archivo S3
                import uuid
                temp_id = str(uuid.uuid4())
                
                # Almacenar en S3 con ID temporal
                s3_url = s3_service.upload_html_content(
                    html_content=comment_in.content,
                    filename=f"temp-comment-{temp_id}.html",
                    folder="comments"
                )
                
                # Actualizar variables para la BD
                s3_html_url = s3_url
                content_to_store = f"[MIGRATED_TO_S3] Content moved to S3: {s3_url}"
                
                logger.info(f"✅ Comment content pre-migrated to S3: {s3_url}")
    except Exception as e:
        logger.error(f"❌ Error pre-migrating comment content to S3: {str(e)}")
        # Continue with original content if S3 fails
        content_to_store = comment_in.content
        s3_html_url = None

    # Create the comment
    comment = CommentModel(
        ticket_id=task_id,
        agent_id=current_user.id,
        workspace_id=current_user.workspace_id,
        content=content_to_store,  
        s3_html_url=s3_html_url,  
        other_destinaries=comment_in.other_destinaries,  
        bcc_recipients=comment_in.bcc_recipients,        
        is_private=comment_in.is_private
    )
    db.add(comment)
    
    # Procesar attachment_ids si están presentes
    processed_attachment_ids = []
    if comment_in.attachment_ids:
        from app.models.ticket_attachment import TicketAttachment
        
        # Commit para asegurar que tengamos un comment ID válido antes de asociar adjuntos
        db.commit()
        db.refresh(comment)
        
        logger.info(f"Processing {len(comment_in.attachment_ids)} attachment IDs for comment ID {comment.id}: {comment_in.attachment_ids}")
        
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
    else:
        # Si no hay adjuntos, hacemos commit para asegurar que el comentario tenga ID
        db.commit()
        db.refresh(comment)

    # MEJORADO: Post-procesamiento solo si es necesario renombrar archivo S3
    if s3_html_url and comment.id:
        try:
            # Renombrar archivo en S3 con el ID real del comentario
            s3_service = get_s3_service()
            
            # Obtener el contenido original para almacenar con el nombre correcto
            original_content = comment_in.content
            
            # Crear nueva URL con ID real
            final_s3_url = s3_service.store_comment_html(comment.id, original_content)
            
            # Actualizar la URL en el comentario
            comment.s3_html_url = final_s3_url
            comment.content = f"[MIGRATED_TO_S3] Content moved to S3: {final_s3_url}"
            db.add(comment)
            
            logger.info(f"✅ S3 file renamed for comment {comment.id}: {final_s3_url}")
        except Exception as e:
            logger.warning(f"⚠️ Could not rename S3 file for comment {comment.id}: {str(e)}")
            # Continue with temp filename - not critical

    # NUEVO: Procesar workflows automáticamente para análisis de contenido
    workflow_results = []
    try:
        # Solo procesar workflows si el comentario tiene contenido significativo
        if comment_in.content and comment_in.content.strip() and not comment_in.is_attachment_upload:
            workflow_service = WorkflowService(db)
            
            # Preparar contexto para workflows
            workflow_context = {
                'task_id': task_id,
                'comment_id': comment.id,
                'agent_id': current_user.id,
                'workspace_id': current_user.workspace_id,
                'task_status': task.status,
                'task_priority': getattr(task, 'priority', 'normal'),
                'is_private': comment_in.is_private,
                'assignee_changed': assignee_changed,
                'previous_assignee_id': previous_assignee_id,
                'current_assignee_id': task.assignee_id
            }
            
            # Procesar workflows basados en contenido
            workflow_results = workflow_service.process_message_for_workflows(
                comment_in.content,
                current_user.workspace_id,
                workflow_context
            )
            
            if workflow_results:
                logger.info(f"Executed {len(workflow_results)} workflows for comment {comment.id} on task {task_id}")
                
                # Aplicar resultados de workflows al ticket si es necesario
                for result in workflow_results:
                    try:
                        execution_result = result.get('execution_result', {})
                        if execution_result.get('status') == 'completed':
                            # Procesar resultados de acciones
                            for action_result in execution_result.get('results', []):
                                if action_result.get('status') == 'success':
                                    action_data = action_result.get('result', {})
                                    
                                    # Auto-asignación
                                    if 'assigned_to' in action_data and not assignee_changed:
                                        # Buscar el usuario por nombre/email
                                        assignee = db.query(AgentModel).filter(
                                            AgentModel.email == action_data['assigned_to'],
                                            AgentModel.workspace_id == current_user.workspace_id
                                        ).first()
                                        if assignee:
                                            task.assignee_id = assignee.id
                                            assignee_changed = True
                                            logger.info(f"Auto-assigned task {task_id} to {assignee.email} via workflow")
                                    
                                    # Auto-priorización
                                    if 'priority' in action_data:
                                        task.priority = action_data['priority']
                                        logger.info(f"Auto-set priority of task {task_id} to {action_data['priority']} via workflow")
                                    
                                    # Auto-categorización
                                    if 'category' in action_data:
                                        task.category = action_data['category']
                                        logger.info(f"Auto-categorized task {task_id} as {action_data['category']} via workflow")
                                        
                    except Exception as e:
                        logger.error(f"Error applying workflow result {result.get('workflow_id')}: {str(e)}")
                        continue
                        
                # Commit changes made by workflows
                db.commit()
                db.refresh(task)
            
    except Exception as e:
        logger.error(f"Error processing workflows for comment {comment.id}: {str(e)}")

    try:
        # Crear  para el comentario con información del ticket
        activity = Activity(
            agent_id=current_user.id,
            source_type="Comment",  # Cambiar a Comment para distinguir de creación de tickets
            source_id=task_id,  # Usar task_id como source_id para mantener la referencia al ticket
            action=f"commented on ticket #{task_id}" if not comment_in.is_attachment_upload else f"uploaded attachment to ticket #{task_id}",
            workspace_id=current_user.workspace_id
        )
        db.add(activity)
        logger.info(f"Activity logged for comment creation: comment {comment.id} on task {task_id} by agent {current_user.id}")
    except Exception as e:
        logger.error(f"Error creating activity for comment {comment.id}: {e}")
    db.commit()
    db.refresh(task)  # Ensure the task is fresh
    db.refresh(comment)
    
    # Ejecutar workflows para comentarios
    try:
        context = {'ticket': task, 'comment': comment, 'agent': current_user}
        
        # Workflow general para comentarios agregados
        executed_workflows = WorkflowService.execute_workflows(
            db=db,
            trigger='comment.added',
            workspace_id=task.workspace_id,
            context=context
        )

        if not comment_in.is_private:
            if current_user:  # Es un agente
                executed_workflows.extend(WorkflowService.execute_workflows(
                    db=db,
                    trigger='agent.replied',
                    workspace_id=task.workspace_id,
                    context=context
                ))
            else:
                # Si fuera un cliente (aunque actualmente solo agentes pueden comentar)
                executed_workflows.extend(WorkflowService.execute_workflows(
                    db=db,
                    trigger='customer.replied',
                    workspace_id=task.workspace_id,
                    context=context
                ))
        
        if executed_workflows:
            logger.info(f"Executed workflows for comment creation {comment.id}: {executed_workflows}")
            
    except Exception as e:
        logger.error(f"Error executing workflows for comment creation {comment.id}: {str(e)}")
    
    # Si el ticket se asignó a un nuevo agente y no es el que está comentando
    if assignee_changed and task.assignee_id != current_user.id:
        try:
            # Obtener la URL de origen para usar el subdominio correcto
            origin_url = None
            if request:
                origin_url = str(request.headers.get("origin", ""))
            if not origin_url:
                origin_url = settings.FRONTEND_URL
            logger.info(f"Using {origin_url} for assignment notification")
            
            # Get the assigned agent
            assigned_agent = db.query(AgentModel).filter(AgentModel.id == task.assignee_id).first()
            if assigned_agent:
                # Send notification in background
                from app.services.task_service import send_assignment_notification
                await send_assignment_notification(db, task, origin_url)
                logger.info(f"Notification scheduled for new assignment from comment: task {task_id} to agent {task.assignee_id}")
        except Exception as e:
            logger.error(f"Error scheduling assignment notification from comment: {e}", exc_info=True)
    
    try:
        from app.services.notification_service import send_notification

        if not comment_in.is_private and not comment_in.is_attachment_upload:

            task_user = None
            if task.user_id:
                from app.models.user import User
                task_user = db.query(User).filter(User.id == task.user_id).first()

            agents = db.query(AgentModel).filter(
                AgentModel.workspace_id == task.workspace_id,
                AgentModel.is_active == True,
                AgentModel.id != current_user.id  # Don't notify the commenting agent
            ).all()
            
            for agent in agents:
                if agent.email:
                    template_vars = {
                        "agent_name": agent.name,
                        "ticket_id": task.id,
                        "ticket_title": task.title,
                        "commenter_name": current_user.name,
                        "user_name": task_user.name if task_user else "Unknown User",
                        "comment_content": comment.content
                    }
                    
                    # Intentar enviar notificación a otros agentes
                    await send_notification(
                        db=db,
                        workspace_id=task.workspace_id,
                        category="agents",
                        notification_type="new_response",
                        recipient_email=agent.email,
                        recipient_name=agent.name,
                        template_vars=template_vars,
                        task_id=task.id
                    )
    
    except Exception as notification_error:
        logger.error(f"Error sending notifications for comment {comment.id} on task {task_id}: {str(notification_error)}", exc_info=True)
    # --- End Send Notifications ---
    
    # Final commit for any remaining changes
    try:
        db.commit()
        db.refresh(comment)
        db.refresh(task)
    except Exception as e:
        logger.error(f"Error in final commit for comment {comment.id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Error saving comment")

    if not comment_in.is_private:
        try:
            # Get the database path for background task
            db_path = str(settings.DATABASE_URI)
            
            background_tasks.add_task(
                send_email_in_background,
                task_id=task_id,
                comment_id=comment.id,
                comment_content=comment_in.content,
                agent_id=current_user.id,
                agent_email=current_user.email,
                agent_name=current_user.name,
                is_private=comment_in.is_private,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                processed_attachment_ids=processed_attachment_ids,
                db_path=db_path
            )
            logger.info(f"Email background task queued for comment {comment.id} on task {task_id}")
        except Exception as e:
            logger.error(f"Error queuing email background task for comment {comment.id}: {e}")

    # Load the task with all necessary relationships
    task_with_details = db.query(TaskModel).options(
        joinedload(TaskModel.assignee),
        joinedload(TaskModel.comments).joinedload(CommentModel.agent),
        joinedload(TaskModel.comments).joinedload(CommentModel.attachments),
        joinedload(TaskModel.user)
    ).filter(TaskModel.id == task_id).first()

    # Load the comment with agent details
    comment_with_agent = db.query(CommentModel).options(
        joinedload(CommentModel.agent),
        joinedload(CommentModel.attachments)
    ).filter(CommentModel.id == comment.id).first()

    # Prepare response with workflow information
    response_data = CommentResponseModel(
        comment=comment_with_agent,
        task=task_with_details,
        assignee_changed=assignee_changed
    )
    
    try:
        comment_data = {
            'id': comment.id,
            'ticket_id': task_id,
            'agent_id': current_user.id,
            'agent_name': current_user.name,
            'agent_email': current_user.email,
            'content': comment_in.content,  # ✅ Enviar contenido completo para reemplazo perfecto
            'other_destinaries': comment_in.other_destinaries,  # Include CC info
            'bcc_recipients': comment_in.bcc_recipients,        # Include BCC info
            'is_private': comment_in.is_private,
            'created_at': comment.created_at.isoformat() if comment.created_at else None,
            'attachments': [
                {
                    'id': att.id,
                    'file_name': att.file_name,
                    'content_type': att.content_type,
                    'file_size': att.file_size,
                    'download_url': att.s3_url
                } for att in comment_with_agent.attachments
            ] if comment_with_agent.attachments else []
        }
        
        # Emitir evento de forma síncrona
        emit_comment_update_sync(
            workspace_id=current_user.workspace_id,
            comment_data=comment_data
        )
        
        logger.info(f"📤 Socket.IO comment_updated event queued for workspace {current_user.workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error emitting Socket.IO event for comment {comment.id}: {str(e)}")
    
    # Add workflow results to response if any were executed
    if workflow_results:
        # Add to response as extra field (will be ignored by Pydantic but available in JSON)
        response_dict = response_data.model_dump()
        response_dict['workflow_results'] = workflow_results
        return response_dict

    return response_data


@router.get("/{comment_id}", response_model=CommentSchema)
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


@router.put("/{comment_id}", response_model=CommentSchema)
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

    if comment.agent_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this comment",
        )

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


@router.delete("/{comment_id}", response_model=CommentSchema)
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
    cc_recipients: List[str],
    bcc_recipients: List[str],
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
        # IMPORTANTE: Forzar refresh desde la base de datos para obtener datos actualizados
        db.expire_all()  # Expira todos los objetos en cache
        task_with_user = db.query(TaskModel).options(
            joinedload(TaskModel.user)
        ).filter(TaskModel.id == task_id).first()

        if not task_with_user:
            logger.error(f"[BACKGROUND] Task {task_id} not found when attempting to send email for comment {comment_id}.")
            return
        
        # Log para debugging - mostrar información del usuario actual del ticket
        if task_with_user.user:
            logger.info(f"[BACKGROUND] Task {task_id} current user: {task_with_user.user.name} ({task_with_user.user.email})")
        else:
            logger.info(f"[BACKGROUND] Task {task_id} has no assigned user")
            
        if task_with_user.mailbox_connection_id:
            # Task originated from email, send a reply
            logger.info(f"[BACKGROUND] Task {task_id} originated from email. Attempting to send comment ID {comment_id} as reply with {len(processed_attachment_ids)} attachments.")
            microsoft_service = get_microsoft_service(db)
            microsoft_service.send_reply_email(task_id=task_id, reply_content=comment_content, agent=agent, attachment_ids=processed_attachment_ids, cc_recipients=cc_recipients)
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

            # Log detallado del envío de email
            logger.info(f"[BACKGROUND] 📧 Sending email notification:")
            logger.info(f"[BACKGROUND]   → From: {sender_mailbox}")
            logger.info(f"[BACKGROUND]   → To: {recipient_email}")
            logger.info(f"[BACKGROUND]   → Subject: {subject}")
            logger.info(f"[BACKGROUND]   → Comment ID: {comment_id}")
            logger.info(f"[BACKGROUND]   → Task ID: {task_id}")

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

@router.get("/comments/{comment_id}/s3-content")
def get_comment_s3_content(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
):
    """
    Get comment content from S3 when it's stored there
    Optimized for fast loading with caching headers
    """
    try:
        # Get comment
        comment = db.query(CommentModel).filter(CommentModel.id == comment_id).first()
        if not comment:
            raise HTTPException(status_code=404, detail="Comment not found")

        if comment.workspace_id != current_user.workspace_id:
            raise HTTPException(status_code=403, detail="Not authorized to access this comment")
        
        if not comment.s3_html_url:
            return {
                "status": "content_in_database",
                "content": comment.content,
                "message": "Comment content is stored in database, not S3"
            }
        
        s3_service = get_s3_service()
        s3_content = s3_service.get_comment_html(comment.s3_html_url)
        
        if not s3_content:
            logger.warning(f"Failed to retrieve content from S3 for comment {comment_id}, falling back to database")
            return {
                "status": "s3_error_fallback",
                "content": comment.content,
                "message": "Failed to retrieve from S3, showing database content"
            }
        
        try:
            # Buscar el ticket asociado para obtener el ID
            ticket = db.query(TaskModel).filter(TaskModel.id == comment.ticket_id).first()
            if ticket:
                # Procesar el HTML para las imágenes CID
                from app.services.microsoft_service import MicrosoftGraphService
                ms_service = MicrosoftGraphService(db)

                processed_content = s3_content
                
                import re
                from bs4 import BeautifulSoup
                
                soup = BeautifulSoup(s3_content, 'html.parser')
                cid_images_found = soup.find_all('img', src=re.compile(r'^cid:'))
                
                if cid_images_found:
                    logger.info(f"Found {len(cid_images_found)} unprocessed CID images in S3 content for comment {comment_id}")
                    
                    inline_attachments = db.query(TicketAttachment).filter(
                        TicketAttachment.comment_id == comment_id
                    ).all()
                    
                    email_attachments = []
                    for att in inline_attachments:
                        if att.content_bytes and att.content_type and att.content_type.startswith('image/'):
                            email_att = type('EmailAttachment', (), {
                                'contentId': att.file_name.replace('.', '_'),  # Usar filename como contentId
                                'is_inline': True,
                                'contentBytes': base64.b64encode(att.content_bytes).decode('utf-8'),
                                'content_type': att.content_type
                            })()
                            email_attachments.append(email_att)
                    
                    if email_attachments:
                        processed_content = ms_service._process_html_body(
                            s3_content, 
                            email_attachments, 
                            f"s3_comment_{comment_id}"
                        )
                        logger.info(f"Processed CID images for S3 comment {comment_id}")
                
                final_content, extracted_images = extract_base64_images(processed_content, ticket.id)
                
                if extracted_images:
                    logger.info(f"Extracted {len(extracted_images)} base64 images from S3 content for comment {comment_id}")
                    processed_content = final_content
                
            else:
                processed_content = s3_content
                
        except Exception as img_process_error:
            logger.warning(f"Error processing images in S3 content for comment {comment_id}: {str(img_process_error)}")
            processed_content = s3_content
        
        from fastapi import Response
        response_data = {
            "status": "loaded_from_s3",
            "content": processed_content,  # Usar contenido procesado
            "s3_url": comment.s3_html_url,
            "message": "Content loaded from S3"
        }     
        return response_data      
    except Exception as e:
        logger.error(f"❌ Error getting S3 content for comment {comment_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get comment content: {str(e)}")
