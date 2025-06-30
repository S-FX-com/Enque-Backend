from typing import Any, List, Optional
import asyncio  # Importar asyncio
import time
import logging
from concurrent.futures import ThreadPoolExecutor  # Importar ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session, joinedload, noload
from sqlalchemy import or_, and_ # Import 'or_' for OR condition and 'and_' for AND condition

# Import dependencies
from app.api.dependencies import get_current_active_user, get_current_active_admin_or_manager
from app.database.session import get_db
from app.models.task import Task, TicketBody  # Importar TicketBody junto con Task
from app.models.agent import Agent
from app.models.user import User # Import User model
from app.models.team import TeamMember # Import TeamMember for filtering
from app.models.microsoft import EmailTicketMapping, MailboxConnection, mailbox_team_assignments # Import MailboxConnection
from app.models.activity import Activity # Import Activity model
# Use TaskWithDetails and the renamed TicketCreate/TicketUpdate schemas
from app.schemas.task import TaskWithDetails, TicketCreate, TicketUpdate, EmailInfo, Task as TaskSchema, TicketMergeRequest, TicketMergeResponse
# Import logger if needed for activity logging errors
from app.utils.logger import logger

# Logger específico para este módulo
task_logger = logging.getLogger(__name__)
# Import update_task service function and Microsoft service
from app.services.task_service import update_task, send_assignment_notification # Importar función de notificación
from app.services.microsoft_service import MicrosoftGraphService # Import the service
from app.services.automation_service import execute_automations_for_ticket # Import automation service
from app.services.ticket_merge_service import TicketMergeService # Import merge service
from datetime import datetime # Import datetime
from app.core.config import settings # Import settings
from app.core.socketio import emit_new_ticket, emit_ticket_update, emit_ticket_deleted, emit_comment_update # Import Socket.IO functions

router = APIRouter()


# OPTIMIZADO: Use TaskSchema en lugar de TaskWithDetails para evitar relaciones pesadas
@router.get("/", response_model=List[TaskSchema])
async def read_tasks(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    team_id: Optional[int] = Query(None),
    assignee_id: Optional[int] = Query(None),
    priority: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
) -> Any:

    start_time = time.time()
    
    query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(
        noload(Task.workspace),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.assignee),
        noload(Task.user),
        noload(Task.team),
        noload(Task.company),
        noload(Task.category),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection)
    )

    if subject:
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if team_id:
        query = query.filter(
            or_(
                Task.team_id == team_id,
                and_(
                    Task.team_id.is_(None),
                    Task.mailbox_connection_id.isnot(None),
                    Task.mailbox_connection_id.in_(
                        db.query(mailbox_team_assignments.c.mailbox_connection_id).filter(
                            mailbox_team_assignments.c.team_id == team_id
                        )
                    )
                )
            )
        )
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if priority:
        query = query.filter(Task.priority == priority)
    if category_id:
        query = query.filter(Task.category_id == category_id)

    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    query_time = time.time() - start_time
            # Optimized tasks list query completed
    
    return tasks


