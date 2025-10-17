from typing import Any, List, Optional
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import re

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session, noload, joinedload
from sqlalchemy import or_, and_, func, String

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.task import Task, TicketBody
from app.models.agent import Agent
from app.models.user import User
from app.models.comment import Comment as CommentModel
from app.schemas.task import Task as TaskSchema, TaskWithDetails, TicketUpdate, TicketCreate, TicketMergeRequest, TicketMergeResponse
from app.models.microsoft import mailbox_team_assignments
from app.models.activity import Activity
from app.utils.logger import logger
from app.services.ticket_merge_service import TicketMergeService
from app.services.automation_service import execute_automations_for_ticket
from app.core.socketio import emit_new_ticket, emit_ticket_deleted
from app.services.s3_service import get_s3_service
from app.services.microsoft_service import MicrosoftGraphService
from app.utils.image_processor import extract_base64_images

logger = logging.getLogger(__name__)
router = APIRouter()

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
            from app.models.microsoft import MailboxConnection
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
                from app.services.microsoft_service import MicrosoftGraphService
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

@router.get("/", response_model=List[TaskSchema])
async def read_tasks_optimized_default(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    team_id: Optional[int] = Query(None),
    assignee_id: Optional[int] = Query(None),
    priority: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
) -> Any:

    return await read_tasks_optimized(
        db=db, skip=skip, limit=limit, current_user=current_user,
        subject=subject, status=status, team_id=team_id,
        assignee_id=assignee_id, priority=priority, category_id=category_id
    )
@router.get("/fast", response_model=List[TaskSchema])
async def read_tasks_optimized(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
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
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.user),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.category)
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
    
    return tasks


@router.get("/assignee/{agent_id}/fast", response_model=List[TaskSchema])
async def read_assigned_tasks_optimized(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
) -> Any:

    start_time = time.time()
    
    query = db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(

        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.user),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.category)
    )

    if subject:
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)

    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    query_time = time.time() - start_time
    
    return tasks


@router.get("/assignee/{agent_id}", response_model=List[TaskSchema])
async def read_assignee_tasks_optimized(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    start_time = time.time()
    
    query = db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(

        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.user),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.category)
    )

    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    query_time = time.time() - start_time
    
    return tasks


