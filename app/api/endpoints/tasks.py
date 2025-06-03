from typing import Any, List, Optional
import asyncio  # Importar asyncio

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
    Create a new task
    """
    # Set the current user as the sent_from user if not specified
    # Note: The schema might enforce user_id, adjust if needed
    # task_in.user_id = task_in.user_id or current_user.id # Assuming user_id refers to creator

    # Assuming workspace_id comes from the input or should be set from current_user
    if not hasattr(task_in, 'workspace_id') or not task_in.workspace_id:
         task_in.workspace_id = current_user.workspace_id

    # Pass category_id if present in task_in
    task_data = task_in.dict()
    task = Task(**task_data)
    db.add(task)
    db.commit()
    db.refresh(task)
    
    task.last_update = task.created_at 
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info(f"Task {task.id} created. Initial last_update set to {task.last_update}.")

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

    # --- Send Email for Manually Created Ticket ---
    if task.description and task.user: # Check if description exists and user is loaded
        try:
            # Get recipient email
            recipient_email = task.user.email
            if not recipient_email:
                 logger.warning(f"Cannot send email for ticket {task.id}: User {task.user_id} has no email address.") # Corrected indentation
            else:
                 # Find an active mailbox connection for the workspace to use as sender
                 mailbox = db.query(MailboxConnection).filter(
                     MailboxConnection.workspace_id == task.workspace_id,
                     MailboxConnection.is_active == True
                 ).first()

                 if not mailbox:
                     logger.warning(f"Cannot send email for ticket {task.id}: No active MailboxConnection found for workspace {task.workspace_id}.")
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
    # --- End Send Email ---

    # --- Send Notifications Based on Settings ---
    try:
        # Import notification service
        from app.services.notification_service import send_notification

        # 1. Notify user about ticket creation if enabled
        if task.user and task.user.email:
            template_vars = {
                "user_name": task.user.name,
                "ticket_id": task.id,
                "ticket_title": task.title
            }
            
            # Try to send notification
            await send_notification(
                db=db,
                workspace_id=task.workspace_id,
                category="users",
                notification_type="new_ticket_created",
                recipient_email=task.user.email,
                recipient_name=task.user.name,
                template_vars=template_vars,
                task_id=task.id
            )
            
        # 2. Notify agents about new ticket if enabled (to all agents)
        agents = db.query(Agent).filter(
            Agent.workspace_id == task.workspace_id,
            Agent.is_active == True
        ).all()
        
        for agent in agents:
            if agent.email:
                template_vars = {
                    "agent_name": agent.name,
                    "ticket_id": task.id,
                    "ticket_title": task.title,
                    "user_name": task.user.name if task.user else "Unknown User"
                }
                
                # Try to send notification
                await send_notification(
                    db=db,
                    workspace_id=task.workspace_id,
                    category="agents",
                    notification_type="new_ticket_created",
                    recipient_email=agent.email,
                    recipient_name=agent.name,
                    template_vars=template_vars,
                    task_id=task.id
                )
    
    except Exception as notification_error:
        logger.error(f"Error sending notifications for ticket {task.id}: {str(notification_error)}", exc_info=True)
    # --- End Send Notifications ---

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

    # Return the updated ORM object with all relationships
    return updated_task_obj


@router.delete("/{task_id}", response_model=TaskSchema)
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user), # Consider if only admin/manager should delete
) -> Any:
    """
    Delete a task (hard delete - physical removal)
    """
    # Add permission check if needed (e.g., only admin/manager)
    # if current_user.role not in ["admin", "manager"]:
    #     raise HTTPException(status_code=403, detail="Permission denied")

    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id, # Check workspace
        Task.is_deleted == False
        ).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Store task data for response before deletion
    task_data = TaskSchema.from_orm(task)

    # Hard delete (physical removal from database)
    db.delete(task)
    db.commit()

    return task_data


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