# Endpoint for ticket search - MOVED BEFORE /{task_id} endpoint
@router.get("/search", response_model=List[TaskWithDetails])
async def search_tickets(
    q: str = Query(..., description="Search term to find in ticket title, description, body, or ticket ID"),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 30,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Search for tickets containing the search term in title, description, body, or by ticket ID.
    If the search query is numeric, it will search by ticket ID first, then by text.
    """
    base_query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    )
    
    # Check if query is numeric (ticket ID search)
    if q.strip().isdigit():
        ticket_id = int(q.strip())
        # Search by exact ticket ID first
        id_query = base_query.filter(Task.id == ticket_id)
        id_query = id_query.options(
            joinedload(Task.sent_from),
            joinedload(Task.sent_to),
            joinedload(Task.assignee),
            joinedload(Task.user),
            joinedload(Task.team),
            joinedload(Task.company),
            joinedload(Task.category),
            joinedload(Task.body)
        )
        tickets = id_query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
        
        # If found by ID, return immediately
        if tickets:
            return tickets
    
    # Text search (original logic)
    search_term = f"%{q}%"
    query = base_query.join(TicketBody, Task.id == TicketBody.ticket_id, isouter=True).filter(
        or_(
            Task.title.ilike(search_term),
            Task.description.ilike(search_term),
            TicketBody.email_body.ilike(search_term)
        )
    )
    
    query = query.options(
        joinedload(Task.sent_from),
        joinedload(Task.sent_to),
        joinedload(Task.assignee),
        joinedload(Task.user),
        joinedload(Task.team),
        joinedload(Task.company),
        joinedload(Task.category),
        joinedload(Task.body)
    )
    
    tickets = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return tickets


@router.post("/", response_model=TaskSchema)
async def create_task(
    task_in: TicketCreate, # Use the renamed schema TicketCreate
    request: Request,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create a new task. All roles can create tasks.
    """
    # Create the task
    task = Task(
        title=task_in.title,
        description=task_in.description,
        status=task_in.status,
        priority=task_in.priority,
        assignee_id=task_in.assignee_id,
        team_id=task_in.team_id,
        due_date=task_in.due_date,
        sent_from_id=current_user.id, # Automatically set the current user as the sender
        sent_to_id=task_in.sent_to_id,
        user_id=task_in.user_id,
        company_id=task_in.company_id,
        workspace_id=current_user.workspace_id, # Use the workspace from current user
        category_id=task_in.category_id # Use the category from input
    )
    
    db.add(task)
    db.commit()
    db.refresh(task)

    # --- Execute Automations ---
    try:
        # Load the task with all relationships needed for automation conditions
        task_with_relations = db.query(Task).options(
            joinedload(Task.user),
            joinedload(Task.assignee),
            joinedload(Task.company),
            joinedload(Task.category),
            joinedload(Task.team)
        ).filter(Task.id == task.id).first()
        
        if task_with_relations:
            executed_actions = execute_automations_for_ticket(db, task_with_relations)
            if executed_actions:
                logger.info(f"Automations executed for ticket {task.id}: {executed_actions}")
                # Refresh the task to get updated values from automations
                db.refresh(task)
        
    except Exception as automation_error:
        logger.error(f"Error executing automations for ticket {task.id}: {str(automation_error)}", exc_info=True)
        # Don't fail ticket creation if automations fail
    # --- End Execute Automations ---

    # --- Log Activity ---
    try:
        activity = Activity(
            agent_id=current_user.id, # Use the ID of the authenticated agent/admin
            action="created", # Consistent action string for creation
            source_type="Ticket",
            source_id=task.id,
            workspace_id=task.workspace_id # Get workspace_id from the created task
        )
        db.add(activity)
        db.commit()
        logger.info(f"Activity logged for ticket creation: {task.id} by agent {current_user.id}")
    except Exception as e:
        logger.error(f"Failed to log activity for ticket creation {task.id}: {str(e)}")
        db.rollback() # Rollback activity commit if it failed
    # --- End Activity Log ---

    # --- Assignment Notification ---
    if task.assignee_id:
        try:
            # Load the assignee
            task.assignee = db.query(Agent).filter(Agent.id == task.assignee_id).first()

            request_origin = None
            if request:
                # Get the origin of the request (Frontend URL)
                request_origin = str(request.headers.get("origin", ""))
                logger.info(f"Request origin detected for notification: {request_origin}")
            
            # Send notification email to the assigned agent
            from app.services.task_service import send_assignment_notification
            await send_assignment_notification(db, task, request_origin)
        except Exception as e:
            logger.error(f"Failed to send assignment notification for task {task.id}: {str(e)}")
    # --- End Assignment Notification ---

    # --- Team Notification ---
    # Send notification to team members if ticket is assigned to team but no specific agent
    if task.team_id and not task.assignee_id:
        try:
            request_origin = None
            if request:
                request_origin = str(request.headers.get("origin", ""))
                logger.info(f"Request origin detected for team notification: {request_origin}")
            from app.services.task_service import send_team_notification
            await send_team_notification(db, task, request_origin)
        except Exception as e:
            logger.error(f"Failed to send team notification for task {task.id}: {str(e)}")
    # --- End Team Notification ---

    # --- Socket.IO Event ---
    try:
        # Emit new ticket event to all workspace clients
        task_data = {
            'id': task.id,
            'title': task.title,
            'status': task.status,
            'priority': task.priority,
            'workspace_id': task.workspace_id,
            'assignee_id': task.assignee_id,
            'team_id': task.team_id,
            'user_id': task.user_id,
            'created_at': task.created_at.isoformat() if task.created_at else None
        }
        await emit_new_ticket(task.workspace_id, task_data)
    except Exception as e:
        logger.error(f"Failed to emit new_ticket event for task {task.id}: {str(e)}")
    # --- End Socket.IO Event ---

    # --- Email Sending Logic ---
    try:
        # Get the user associated with the task
        user = db.query(User).filter(User.id == task.user_id).first()
        if user and user.email:
            recipient_email = user.email
            logger.info(f"Recipient email found: {recipient_email}")
            
            # Get the mailbox connections associated with the current workspace
            mailbox = db.query(MailboxConnection).filter(
                MailboxConnection.workspace_id == current_user.workspace_id
            ).first()
            
            if not mailbox:
                logger.warning(f"No mailbox connection found for workspace {current_user.workspace_id}. Cannot send email.")
            else:
                sender_mailbox = mailbox.email
                # Prepare email content - Use only the task title as the subject
                subject = task.title
                # Use the description as the HTML body (assuming it's HTML from Tiptap)
                html_body = task.description

                # Get Microsoft Service instance
                microsoft_service = MicrosoftGraphService(db=db)

                # Send the email
                logger.info(f"Attempting to send new ticket email for task {task.id} from {sender_mailbox} to {recipient_email}")
                email_sent = microsoft_service.send_new_email(
                    mailbox_email=sender_mailbox,
                    recipient_email=recipient_email,
                    subject=subject,
                    html_body=html_body,
                    task_id=task.id  # Pass the task ID to include in the subject
                )
                if not email_sent:
                    logger.error(f"Failed to send new ticket email for task {task.id}")
                else:
                    logger.info(f"Successfully sent new ticket email for task {task.id}")

    except Exception as email_error:
        logger.error(f"Error trying to send email for newly created ticket {task.id}: {str(email_error)}", exc_info=True)
        # Do not raise an exception here, ticket creation succeeded, email is secondary
    # --- End Email Logic ---

    return task


# Update response model to TaskWithDetails to include body
@router.get("/{task_id}", response_model=TaskWithDetails)
async def read_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get a specific task by ID with all related details
    """
    query = db.query(Task).options(
        joinedload(Task.workspace),
        joinedload(Task.sent_from), 
        joinedload(Task.sent_to),
        joinedload(Task.assignee),
        joinedload(Task.user),
        joinedload(Task.team),
        joinedload(Task.company),
        joinedload(Task.category),
        joinedload(Task.body),
        joinedload(Task.merged_by_agent)
    ).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    )
    
    task = query.first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task


@router.put("/{task_id}", response_model=TaskWithDetails)
async def update_task_endpoint(
    task_id: int,
    task_in: TicketUpdate,
    request: Request,
    db: Session = Depends(get_db),
    # Inject the basic active user dependency
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Update a task. All roles (admin, manager, agent) can update all fields including assignee and team.
    """
    # Fetch the task ensuring it belongs to the user's workspace
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Get origin URL for notification
    origin = request.headers.get("origin") or settings.FRONTEND_URL

    # Use the service function which handles the actual update logic
    updated_task_dict = update_task(db=db, task_id=task_id, task_in=task_in, request_origin=origin)

    if not updated_task_dict: # Service function returns the updated dict or None
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, # Or appropriate error from service
            detail="Task update failed", # Or more specific error from service
        )
    
    # Load the complete task object with all relationships required by TaskWithDetails
    updated_task_obj = db.query(Task).options(
        joinedload(Task.workspace),
        joinedload(Task.team),
        joinedload(Task.company),
        joinedload(Task.user),
        joinedload(Task.sent_from),
        joinedload(Task.sent_to),
        joinedload(Task.assignee),
        joinedload(Task.category),
        joinedload(Task.body)
    ).filter(Task.id == task_id).first()

    if not updated_task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found after update",
        )

    # --- Socket.IO Event ---
    try:
        # ✅ OPTIMIZACIÓN: Usar función síncrona para respuesta más rápida
        task_data = {
            'id': updated_task_obj.id,
            'title': updated_task_obj.title,
            'status': updated_task_obj.status,
            'priority': updated_task_obj.priority,
            'workspace_id': updated_task_obj.workspace_id,
            'assignee_id': updated_task_obj.assignee_id,
            'team_id': updated_task_obj.team_id,
            'user_id': updated_task_obj.user_id,
            'updated_at': updated_task_obj.updated_at.isoformat() if updated_task_obj.updated_at else None
        }
        
        # Usar función síncrona para no bloquear la respuesta
        from app.core.socketio import emit_ticket_update_sync
        emit_ticket_update_sync(updated_task_obj.workspace_id, task_data)
        
    except Exception as e:
        logger.error(f"Failed to emit ticket_updated event for task {task_id}: {str(e)}")
    # --- End Socket.IO Event ---

    # Return the updated ORM object with all relationships
    return updated_task_obj


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Delete a task. All roles can delete tasks.
    """
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id
    ).first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    workspace_id = task.workspace_id  # Store workspace_id before deletion
    
    # Mark as deleted instead of actual deletion
    task.is_deleted = True
    db.commit()

    # --- Socket.IO Event ---
    try:
        # Emit ticket deleted event to all workspace clients
        await emit_ticket_deleted(workspace_id, task_id)
    except Exception as e:
        logger.error(f"Failed to emit ticket_deleted event for task {task_id}: {str(e)}")
    # --- End Socket.IO Event ---

    return {"message": "Task deleted successfully"}


@router.get("/user/{user_id}", response_model=List[TaskSchema])
async def read_user_tasks(
    user_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve tasks created by a specific user WITHIN the current user's workspace
    """
    # Add workspace filter
    tasks = db.query(Task).filter(
        Task.user_id == user_id,
        Task.workspace_id == current_user.workspace_id, # Filter by current user's workspace
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()

    return tasks


@router.get("/assignee/{agent_id}", response_model=List[TaskSchema])
async def read_assigned_tasks(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
) -> Any:
    """
    OPTIMIZADO: Tasks assigned without heavy relationships for maximum performance
    """
    start_time = time.time()
    
    query = db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(
        # EVITAR loading relationships for maximum performance
        noload(Task.workspace),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.assignee),
        noload(Task.user),
        noload(Task.team),
        noload(Task.company),
        noload(Task.category),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection)
    )

    if subject:
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)

    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    query_time = time.time() - start_time
            # Optimized assignee tasks query completed
    
    return tasks


