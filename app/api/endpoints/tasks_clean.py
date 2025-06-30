from typing import Any, List, Optional
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import or_, and_
from app.api.dependencies import get_current_active_user, get_current_active_admin_or_manager
from app.database.session import get_db
from app.models.task import Task, TicketBody
from app.models.agent import Agent
from app.models.user import User
from app.models.team import TeamMember
from app.models.microsoft import EmailTicketMapping, MailboxConnection, mailbox_team_assignments
from app.models.activity import Activity
from app.schemas.task import TaskWithDetails, TicketCreate, TicketUpdate, EmailInfo, Task as TaskSchema
from app.utils.logger import logger
from app.services.task_service import update_task, send_assignment_notification
from app.services.microsoft_service import MicrosoftGraphService
from app.services.automation_service import execute_automations_for_ticket
from datetime import datetime
from app.core.config import settings
from app.core.socketio import emit_new_ticket, emit_ticket_update, emit_ticket_deleted, emit_comment_update
router = APIRouter()
@router.get("/", response_model=List[TaskWithDetails])
async def read_tasks(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None, description="Filter by subject text (contains, case-insensitive)"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., Open, Closed, Unread)"),
    team_id: Optional[int] = Query(None, description="Filter by assigned team ID"),
    assignee_id: Optional[int] = Query(None, description="Filter by assigned agent ID"),
    priority: Optional[str] = Query(None, description="Filter by priority (e.g., Low, Medium, High)"),
    category_id: Optional[int] = Query(None, description="Filter by category ID"),
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
    query = base_query
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
    query = query.options(
        selectinload(Task.sent_from),
        selectinload(Task.sent_to),
        selectinload(Task.assignee),
        selectinload(Task.user),
        selectinload(Task.team),
        selectinload(Task.company),
        selectinload(Task.category),
    )
    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return tasks
@router.get("/search", response_model=List[TaskWithDetails])
async def search_tickets(
    q: str = Query(..., description="Search term to find in ticket title, description, body, or ticket ID"),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Search for tickets containing the search term in title, description, body, or by ticket ID.
    If the search query is numeric, it will search by ticket ID first, then by text.
    All users can search ALL tickets in the workspace regardless of team membership.
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
            selectinload(Task.sent_from),
            selectinload(Task.sent_to),
            selectinload(Task.assignee),
            selectinload(Task.user),
            selectinload(Task.team),
            selectinload(Task.company),
            selectinload(Task.category),
            selectinload(Task.body),
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
        selectinload(Task.sent_from),
        selectinload(Task.sent_to),
        selectinload(Task.assignee),
        selectinload(Task.user),
        selectinload(Task.team),
        selectinload(Task.company),
        selectinload(Task.category),
        selectinload(Task.body),
    )
    tickets = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return tickets
