from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_ # Import 'or_' for OR condition

# Import dependencies
from app.api.dependencies import get_current_active_user, get_current_active_admin_or_manager
from app.database.session import get_db
from app.models.task import Task
from app.models.agent import Agent
from app.models.user import User # Import User model
from app.models.team import TeamMember # Import TeamMember for filtering
from app.models.microsoft import EmailTicketMapping, MailboxConnection # Import MailboxConnection
from app.models.activity import Activity # Import Activity model
# Use TaskWithDetails and the renamed TicketCreate/TicketUpdate schemas
from app.schemas.task import TaskWithDetails, TicketCreate, TicketUpdate, EmailInfo, Task as TaskSchema
# Import logger if needed for activity logging errors
from app.utils.logger import logger
# Import update_task service function and Microsoft service
from app.services.task_service import update_task # Assuming update_task is here
from app.services.microsoft_service import MicrosoftGraphService # Import the service
from datetime import datetime # Import datetime

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
    - Admin/Manager: All tasks in the workspace, optionally filtered.
    - Agent: Tasks assigned to them OR to any team they belong to, optionally filtered.
    """
    base_query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    )

    # Apply role-based filtering first
    if current_user.role in ["admin", "manager"]:
        # Admins and Managers see all tasks in the workspace
        query = base_query
    elif current_user.role == "agent":
        # Agents see tasks assigned to them OR their teams
        # Get IDs of teams the agent belongs to
        agent_team_ids = db.query(TeamMember.team_id).filter(
            TeamMember.agent_id == current_user.id
        ).distinct().all()
        # Extract just the IDs
        team_ids = [t[0] for t in agent_team_ids]

        # Filter tasks: assigned to agent OR assigned to one of the agent's teams
        query = base_query.filter(
            or_(
                Task.assignee_id == current_user.id,
                Task.team_id.in_(team_ids) # Check if task's team_id is in the agent's team list
            )
        )
    else:
        # Should not happen with current roles, but handle defensively
        raise HTTPException(status_code=403, detail="User role not recognized for task access.")

    # Apply optional filters to the role-filtered query
    if subject:
        # Use ilike for case-insensitive contains search
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if team_id:
        query = query.filter(Task.team_id == team_id)
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


@router.post("/", response_model=TaskSchema)
async def create_task(
    task_in: TicketCreate, # Use the renamed schema TicketCreate
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
    # --- End Log Activity ---

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
                         html_body=html_body
                     )
                     if not email_sent:
                         logger.error(f"Failed to send new ticket email for task {task.id}")
                     else:
                         logger.info(f"Successfully sent new ticket email for task {task.id}")

        except Exception as email_error:
            logger.error(f"Error trying to send email for newly created ticket {task.id}: {str(email_error)}", exc_info=True)
            # Do not raise an exception here, ticket creation succeeded, email is secondary
    # --- End Send Email ---

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
    db: Session = Depends(get_db),
    # Inject the basic active user dependency
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Update a task. Requires admin/manager role to change assignee or team.
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

    # Check permissions *before* calling the service function
    is_changing_assignment = task_in.assignee_id is not None or task_in.team_id is not None
    if is_changing_assignment and current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Manager role required to change task assignment.",
        )

    # --- Optional: Further permission checks ---
    # Example: Allow agent to only update status/priority if assigned
    # if current_user.role == 'agent' and task.assignee_id != current_user.id:
    #     allowed_updates_for_agent = {'status', 'priority'}
    #     update_keys = set(task_in.dict(exclude_unset=True).keys())
    #     # Check if trying to update fields other than allowed ones OR assignment fields
    #     if not update_keys.issubset(allowed_updates_for_agent) and not is_changing_assignment:
    #          raise HTTPException(
    #              status_code=status.HTTP_403_FORBIDDEN,
    #              detail="Agent can only update status or priority of assigned tickets.",
    #          )
    # --- End Permission Check ---


    # Use the service function which handles the actual update logic
    # Remove the task_obj argument as the service function fetches it
    updated_task_obj = update_task(db=db, task_id=task_id, task_in=task_in)

    if not updated_task_obj: # Service function returns the updated ORM object or None
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, # Or appropriate error from service
            detail="Task update failed", # Or more specific error from service
        )

    # Return the updated ORM object
    return updated_task_obj


@router.delete("/{task_id}", response_model=TaskSchema)
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user), # Consider if only admin/manager should delete
) -> Any:
    """
    Delete a task (soft delete)
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

    # Soft delete (mark as deleted)
    task.is_deleted = True
    task.deleted_at = datetime.utcnow()

    db.commit()
    db.refresh(task)

    return task


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
    Retrieve tasks assigned to a specific team WITHIN the current user's workspace
    """
     # Add workspace filter
    tasks = db.query(Task).filter(
        Task.team_id == team_id,
        Task.workspace_id == current_user.workspace_id, # Filter by current user's workspace
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()

    return tasks
