from typing import Any, List, Optional
import asyncio  # Importar asyncio
from concurrent.futures import ThreadPoolExecutor  # Importar ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session, joinedload
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
from app.schemas.task import TaskWithDetails, TicketCreate, TicketUpdate, EmailInfo, Task as TaskSchema
# Import logger if needed for activity logging errors
from app.utils.logger import logger
# Import update_task service function and Microsoft service
from app.services.task_service import update_task, send_assignment_notification # Importar función de notificación
from app.services.microsoft_service import MicrosoftGraphService # Import the service
from app.services.automation_service import execute_automations_for_ticket # Import automation service
from datetime import datetime # Import datetime
from app.core.config import settings # Import settings
from app.core.socketio import emit_new_ticket, emit_ticket_update, emit_ticket_deleted, emit_comment_update # Import Socket.IO functions

router = APIRouter()


# Use TaskWithDetails as the response model to include sender details
@router.get("/", response_model=List[TaskWithDetails])
async def read_tasks(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    # Add filter parameters
    subject: Optional[str] = Query(None, description="Filter by subject text (contains, case-insensitive)"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., Open, Closed, Unread)"),
    team_id: Optional[int] = Query(None, description="Filter by assigned team ID"),
    assignee_id: Optional[int] = Query(None, description="Filter by assigned agent ID"),
    priority: Optional[str] = Query(None, description="Filter by priority (e.g., Low, Medium, High)"),
    category_id: Optional[int] = Query(None, description="Filter by category ID"), # Add category filter
) -> Any:
    """
    Retrieve tasks based on user role and optional filters:
    - All users (Admin/Manager/Agent): Can see ALL tasks in the workspace, optionally filtered.
    - Team-specific filtering only applies when teamId filter is used explicitly.
    
    Note: All users can see ALL tickets in "All Tickets" view regardless of team membership.
    """
    base_query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    )

    # No team membership filtering in the main endpoint - all users see all tickets
    # This ensures "All Tickets" shows everything for everyone
    query = base_query

    # Apply optional filters to the query
    if subject:
        # Use ilike for case-insensitive contains search
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if team_id:
        # Include both direct team assignments and mailbox team assignments (avoiding duplicates)
        query = query.filter(
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
            )
        )
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if priority:
        query = query.filter(Task.priority == priority)
    if category_id: # Add category filter logic
        query = query.filter(Task.category_id == category_id)

    # Apply eager loading options to the final filtered query
    query = query.options(
        joinedload(Task.sent_from),
        joinedload(Task.sent_to),
        joinedload(Task.assignee),
        joinedload(Task.user),
        joinedload(Task.team),
        joinedload(Task.company),
        joinedload(Task.category) # Eager load category
    )

    # Apply ordering, offset, and limit
    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()

    return tasks


# Endpoint for ticket search - MOVED BEFORE /{task_id} endpoint
@router.get("/search", response_model=List[TaskWithDetails])
async def search_tickets(
    q: str = Query(..., description="Search term to find in ticket title, description or body"),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Search for tickets containing the search term in title, description or body.
    All users can search ALL tickets in the workspace regardless of team membership.
    """
    # Base query for tickets in current workspace and not deleted
    base_query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    )
    
    # No team filtering - all users can search all tickets
    
    # Apply search on title, description and body
    search_term = f"%{q}%"  # Search term with wildcards for LIKE
    
    # Use join and OR condition to search across related tables
    query = base_query.join(TicketBody, Task.id == TicketBody.ticket_id, isouter=True).filter(
        or_(
            Task.title.ilike(search_term),
            Task.description.ilike(search_term),
            TicketBody.email_body.ilike(search_term)
        )
    )
    
    # Load relationships with eager loading
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
    
    # Order by creation date and apply pagination
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
    Get task by ID, including its body content and related details.
    Ensures the task belongs to the current user's workspace.
    """
    # Eager load relationships including the new 'body'
    task = db.query(Task).options(
        joinedload(Task.workspace),
        joinedload(Task.team),
        joinedload(Task.company),
        joinedload(Task.user),
        joinedload(Task.sent_from),
        joinedload(Task.sent_to),
        joinedload(Task.assignee),
        joinedload(Task.category), # Eager load category
        joinedload(Task.body) # Eager load the body
    ).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id, # Ensure task is in user's workspace
        Task.is_deleted == False
    ).first()

    if not task:
        # Use 404 even if it exists in another workspace for security
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

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
        # Emit ticket update event to all workspace clients
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
        await emit_ticket_update(updated_task_obj.workspace_id, task_data)
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