@router.get("/team/{team_id}", response_model=List[TaskSchema])
async def read_team_tasks(
    team_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve tasks assigned to a specific team WITHIN the current user's workspace.
    Includes both direct team assignments and mailbox team assignments.
    """
    # Include both direct team assignments and mailbox team assignments (avoiding duplicates)
    tasks = db.query(Task).filter(
        or_(
            Task.team_id == team_id,  # Direct team assignment
            and_(  # Mailbox team assignment (only for tickets without direct team assignment)
                Task.team_id.is_(None),  # Only include mailbox tickets that don't have team_id
                Task.mailbox_connection_id.isnot(None),
                Task.mailbox_connection_id.in_(
                    db.query(mailbox_team_assignments.c.mailbox_connection_id).filter(
                        mailbox_team_assignments.c.team_id == team_id
                    )
                )
            )
        ),
        Task.workspace_id == current_user.workspace_id, # Filter by current user's workspace
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()

    return tasks


@router.get("/{task_id}/initial-content")
def get_task_initial_content(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    """
    Get initial ticket content from S3 when it's migrated there.
    Falls back to description or email_body if not in S3.
    """
    try:
        # Verify the task exists and user has access
        task = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).first()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )

        # First, check if we have description (for manual tickets)
        if task.description and not task.description.startswith('[MIGRATED_TO_S3]'):
            return {
                "status": "content_in_database",
                "content": task.description,
                "message": "Content loaded from ticket description"
            }

        # Check email_body in TicketBody
        if task.body and task.body.email_body:
            if not task.body.email_body.startswith('[MIGRATED_TO_S3]'):
                return {
                    "status": "content_in_database", 
                    "content": task.body.email_body,
                    "message": "Content loaded from ticket body"
                }

        # If we reach here, content is likely in S3 via the initial comment
        # Find the initial comment (the oldest comment for this ticket)
        from app.models.comment import Comment as CommentModel
        initial_comment = db.query(CommentModel).filter(
            CommentModel.ticket_id == task_id
        ).order_by(CommentModel.created_at.asc()).first()

        if not initial_comment:
            # No comments found, return empty or fallback content
            fallback_content = task.description or task.body.email_body if task.body else ""
            if fallback_content and fallback_content.startswith('[MIGRATED_TO_S3]'):
                # Clean the migrated message
                clean_content = fallback_content.replace('[MIGRATED_TO_S3]', '').strip()
                # Remove the URL part
                import re
                clean_content = re.sub(r'Content moved to S3: https://[^\s]*', '', clean_content).strip()
                fallback_content = clean_content or "Content not available"
            
            return {
                "status": "no_initial_comment",
                "content": fallback_content or "No initial content found",
                "message": "No initial comment found for this ticket"
            }

        # Check if initial comment has S3 content
        if not initial_comment.s3_html_url:
            return {
                "status": "content_in_database",
                "content": initial_comment.content or "",
                "message": "Initial content loaded from comment in database"
            }

        # Get content from S3
        from app.services.s3_service import get_s3_service
        s3_service = get_s3_service()
        s3_content = s3_service.get_comment_html(initial_comment.s3_html_url)

        if not s3_content:
            # Fallback to comment content in database
            logger.warning(f"Failed to retrieve initial content from S3 for ticket {task_id}, falling back to database")
            fallback_content = initial_comment.content or ""
            if fallback_content.startswith('[MIGRATED_TO_S3]'):
                # Clean the migrated message
                clean_content = fallback_content.replace('[MIGRATED_TO_S3]', '').strip()
                import re
                clean_content = re.sub(r'Content moved to S3: https://[^\s]*', '', clean_content).strip()
                fallback_content = clean_content or "Content temporarily unavailable"
            
            return {
                "status": "s3_error_fallback",
                "content": fallback_content,
                "message": "Failed to retrieve from S3, showing database content"
            }

        # Process S3 content for images and attachments
        try:
            # Process images if needed (similar to comment S3 processing)
            from app.services.microsoft_service import MicrosoftGraphService
            from app.utils.image_processor import extract_base64_images
            
            ms_service = MicrosoftGraphService(db)
            processed_content = s3_content
            
            # Process base64 images that might be in the content
            final_content, extracted_images = extract_base64_images(processed_content, task.id)
            
            if extracted_images:
                logger.info(f"Extracted {len(extracted_images)} base64 images from initial S3 content for ticket {task_id}")
                processed_content = final_content
                
        except Exception as img_process_error:
            logger.warning(f"Error processing images in initial S3 content for ticket {task_id}: {str(img_process_error)}")
            processed_content = s3_content

        return {
            "status": "loaded_from_s3",
            "content": processed_content,
            "s3_url": initial_comment.s3_html_url,
            "message": "Initial content loaded from S3"
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting initial content for ticket {task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get initial ticket content: {str(e)}")


@router.get("/{task_id}/html-content")
def get_ticket_html_content(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    """
    Get complete ticket HTML content directly from S3 URLs stored in comments.
    This is MUCH simpler - just reads the s3_html_url field and fetches from S3.
    """
    try:
        # Verify the task exists and user has access
        task = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).first()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found"
            )

        from app.models.comment import Comment as CommentModel
        from app.services.s3_service import get_s3_service
        
        s3_service = get_s3_service()
        
        # Get all comments with their S3 URLs, ordered by creation date
        comments = db.query(CommentModel).options(
            joinedload(CommentModel.agent),
            joinedload(CommentModel.attachments)
        ).filter(
            CommentModel.ticket_id == task_id
        ).order_by(CommentModel.created_at.asc()).all()

        # Prepare results
        html_contents = []
        
        # 1. Handle initial ticket content (first comment or ticket description)
        initial_content = None
        initial_sender = None
        
        # Check if we have comments first - initial content is usually the first comment
        if comments and comments[0].s3_html_url:
            # First comment has S3 content - this is the initial message
            try:
                s3_content = s3_service.get_comment_html(comments[0].s3_html_url)
                if s3_content:
                    initial_content = s3_content
                    
                    # ✅ EXTRACT ORIGINAL-SENDER INFORMATION (like frontend used to do)
                    import re
                    original_sender_match = re.search(r'<original-sender>(.*?)\|(.*?)</original-sender>', s3_content)
                    
                    if original_sender_match:
                        # Es un mensaje de usuario con información extraída
                        initial_sender = {
                            "type": "user", 
                            "name": original_sender_match.group(1).strip(),
                            "email": original_sender_match.group(2).strip(),
                            "created_at": comments[0].created_at
                        }
                    elif comments[0].agent:
                        # Es un mensaje de agente real
                        initial_sender = {
                            "type": "agent", 
                            "name": comments[0].agent.name,
                            "email": comments[0].agent.email,
                            "created_at": comments[0].created_at
                        }
            except Exception as e:
                logger.warning(f"Failed to get initial S3 content: {e}")
        
        # Fallback to ticket description if no S3 content in first comment
        if not initial_content:
            if task.description:
                initial_content = task.description
            elif task.body and task.body.email_body:
                initial_content = task.body.email_body
            
            if initial_content:
                initial_sender = {
                    "type": "user",
                    "name": task.user.name if task.user else "Unknown User",
                    "email": task.user.email if task.user else "unknown",
                    "created_at": task.created_at
                }

        if initial_content:
            initial_attachments = []
            if comments and comments[0].attachments:
                for att in comments[0].attachments:
                    download_url = att.s3_url if att.s3_url else f"/api/v1/attachments/{att.id}"
                    
                    initial_attachments.append({
                        "id": att.id,
                        "file_name": att.file_name,
                        "content_type": att.content_type,
                        "file_size": att.file_size,
                        "s3_url": getattr(att, 's3_url', None),
                        "download_url": download_url
                    })
            
            html_contents.append({
                "id": "initial",
                "content": initial_content,
                "sender": initial_sender,
                "is_private": False,
                "attachments": initial_attachments,
                "created_at": comments[0].created_at if comments else task.created_at
            })
        s3_urls_needed = []
        comment_mapping = {}
        
        for comment in comments:
            if comment.s3_html_url:
                s3_urls_needed.append(comment.s3_html_url)
                comment_mapping[comment.s3_html_url] = comment
        
        # Fetch all S3 content in parallel if we have any S3 URLs
        s3_content_cache = {}
        if s3_urls_needed:
            # Fetching S3 contents in parallel
            
            # Simple concurrent fetching using ThreadPoolExecutor
            from concurrent.futures import as_completed
            
            def fetch_s3_content(s3_url):
                try:
                    content = s3_service.get_comment_html(s3_url)
                    return s3_url, content
                except Exception as e:
                    logger.warning(f"Failed to fetch S3 content from {s3_url}: {e}")
                    return s3_url, None
            
            # Use ThreadPoolExecutor for parallel S3 fetching
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_url = {executor.submit(fetch_s3_content, url): url for url in s3_urls_needed}
                
                for future in as_completed(future_to_url):
                    s3_url, content = future.result()
                    s3_content_cache[s3_url] = content
        
        # Now process all comments with cached S3 content
        for comment in comments:
            content = None
            
            # Skip the first comment if it was already used as initial content
            if (initial_content and comments and comment.id == comments[0].id and 
                comments[0].s3_html_url and initial_content != "Content not available"):
                continue
            
            # Get content from S3 cache if available
            if comment.s3_html_url and comment.s3_html_url in s3_content_cache:
                content = s3_content_cache[comment.s3_html_url]
                
                # Process base64 images if the content has them
                if content and 'data:image/' in content:
                    try:
                        from app.utils.image_processor import extract_base64_images
                        processed_content, extracted_images = extract_base64_images(content, task.id)
                        content = processed_content
                        # Base64 images processed silently
                    except Exception as e:
                        logger.warning(f"Error processing images in comment {comment.id}: {e}")
            
            # If no S3 content, use database content
            if not content:
                content = comment.content or "Content not available"

            import re
            original_sender_match = re.search(r'<original-sender>(.*?)\|(.*?)</original-sender>', content) if content else None
            
            if original_sender_match:
                sender = {
                    "type": "user",
                    "name": original_sender_match.group(1).strip(),
                    "email": original_sender_match.group(2).strip(),
                    "created_at": comment.created_at
                }
            elif comment.agent:
                sender = {
                    "type": "agent",
                    "name": comment.agent.name,
                    "email": comment.agent.email,
                    "created_at": comment.created_at
                }
            else:
                sender = {
                    "type": "unknown",
                    "name": "Unknown",
                    "email": "unknown",
                    "created_at": comment.created_at
                }

            attachments = []
            if comment.attachments:
                for att in comment.attachments:
                    download_url = att.s3_url if att.s3_url else f"/api/v1/attachments/{att.id}"
                    
                    attachments.append({
                        "id": att.id,
                        "file_name": att.file_name,
                        "content_type": att.content_type,
                        "file_size": att.file_size,
                        "s3_url": getattr(att, 's3_url', None),
                        "download_url": download_url
                    })

            html_contents.append({
                "id": comment.id,
                "content": content,
                "sender": sender,
                "is_private": comment.is_private,
                "attachments": attachments,
                "created_at": comment.created_at
            })        
        return {
            "status": "success",
            "ticket_id": task_id,
            "ticket_title": task.title,
            "total_items": len(html_contents),
            "contents": html_contents,
            "message": f"Ticket HTML content retrieved with {len(html_contents)} items"
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting HTML content for ticket {task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get ticket HTML content: {str(e)}")


# === MERGE ENDPOINTS ===

@router.post("/merge", response_model=TicketMergeResponse)
async def merge_tickets(
    merge_request: TicketMergeRequest,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Merge multiple tickets into a main ticket.
    Transfers all comments, attachments and content from secondary tickets to the main one.
    """
    try:
        result = TicketMergeService.merge_tickets(
            db=db,
            target_ticket_id=merge_request.target_ticket_id,
            ticket_ids_to_merge=merge_request.ticket_ids_to_merge,
            current_user=current_user
        )
        
        if result["success"]:
            logger.info(f"Successful merge: ticket {merge_request.target_ticket_id} with {result['merged_ticket_ids']}")
            return TicketMergeResponse(
                success=True,
                target_ticket_id=result["target_ticket_id"],
                merged_ticket_ids=result["merged_ticket_ids"],
                comments_transferred=result["comments_transferred"],
                message=result["message"]
            )
        else:
            logger.error(f"Merge error: {result.get('errors', [])}")
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Error merging tickets",
                    "errors": result.get("errors", [])
                }
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in merge_tickets: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/mergeable", response_model=List[TaskSchema])
async def get_mergeable_tickets(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    exclude_ticket_id: Optional[int] = Query(None, description="Ticket ID to exclude from search"),
    search: Optional[str] = Query(None, description="Search term to filter tickets"),
    limit: int = Query(50, le=100, description="Results limit")
) -> Any:
    """
    Get list of tickets that can be merged.
    Excludes already merged tickets, deleted tickets, and optionally a specific ticket.
    """
    try:
        tickets = TicketMergeService.get_mergeable_tickets(
            db=db,
            workspace_id=current_user.workspace_id,
            exclude_ticket_id=exclude_ticket_id,
            search_term=search,
            limit=limit
        )
        
        return tickets
        
    except Exception as e:
        logger.error(f"Error getting mergeable tickets: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting tickets: {str(e)}")