@router.get("/team/{team_id}", response_model=List[TaskSchema])
async def read_team_tasks_optimized(
    team_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    ENDPOINT OPTIMIZADO: Tasks asignadas a un equipo específico
    """
    start_time = time.time()

    query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(
        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.user),
        noload(Task.category),
        noload(Task.comments),
    )

    from app.models.agent import Agent
    from app.models.team import TeamMember
    query = query.join(Agent, Task.assignee_id == Agent.id).join(TeamMember, Agent.id == TeamMember.agent_id).filter(
        TeamMember.team_id == team_id
    )
    
    query = query.offset(skip).limit(limit)
    
    query_start = time.time()
    tasks = query.all()
    query_time = time.time() - query_start
    
    total_time = time.time() - start_time
    
    return tasks


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


@router.get("/count")
async def get_tasks_count(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    status: Optional[str] = Query(None),
    assignee_id: Optional[int] = Query(None),
) -> dict:

    start_time = time.time()
    
    query = db.query(func.count(Task.id)).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    )
    
    if status:
        query = query.filter(Task.status == status)
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    
    count = query.scalar()
    
    query_time = time.time() - start_time
    logger.info(f"FAST COUNT: {count} tasks contados en {query_time*1000:.2f}ms")
    
    return {"count": count, "query_time_ms": round(query_time * 1000, 2)}


@router.get("/count/my-tickets")
async def get_my_tickets_count(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> dict:
    """
    Cuenta los tickets asignados directamente al usuario actual.
    """
    start_time = time.time()
    
    # Contar tickets asignados al usuario actual (no cerrados)
    count = db.query(func.count(Task.id)).filter(
        Task.assignee_id == current_user.id,
        Task.workspace_id == current_user.workspace_id,
        Task.status != 'Closed',
        Task.is_deleted == False
    ).scalar() or 0
    
    query_time = time.time() - start_time
    logger.info(f"MY TICKETS COUNT: {count} tickets asignados al usuario {current_user.id} contados en {query_time*1000:.2f}ms")
    
    return {"count": count, "query_time_ms": round(query_time * 1000, 2)}


@router.get("/count/my-teams")
async def get_my_teams_tasks_count(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> dict:

    start_time = time.time()
    
    from app.models.team import Team, TeamMember
    is_admin_or_manager = current_user.role in ['admin', 'manager']
    
    total_count = 0
    
    if is_admin_or_manager:
        total_count = db.query(func.count(Task.id)).filter(
            Task.workspace_id == current_user.workspace_id,
            Task.status != 'Closed',
            Task.is_deleted == False
        ).scalar() or 0
    else:
        user_teams = db.query(Team).join(TeamMember).filter(
            TeamMember.agent_id == current_user.id,
            Team.workspace_id == current_user.workspace_id
        ).all()
        
        for team in user_teams:
            team_ticket_count = db.query(func.count(Task.id.distinct())).filter(
                or_(
                    Task.team_id == team.id,
                    and_(
                        Task.team_id.is_(None),
                        Task.mailbox_connection_id.isnot(None),
                        Task.mailbox_connection_id.in_(
                            db.query(mailbox_team_assignments.c.mailbox_connection_id).filter(
                                mailbox_team_assignments.c.team_id == team.id
                            )
                        )
                    )
                ),
                Task.status != 'Closed',
                Task.is_deleted == False,
                Task.workspace_id == current_user.workspace_id
            ).scalar() or 0
            
            total_count += team_ticket_count
    
    query_time = time.time() - start_time
    logger.info(f"MY TEAMS COUNT: {total_count} tickets contados en {query_time*1000:.2f}ms")
    
    return {"count": total_count, "query_time_ms": round(query_time * 1000, 2)}


@router.get("/stats")
async def get_tasks_stats(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> dict:

    start_time = time.time()
    
    stats = db.query(
        Task.status,
        func.count(Task.id).label('count')
    ).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).group_by(Task.status).all()
    
    result = {
        "stats": {stat.status: stat.count for stat in stats},
        "total": sum(stat.count for stat in stats)
    }
    
    query_time = time.time() - start_time
    logger.info(f"FAST STATS: Estadísticas generadas en {query_time*1000:.2f}ms")
    
    return {**result, "query_time_ms": round(query_time * 1000, 2)}


@router.get("/{task_id}", response_model=TaskWithDetails)
async def read_task(
    task_id: int,
    current_user: Agent = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:
    """
    Get a single ticket with ultra-smart optimization.
    This endpoint intelligently decides the best fetching strategy.
    """
    import time
    from app.services.cache_service import cached_ticket_exists_check
    from sqlalchemy.orm import joinedload, noload
    
    ultra_start = time.time()
    
    permissions_start = time.time()
    
    try:  
        ticket_exists = await cached_ticket_exists_check(
            db, task_id, current_user.workspace_id, current_user.id
        )
    except Exception as e:

        logger.warning(f"⚠️ Cache fallback: {e}")
        from sqlalchemy import exists as sql_exists
        ticket_exists = db.query(
            sql_exists().where(
                Task.id == task_id,
                Task.workspace_id == current_user.workspace_id,
                Task.is_deleted == False
            )
        ).scalar()
    
    if not ticket_exists:
        raise HTTPException(status_code=404, detail="Task not found")
    
    permissions_time = time.time() - permissions_start
    
    analysis_start = time.time()
    
    basic_query = db.query(Task.title, Task.description, Task.assignee_id, Task.user_id, Task.category_id).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first()
    
    if not basic_query:
        raise HTTPException(status_code=404, detail="Task not found")
    
    title, description, assignee_id, user_id, category_id = basic_query
    
    title_size = len(title) if title else 0
    desc_size = len(description) if description else 0
    total_content = title_size + desc_size
    
    relations_count = sum([bool(assignee_id), bool(user_id), bool(category_id)])
    
    if total_content < 50 and relations_count == 0:
        strategy = "MINIMAL"
        expected_time = "~5-10ms"
    elif total_content < 200 and relations_count <= 1:
        strategy = "ESSENTIAL_LITE"  
        expected_time = "~10-20ms"
    elif total_content < 1000 and relations_count <= 2:
        strategy = "BALANCED"
        expected_time = "~20-35ms"
    else:
        strategy = "COMPLETE"
        expected_time = "~35-50ms"
    
    analysis_time = time.time() - analysis_start
    
    execution_start = time.time()
    
    base_query = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).execution_options(
        compiled_cache={},
        autoflush=False,
        autocommit=False
    )

    if strategy == "MINIMAL":
        task = base_query.options(
            joinedload(Task.user),      
            joinedload(Task.sent_from), 
            noload(Task.workspace), noload(Task.assignee), noload(Task.category),
            noload(Task.sent_to), noload(Task.team), noload(Task.company), 
            noload(Task.comments), noload(Task.body), noload(Task.merged_by_agent)
        ).first()
        
    elif strategy == "ESSENTIAL_LITE":

        options = [

            joinedload(Task.user),      
            joinedload(Task.sent_from), 
        ]

        if assignee_id:
            options.append(joinedload(Task.assignee))
            options.append(noload(Task.category))
        elif category_id:
            options.append(noload(Task.assignee))
            options.append(joinedload(Task.category))
        else:
            options.extend([noload(Task.assignee), noload(Task.category)])
        options.extend([
            noload(Task.workspace), noload(Task.sent_to), noload(Task.team), 
            noload(Task.company), noload(Task.comments), noload(Task.body), 
            noload(Task.merged_by_agent)
        ])
            
        task = base_query.options(*options).first()
        
    elif strategy == "BALANCED":
        task = base_query.options(
            joinedload(Task.user),      
            joinedload(Task.sent_from), 
            joinedload(Task.assignee) if assignee_id else noload(Task.assignee),
            joinedload(Task.category) if category_id else noload(Task.category),
            noload(Task.workspace), noload(Task.sent_to),
            noload(Task.team), noload(Task.company), noload(Task.comments),
            noload(Task.body), noload(Task.merged_by_agent)
        ).first()
        
    else:  # COMPLETE
        task = base_query.options(
            joinedload(Task.assignee),
            joinedload(Task.user), 
            joinedload(Task.category),
            joinedload(Task.workspace),
            joinedload(Task.sent_from),
            noload(Task.sent_to), noload(Task.team), noload(Task.company), 
            noload(Task.comments), noload(Task.body), noload(Task.merged_by_agent)
        ).first()
    
    execution_time = time.time() - execution_start
    return TaskWithDetails.from_orm(task)


@router.put("/{task_id}/refresh", response_model=TaskWithDetails)
async def update_task_optimized_for_refresh(
    task_id: int,
    task_in: TicketUpdate, 
    request: Request,  
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    from fastapi import Request as FastAPIRequest
    from app.core.config import settings
    from sqlalchemy.orm import joinedload
    
    refresh_start_time = time.time()

    update_fields = [field for field, value in task_in.dict(exclude_unset=True).items() if value is not None]

    fetch_start = time.time()
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first()
    fetch_time = time.time() - fetch_start
    
    if not task:
        total_time = time.time() - refresh_start_time
        raise HTTPException(status_code=404, detail="Task not found")

    service_start = time.time()
    origin = request.headers.get("origin") or settings.FRONTEND_URL
    from app.services.task_service import update_task
    updated_task_dict = update_task(db=db, task_id=task_id, task_in=task_in, request_origin=origin)
    service_time = time.time() - service_start
    
    if not updated_task_dict:
        total_time = time.time() - refresh_start_time
        raise HTTPException(status_code=400, detail="Task update failed")

    reload_start = time.time()
    updated_task = db.query(Task).filter(Task.id == task_id).options(

        joinedload(Task.assignee),  
        joinedload(Task.user),      
        joinedload(Task.sent_from), 
        joinedload(Task.category),  

        noload(Task.workspace),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.merged_by_agent)
    ).first()
    reload_time = time.time() - reload_start
    
    # 4. Socket.IO (más rápido)
    socketio_start = time.time()
    try:
        task_data = {
            'id': updated_task.id,
            'title': updated_task.title,
            'status': updated_task.status,
            'priority': updated_task.priority,
            'workspace_id': updated_task.workspace_id,
            'assignee_id': updated_task.assignee_id,
            'team_id': updated_task.team_id,
            'user_id': updated_task.user_id,
            'updated_at': updated_task.updated_at.isoformat() if updated_task.updated_at else None
        }
        
        from app.core.socketio import emit_ticket_update_sync
        emit_ticket_update_sync(updated_task.workspace_id, task_data)
        socketio_time = time.time() - socketio_start
        
    except Exception as e:
        socketio_time = time.time() - socketio_start
        logger.warning(f"Socket.IO error en refresh optimizado: {e}")
    
    # 5. 📊 Performance summary
    total_time = time.time() - refresh_start_time
    
    # 🔧 CORREGIDO: Retornar schema con relaciones expandidas para mostrar contacto
    return TaskWithDetails.from_orm(updated_task)


@router.get("/{task_id}/initial-content")
def get_task_initial_content(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    try:
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
        if task.description and not task.description.startswith('[MIGRATED_TO_S3]'):
            return {
                "status": "content_in_database",
                "content": task.description,
                "message": "Content loaded from ticket description"
            }
        if task.body and task.body.email_body:
            if not task.body.email_body.startswith('[MIGRATED_TO_S3]'):
                return {
                    "status": "content_in_database", 
                    "content": task.body.email_body,
                    "message": "Content loaded from ticket body"
                }
        from app.models.comment import Comment as CommentModel
        initial_comment = db.query(CommentModel).filter(
            CommentModel.ticket_id == task_id
        ).order_by(CommentModel.created_at.asc()).first()

        if not initial_comment:
            fallback_content = task.description or task.body.email_body if task.body else ""
            if fallback_content and fallback_content.startswith('[MIGRATED_TO_S3]'):
                clean_content = fallback_content.replace('[MIGRATED_TO_S3]', '').strip()
                import re
                clean_content = re.sub(r'Content moved to S3: https://[^\s]*', '', clean_content).strip()
                fallback_content = clean_content or "Content not available"
            
            return {
                "status": "no_initial_comment",
                "content": fallback_content or "No initial content found",
                "message": "No initial comment found for this ticket"
            }
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
        try:
            from app.services.microsoft_service import MicrosoftGraphService
            from app.utils.image_processor import extract_base64_images
            
            ms_service = MicrosoftGraphService(db)
            processed_content = s3_content

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

    try:
        task = db.query(Task).options(
            joinedload(Task.user).joinedload(User.company)
        ).filter(
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

        
        def get_avatar_url(sender_type: str, agent=None, user=None):
            if sender_type == "agent" and agent and agent.avatar_url:
                return agent.avatar_url
            elif sender_type == "user":
                if user and user.avatar_url:
                    return user.avatar_url
                elif user and user.company and user.company.logo_url:
                    return user.company.logo_url
            return None
        
        s3_service = get_s3_service()

        comments = db.query(CommentModel).options(
            joinedload(CommentModel.agent),
            joinedload(CommentModel.attachments)
        ).filter(
            CommentModel.ticket_id == task_id
        ).order_by(CommentModel.created_at.asc()).all()

        html_contents = []

        initial_content = None
        initial_sender = None

        if comments and comments[0].s3_html_url:
            try:
                s3_content = s3_service.get_comment_html(comments[0].s3_html_url)
                if s3_content:
                    initial_content = s3_content
                    import re
                    original_sender_match = re.search(r'<original-sender>(.*?)\|(.*?)</original-sender>', s3_content)
                    
                    if original_sender_match:
                        user_name = original_sender_match.group(1).strip()
                        user_email = original_sender_match.group(2).strip()

                        user = db.query(User).options(
                            joinedload(User.company)
                        ).filter(
                            User.email == user_email,
                            User.workspace_id == current_user.workspace_id
                        ).first()
                        
                        initial_sender = {
                            "type": "user", 
                            "name": user_name,
                            "email": user_email,
                            "created_at": comments[0].created_at,
                            "avatar_url": get_avatar_url("user", user=user)
                        }
                    elif comments[0].agent:
                        initial_sender = {
                            "type": "agent", 
                            "name": comments[0].agent.name,
                            "email": comments[0].agent.email,
                            "created_at": comments[0].created_at,
                            "avatar_url": get_avatar_url("agent", agent=comments[0].agent)
                        }
            except Exception as e:
                logger.warning(f"Failed to get initial S3 content: {e}")
        
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
                    "created_at": task.created_at,
                    "avatar_url": get_avatar_url("user", user=task.user)
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
        s3_content_cache = {}
        if s3_urls_needed:
            from concurrent.futures import as_completed
            
            def fetch_s3_content(s3_url):
                try:
                    content = s3_service.get_comment_html(s3_url)
                    return s3_url, content
                except Exception as e:
                    logger.warning(f"Failed to fetch S3 content from {s3_url}: {e}")
                    return s3_url, None
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_url = {executor.submit(fetch_s3_content, url): url for url in s3_urls_needed}
                
                for future in as_completed(future_to_url):
                    s3_url, content = future.result()
                    s3_content_cache[s3_url] = content
        for comment in comments:
            content = None  
            if (initial_content and comments and comment.id == comments[0].id and 
                comments[0].s3_html_url and initial_content != "Content not available"):
                continue
            if comment.s3_html_url and comment.s3_html_url in s3_content_cache:
                content = s3_content_cache[comment.s3_html_url]
                if content and 'data:image/' in content:
                    try:
                        from app.utils.image_processor import extract_base64_images
                        processed_content, extracted_images = extract_base64_images(content, task.id)
                        content = processed_content
                    except Exception as e:
                        logger.warning(f"Error processing images in comment {comment.id}: {e}")
            if not content:
                content = comment.content or "Content not available"

            import re
            original_sender_match = re.search(r'<original-sender>(.*?)\|(.*?)</original-sender>', content) if content else None
            
            if original_sender_match:
                user_name = original_sender_match.group(1).strip()
                user_email = original_sender_match.group(2).strip()
                user = db.query(User).options(
                    joinedload(User.company)
                ).filter(
                    User.email == user_email,
                    User.workspace_id == current_user.workspace_id
                ).first()
                
                sender = {
                    "type": "user",
                    "name": user_name,
                    "email": user_email,
                    "created_at": comment.created_at,
                    "avatar_url": get_avatar_url("user", user=user)
                }
            elif comment.agent:
                sender = {
                    "type": "agent",
                    "name": comment.agent.name,
                    "email": comment.agent.email,
                    "created_at": comment.created_at,
                    "avatar_url": get_avatar_url("agent", agent=comment.agent)
                }
            else:
                sender = {
                    "type": "unknown",
                    "name": "Unknown",
                    "email": "unknown",
                    "created_at": comment.created_at,
                    "avatar_url": None
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

@router.post("/merge", response_model=TicketMergeResponse)
async def merge_tickets(
    merge_request: TicketMergeRequest,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
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