@router.get("/assignee/{agent_id}", response_model=List[TaskWithDetails]) # Use TaskWithDetails
async def read_assigned_tasks(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    # Add filter parameters (excluding assignee_id as it's the main filter)
    subject: Optional[str] = Query(None, description="Filter by subject text (contains, case-insensitive)"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., Open, Closed, Unread)"),
    priority: Optional[str] = Query(None, description="Filter by priority (e.g., Low, Medium, High)"),
) -> Any:
    """
    Retrieve tasks assigned to a specific agent WITHIN the current user's workspace, with optional filters.
    """
     # Base query for assigned tasks
    query = db.query(Task).options(
        joinedload(Task.user) # Eager load the user relationship
    )
    # Apply mandatory filters sequentially
    query = query.filter(Task.assignee_id == agent_id)
    query = query.filter(Task.workspace_id == current_user.workspace_id)
    query = query.filter(Task.is_deleted == False)

    # Apply optional filters
    if subject:
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)

    # Apply ordering, offset, and limit
    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()

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
                    
                    # ✅ EXTRAER INFORMACIÓN DEL ORIGINAL-SENDER (como hacía el frontend)
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

        # Add initial content if we have it
        if initial_content:
            html_contents.append({
                "id": "initial",
                "content": initial_content,
                "sender": initial_sender,
                "is_private": False,
                "attachments": [],
                "created_at": comments[0].created_at if comments else task.created_at
            })

        # 2. Process ALL comments - much simpler approach
        
        # First, collect all S3 URLs that need to be fetched
        s3_urls_needed = []
        comment_mapping = {}
        
        for comment in comments:
            if comment.s3_html_url:
                s3_urls_needed.append(comment.s3_html_url)
                comment_mapping[comment.s3_html_url] = comment
        
        # Fetch all S3 content in parallel if we have any S3 URLs
        s3_content_cache = {}
        if s3_urls_needed:
            logger.info(f"Fetching {len(s3_urls_needed)} S3 contents in parallel for ticket {task_id}")
            
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
                        if extracted_images:
                            logger.info(f"Processed {len(extracted_images)} base64 images in comment {comment.id}")
                    except Exception as e:
                        logger.warning(f"Error processing images in comment {comment.id}: {e}")
            
            # If no S3 content, use database content
            if not content:
                content = comment.content or "Content not available"

            # ✅ DETERMINAR SENDER INFO - extraer de original-sender si existe
            import re
            original_sender_match = re.search(r'<original-sender>(.*?)\|(.*?)</original-sender>', content) if content else None
            
            if original_sender_match:
                # Es un mensaje de usuario con información extraída del HTML
                sender = {
                    "type": "user",
                    "name": original_sender_match.group(1).strip(),
                    "email": original_sender_match.group(2).strip(),
                    "created_at": comment.created_at
                }
            elif comment.agent:
                # Es un mensaje de agente real
                sender = {
                    "type": "agent",
                    "name": comment.agent.name,
                    "email": comment.agent.email,
                    "created_at": comment.created_at
                }
            else:
                # Fallback
                sender = {
                    "type": "unknown",
                    "name": "Unknown",
                    "email": "unknown",
                    "created_at": comment.created_at
                }

            # Process attachments
            attachments = []
            if comment.attachments:
                for att in comment.attachments:
                    attachments.append({
                        "id": att.id,
                        "file_name": att.file_name,
                        "content_type": att.content_type,
                        "file_size": att.file_size,
                        "s3_url": getattr(att, 's3_url', None),
                        "download_url": f"/api/v1/attachments/{att.id}"
                    })

            html_contents.append({
                "id": comment.id,
                "content": content,
                "sender": sender,
                "is_private": comment.is_private,
                "attachments": attachments,
                "created_at": comment.created_at
            })

        logger.info(f"Successfully retrieved HTML content for ticket {task_id}: {len(html_contents)} items")
        
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