@router.get("/{ticket_id}/merge-info")
async def get_ticket_merge_info(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get merge information for a specific ticket.
    Includes if it's merged, with which ticket, and which tickets were merged into it.
    """
    try:
        ticket = db.query(Task).filter(
            Task.id == ticket_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).first()
        
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        merge_info = {
            "ticket_id": ticket_id,
            "is_merged": ticket.is_merged,
            "merged_to_ticket_id": ticket.merged_to_ticket_id,
            "merged_at": ticket.merged_at,
            "merged_by_agent_id": ticket.merged_by_agent_id,
            "merged_by_agent_name": None,
            "merged_tickets": [],
            "merged_to_ticket_title": None
        }
        
        if ticket.is_merged and ticket.merged_to_ticket_id:
            target_ticket = db.query(Task).filter(Task.id == ticket.merged_to_ticket_id).first()
            if target_ticket:
                merge_info["merged_to_ticket_title"] = target_ticket.title
        
        if ticket.merged_by_agent_id:
            agent = db.query(Agent).filter(Agent.id == ticket.merged_by_agent_id).first()
            if agent:
                merge_info["merged_by_agent_name"] = agent.name
        
        merged_tickets = TicketMergeService.get_merged_tickets_for_ticket(
            db=db,
            ticket_id=ticket_id,
            workspace_id=current_user.workspace_id
        )
        
        merge_info["merged_tickets"] = [
            {
                "id": t.id,
                "title": t.title,
                "merged_at": t.merged_at,
                "status": t.status
            }
            for t in merged_tickets
        ]
        
        return merge_info
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting merge info for {ticket_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting merge information: {str(e)}")