@router.post("/", response_model=TaskSchema)
async def create_task(
    task_in: TicketCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create a new task. All roles can create tasks.
    """
    task = Task(
        title=task_in.title,
        description=task_in.description,
        status=task_in.status,
        priority=task_in.priority,
        assignee_id=task_in.assignee_id,
        team_id=task_in.team_id,
        due_date=task_in.due_date,
        sent_from_id=current_user.id,
        sent_to_id=task_in.sent_to_id,
        user_id=task_in.user_id,
        company_id=task_in.company_id,
        workspace_id=current_user.workspace_id,
        category_id=task_in.category_id
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    try:
        task_with_relations = db.query(Task).options(
            selectinload(Task.user),
            selectinload(Task.assignee),
            selectinload(Task.company),
            selectinload(Task.category),
            selectinload(Task.team)
        ).filter(Task.id == task.id).first()
        if task_with_relations:
            executed_actions = execute_automations_for_ticket(db, task_with_relations)
            if executed_actions:
                logger.info(f"Automations executed for ticket {task.id}: {executed_actions}")
                db.refresh(task)
    except Exception as automation_error:
        logger.error(f"Error executing automations for ticket {task.id}: {str(automation_error)}", exc_info=True)
    try:
        activity = Activity(
            agent_id=current_user.id,
            action="created",
            source_type="Ticket",
            source_id=task.id,
            workspace_id=task.workspace_id
        )
        db.add(activity)
        db.commit()
        logger.info(f"Activity logged for ticket creation: {task.id} by agent {current_user.id}")
    except Exception as e:
        logger.error(f"Failed to log activity for ticket creation {task.id}: {str(e)}")
        db.rollback()
    if task.assignee_id:
        try:
            task.assignee = db.query(Agent).filter(Agent.id == task.assignee_id).first()
            request_origin = None
            if request:
                request_origin = str(request.headers.get("origin", ""))
                logger.info(f"Request origin detected for notification: {request_origin}")
            from app.services.task_service import send_assignment_notification
            await send_assignment_notification(db, task, request_origin)
        except Exception as e:
            logger.error(f"Failed to send assignment notification for task {task.id}: {str(e)}")
    
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
    
    try:
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
    try:
        user = db.query(User).filter(User.id == task.user_id).first()
        if user and user.email:
            recipient_email = user.email
            logger.info(f"Recipient email found: {recipient_email}")
            mailbox = db.query(MailboxConnection).filter(
                MailboxConnection.workspace_id == current_user.workspace_id
            ).first()
            if not mailbox:
                logger.warning(f"No mailbox connection found for workspace {current_user.workspace_id}. Cannot send email.")
            else:
                sender_mailbox = mailbox.email
                subject = task.title
                html_body = task.description
                microsoft_service = MicrosoftGraphService(db=db)
                logger.info(f"Attempting to send new ticket email for task {task.id} from {sender_mailbox} to {recipient_email}")
                email_sent = microsoft_service.send_new_email(
                    mailbox_email=sender_mailbox,
                    recipient_email=recipient_email,
                    subject=subject,
                    html_body=html_body,
                    task_id=task.id
                )
                if not email_sent:
                    logger.error(f"Failed to send new ticket email for task {task.id}")
                else:
                    logger.info(f"Successfully sent new ticket email for task {task.id}")
    except Exception as email_error:
        logger.error(f"Error trying to send email for newly created ticket {task.id}: {str(email_error)}", exc_info=True)
    return task
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
    task = db.query(Task).options(
        selectinload(Task.workspace),
        selectinload(Task.team),
        selectinload(Task.company),
        selectinload(Task.user),
        selectinload(Task.sent_from),
        selectinload(Task.sent_to),
        selectinload(Task.assignee),
        selectinload(Task.category),
        selectinload(Task.body)
    ).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first()
    if not task:
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
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Update a task. All roles (admin, manager, agent) can update all fields including assignee and team.
    """
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
    origin = request.headers.get("origin") or settings.FRONTEND_URL
    updated_task_dict = update_task(db=db, task_id=task_id, task_in=task_in, request_origin=origin)
    if not updated_task_dict:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task update failed",
        )
    updated_task_obj = db.query(Task).options(
        selectinload(Task.workspace),
        selectinload(Task.team),
        selectinload(Task.company),
        selectinload(Task.user),
        selectinload(Task.sent_from),
        selectinload(Task.sent_to),
        selectinload(Task.assignee),
        selectinload(Task.category),
        selectinload(Task.body)
    ).filter(Task.id == task_id).first()
    if not updated_task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found after update",
        )
    try:
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
        from app.core.socketio import emit_ticket_update_sync
        emit_ticket_update_sync(updated_task_obj.workspace_id, task_data)
    except Exception as e:
        logger.error(f"Failed to emit ticket_updated event for task {task_id}: {str(e)}")
    return updated_task_obj
@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
   
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id
    ).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    workspace_id = task.workspace_id
    task.is_deleted = True
    db.commit()
    try:
        await emit_ticket_deleted(workspace_id, task_id)
    except Exception as e:
        logger.error(f"Failed to emit ticket_deleted event for task {task_id}: {str(e)}")
    return {"message": "Task deleted successfully"}
@router.get("/user/{user_id}", response_model=List[TaskSchema])
async def read_user_tasks(
    user_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
  
    tasks = db.query(Task).filter(
        Task.user_id == user_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return tasks
@router.get("/assignee/{agent_id}", response_model=List[TaskWithDetails])
async def read_assigned_tasks(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None, description="Filter by subject text (contains, case-insensitive)"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., Open, Closed, Unread)"),
    priority: Optional[str] = Query(None, description="Filter by priority (e.g., Low, Medium, High)"),
) -> Any:
    
    query = db.query(Task).options(
        selectinload(Task.user)
    )
    query = query.filter(Task.assignee_id == agent_id)
    query = query.filter(Task.workspace_id == current_user.workspace_id)
    query = query.filter(Task.is_deleted == False)
    if subject:
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)
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
   
    tasks = db.query(Task).filter(
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
        ),
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return tasks
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
        from app.services.s3_service import get_s3_service
        s3_service = get_s3_service()
        s3_content = s3_service.get_comment_html(initial_comment.s3_html_url)
        if not s3_content:
            logger.warning(f"Failed to retrieve initial content from S3 for ticket {task_id}, falling back to database")
            fallback_content = initial_comment.content or ""
            if fallback_content.startswith('[MIGRATED_TO_S3]'):
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
        comments = db.query(CommentModel).options(
            selectinload(CommentModel.agent),
            selectinload(CommentModel.attachments)
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
                        initial_sender = {
                            "type": "user", 
                            "name": original_sender_match.group(1).strip(),
                            "email": original_sender_match.group(2).strip(),
                            "created_at": comments[0].created_at
                        }
                    elif comments[0].agent:
                        initial_sender = {
                            "type": "agent", 
                            "name": comments[0].agent.name,
                            "email": comments[0].agent.email,
                            "created_at": comments[0].created_at
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
                    "created_at": task.created_at
                }
        if initial_content:
            # ✅ FIX: Obtener adjuntos del primer comentario si existe
            initial_attachments = []
            if comments and comments[0].attachments:
                for att in comments[0].attachments:
                    # Use S3 URL directly if available, otherwise use API endpoint
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
            # Fetching S3 contents in parallel
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
                        # Base64 images processed silently
                    except Exception as e:
                        logger.warning(f"Error processing images in comment {comment.id}: {e}")
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
        # Successfully retrieved HTML content
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
