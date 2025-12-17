from typing import Any, List, Dict, Optional
from datetime import datetime, timezone
import asyncio
import base64
import time

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from pydantic import BaseModel
from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.agent import Agent as AgentModel
from app.models.comment import Comment as CommentModel
from app.models.scheduled_comment import ScheduledComment
from app.models.task import Task as TaskModel
from app.models.activity import Activity
from app.models.microsoft import MailboxConnection
from app.models.user import User
from app.schemas.comment import Comment as CommentSchema, CommentCreate, CommentUpdate
from app.schemas.task import TaskStatus, Task as TaskSchema, TicketWithDetails
from app.services.microsoft_service import get_microsoft_service, MicrosoftGraphService
from app.services.task_service import send_assignment_notification
from app.utils.logger import logger
from app.core.config import settings
from app.core.exceptions import MicrosoftAPIException, DatabaseException
from app.services.workflow_service import WorkflowService
from app.services.s3_service import get_s3_service
from app.utils.image_processor import extract_base64_images
from app.models.ticket_attachment import TicketAttachment
import re
router = APIRouter()

class CommentResponseModel(BaseModel):
    comment: Optional[CommentSchema] = None
    task: TicketWithDetails
    assignee_changed: bool
    is_scheduled: Optional[bool] = False
    scheduled_comment: Optional[Dict[str, Any]] = None

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
    start_time = time.time()
    pass
    permissions_start = time.time()
    task = db.query(TaskModel).options(joinedload(TaskModel.user)).filter(
        TaskModel.id == task_id,
        TaskModel.workspace_id == current_user.workspace_id,
        TaskModel.is_deleted == False
    ).first()
    permissions_time = time.time() - permissions_start

    if not task:
        total_time = time.time() - start_time
        logger.error(f"❌ PERFORMANCE: Ticket {task_id} no encontrado en workspace {current_user.workspace_id} (tiempo: {total_time*1000:.2f}ms)")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    query_start = time.time()
    comments_orm = db.query(CommentModel).options(
        joinedload(CommentModel.agent),
        joinedload(CommentModel.attachments)
    ).filter(
        CommentModel.ticket_id == task_id
    )

    comments_orm = comments_orm.order_by(
        CommentModel.created_at.asc()
    ).offset(skip).limit(limit).all()

    query_time = time.time() - query_start
    total_time = time.time() - start_time
    pass
    return comments_orm

@router.get("/tasks/{task_id}/scheduled_comments")
async def get_scheduled_comments(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    start_time = time.time()
    pass
    permissions_start = time.time()
    scheduled_comment = db.query(ScheduledComment).filter(
        ScheduledComment.ticket_id == task_id,
    )

    permissions_time = time.time() - permissions_start
    if not scheduled_comment:
            total_time = time.time() - start_time
            logger.error(f"Scheduled comment inside the task with id {task_id} was not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scheduled comment not found",
            )
    from app.services.s3_service import get_s3_service
    s3_service = get_s3_service()
    query_start = time.time()
    regex_matchS3 = re.escape("[MIGRATED_TO_S3] Content moved to S3: ")
    scheduled_comments_list: list = []
    for comment in scheduled_comment:
        agent = db.query(AgentModel).filter(
            AgentModel.id == comment.agent_id,
            AgentModel.workspace_id == current_user.workspace_id,
        ).first()
        url = comment.content
        if re.match(regex_matchS3, url):
            url = re.sub(regex_matchS3,'', url, count=1)
        s3_content:str = str(s3_service.get_comment_html(url))
        agent_name = agent.name if agent else "Unknown"
        dateScheduled: str = comment.scheduled_send_at.strftime("%Y-%m-%d %H:%M:%S")
        scheduled_comments_list.append({
            "due_date": dateScheduled,
            "status": comment.status,
            "content": s3_content,
            "agent_name": agent_name,
        })
    query_time = time.time() - query_start
    total_time = time.time() - start_time
    logger.info(
        f"Query time: {query_time:.4f}s | Permissions time: {permissions_time:.4f}s | Total time: {total_time:.4f}s"
    )
    return scheduled_comments_list


@router.get("/tasks/{task_id}/comments/fast", response_model=List[CommentSchema])
async def read_comments_optimized(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user),
    skip: int = 0,
    limit: int = 50,

) -> Any:
    start_time = time.time()
    permissions_start = time.time()
    task_exists = db.query(TaskModel.id).filter(
        TaskModel.id == task_id,
        TaskModel.workspace_id == current_user.workspace_id,
        TaskModel.is_deleted == False
    ).first() is not None
    permissions_time = time.time() - permissions_start

    if not task_exists:
        total_time = time.time() - start_time
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    query_start = time.time()
    from sqlalchemy.orm import selectinload

    comments_orm = db.query(CommentModel).options(
        selectinload(CommentModel.agent),
        selectinload(CommentModel.attachments)
    ).filter(
        CommentModel.ticket_id == task_id
    ).order_by(
        CommentModel.created_at.asc()
    ).offset(skip).limit(limit).all()

    query_time = time.time() - query_start
    total_time = time.time() - start_time

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
    # Process TO recipients
    to_recipients = []
    logger.info(f"🔍 DEBUG: Background task received to_recipients: {comment_in.to_recipients}")
    if comment_in.to_recipients and not comment_in.is_private:
        try:
            from app.services.email_service import parse_other_destinaries
            to_recipients = parse_other_destinaries(comment_in.to_recipients)
            logger.info(f"✅ Parsed {len(to_recipients)} TO recipients for comment on task {task_id}: {to_recipients}")
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid email addresses in to_recipients: {str(e)}"
            )

    cc_recipients = []
    if comment_in.other_destinaries and not comment_in.is_private:
        try:
            from app.services.email_service import parse_other_destinaries

            cc_recipients = parse_other_destinaries(comment_in.other_destinaries)

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid email addresses in other_destinaries: {str(e)}"
            )
    else:
        pass  # No CC recipients to process
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
    task_stmt = select(TaskModel).options(
        joinedload(TaskModel.user)  # Eager load user to avoid lazy loading issues
    ).filter(
        TaskModel.id == task_id,
        TaskModel.workspace_id == current_user.workspace_id,
        TaskModel.is_deleted == False
    )
    task_result = await db.execute(task_stmt)
    task = task_result.scalar_one_or_none()

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

    # Check if primary contact needs to be updated based on the new "To" list
    if not comment_in.is_private and comment_in.to_recipients is not None:
        current_primary_email = task.user.email.lower() if task.user and task.user.email else None
        new_to_emails_lower = [email.strip().lower() for email in to_recipients]

        if current_primary_email and current_primary_email not in new_to_emails_lower:
            logger.info(f"Primary contact {current_primary_email} was removed from TO list for ticket {task_id}.")
            
            if new_to_emails_lower:
                # Set the first recipient as the new primary contact
                new_primary_email = to_recipients[0] # Use original casing
                
                new_primary_user_stmt = select(User).filter(
                    User.email.ilike(new_primary_email),
                    User.workspace_id == current_user.workspace_id
                )
                new_primary_user_result = await db.execute(new_primary_user_stmt)
                new_primary_user = new_primary_user_result.scalar_one_or_none()

                if new_primary_user:
                    task.user_id = new_primary_user.id
                    logger.info(f"Changed primary contact for ticket {task_id} to {new_primary_email} (User ID: {new_primary_user.id})")
                else:
                    logger.warning(f"Could not find existing user for new primary contact: {new_primary_email}. Primary contact will not be changed automatically.")
            else:
                # TO list is empty, so remove primary contact
                task.user_id = None
                logger.info(f"Removed primary contact for ticket {task_id} as TO list is empty.")
            db.add(task)

    # Update TO recipients on ticket
    # ✅ FIXED: Allow explicit clearing of TO recipients when user removes them
    # Distinguish between "not provided" (None) vs "intentionally cleared" (empty string)
    if comment_in.to_recipients is not None and not comment_in.is_private:
        # If user provided TO field (even if empty), update the ticket
        # This allows users to intentionally remove all TO recipients
        if to_recipients and len(to_recipients) > 0:
            task.to_recipients = ", ".join(to_recipients)
            logger.info(f"✅ Updated ticket {task_id} TO recipients: {task.to_recipients}")
        else:
            # User explicitly sent empty TO list - clear the TO recipients
            task.to_recipients = None
            logger.info(f"✅ Cleared TO recipients for ticket {task_id} (user removed all)")
        db.add(task)

    # Update CC recipients on ticket
    # ✅ FIXED: Allow explicit clearing of CC recipients when user removes them
    # Distinguish between "not provided" (None) vs "intentionally cleared" (empty string)
    if comment_in.other_destinaries is not None and not comment_in.is_private:
        # If user provided CC field (even if empty), update the ticket
        # This allows users to intentionally remove all CC recipients
        if cc_recipients and len(cc_recipients) > 0:
            task.cc_recipients = ", ".join(cc_recipients)
            logger.info(f"✅ Updated ticket {task_id} CC recipients: {task.cc_recipients}")
        else:
            # User explicitly sent empty CC list - clear the CC recipients
            task.cc_recipients = None
            logger.info(f"✅ Cleared CC recipients for ticket {task_id} (user removed all)")
        db.add(task)

    # Update BCC recipients on ticket
    # ✅ FIXED: Allow explicit clearing of BCC recipients when user removes them
    # Distinguish between "not provided" (None) vs "intentionally cleared" (empty string)
    if comment_in.bcc_recipients is not None and not comment_in.is_private:
        # If user provided BCC field (even if empty), update the ticket
        # This allows users to intentionally remove all BCC recipients
        if bcc_recipients and len(bcc_recipients) > 0:
            task.bcc_recipients = ", ".join(bcc_recipients)
            logger.info(f"✅ Updated ticket {task_id} BCC recipients: {task.bcc_recipients}")
        else:
            # User explicitly sent empty BCC list - clear the BCC recipients
            task.bcc_recipients = None
            logger.info(f"✅ Cleared BCC recipients for ticket {task_id} (user removed all)")
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
    if comment_in.scheduled_send_at:
        import pytz

        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        naive_scheduled = comment_in.scheduled_send_at.replace(tzinfo=None)
        scheduled_et = eastern.localize(naive_scheduled)

        logger.info(f"🕐 Received from frontend: {comment_in.scheduled_send_at}")
        logger.info(f"🕐 Interpreted as ET: {scheduled_et}")
        logger.info(f"🕐 Current ET: {now_et}")

        if scheduled_et <= now_et:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Scheduled send time must be in the future"
            )
        scheduled_utc = scheduled_et.astimezone(timezone.utc)
        scheduled_utc_naive = scheduled_utc.replace(tzinfo=None)
        scheduled_comment = ScheduledComment(
            ticket_id=task_id,
            agent_id=current_user.id,
            workspace_id=current_user.workspace_id,
            content=content_to_store,
            scheduled_send_at=scheduled_utc_naive,  # Use naive UTC time
            is_private=comment_in.is_private,
            other_destinaries=comment_in.other_destinaries,
            bcc_recipients=comment_in.bcc_recipients,
            attachment_ids=comment_in.attachment_ids or []
        )
        db.add(scheduled_comment)
        await db.commit()

        # Read back from DB to verify
        await db.refresh(scheduled_comment)
        logger.info(f"🕐 DEBUG - After DB storage:")
        logger.info(f"   DB stored: {scheduled_comment.scheduled_send_at}")
        logger.info(f"   DB type: {type(scheduled_comment.scheduled_send_at)}")


        logger.info(f"✅ Created scheduled comment {scheduled_comment.id} for task {task_id}")
        logger.info(f"   📅 Scheduled for ET: {scheduled_et}")
        logger.info(f"   📅 Stored as UTC: {scheduled_utc}")

        from app.schemas.scheduled_comment import ScheduledCommentResponse
        return CommentResponseModel(
            comment=None,  # No immediate comment for scheduled
            task=task,
            assignee_changed=False,
            is_scheduled=True,
            scheduled_comment=ScheduledCommentResponse.from_orm(scheduled_comment).dict()
        )
    comment = CommentModel(
        ticket_id=task_id,
        agent_id=current_user.id,
        workspace_id=current_user.workspace_id,
        content=content_to_store,
        s3_html_url=s3_html_url,
        to_recipients=comment_in.to_recipients,
        other_destinaries=comment_in.other_destinaries,
        bcc_recipients=comment_in.bcc_recipients,
        is_private=comment_in.is_private
    )
    db.add(comment)
    processed_attachment_ids = []
    if comment_in.attachment_ids:
        from app.models.ticket_attachment import TicketAttachment
        await db.commit()
        await db.refresh(comment)

        logger.info(f"Processing {len(comment_in.attachment_ids)} attachment IDs for comment ID {comment.id}: {comment_in.attachment_ids}")

        for attachment_id in comment_in.attachment_ids:
            attachment_stmt = select(TicketAttachment).filter(TicketAttachment.id == attachment_id)
            attachment_result = await db.execute(attachment_stmt)
            attachment = attachment_result.scalar_one_or_none()
            if attachment:
                prev_comment_stmt = select(CommentModel).filter(CommentModel.id == attachment.comment_id)
                prev_comment_result = await db.execute(prev_comment_stmt)
                prev_comment = prev_comment_result.scalar_one_or_none()
                if prev_comment and prev_comment.content == "TEMP_ATTACHMENT_PLACEHOLDER":
                    attachment.comment_id = comment.id
                    db.add(attachment)
                    processed_attachment_ids.append(attachment_id)
                    logger.info(f"Adjunto {attachment_id} asociado al comentario {comment.id}")
                else:
                    logger.warning(f"Adjunto {attachment_id} ya está asociado a un comentario no temporal")
            else:
                logger.warning(f"Adjunto {attachment_id} no encontrado al crear el comentario {comment.id}")
    else:
        await db.commit()
        await db.refresh(comment)
    if s3_html_url and comment.id:
        try:
            s3_service = get_s3_service()
            original_content = comment_in.content
            final_s3_url = s3_service.store_comment_html(comment.id, original_content)
            comment.s3_html_url = final_s3_url
            comment.content = f"[MIGRATED_TO_S3] Content moved to S3: {final_s3_url}"
            db.add(comment)

            logger.info(f"✅ S3 file renamed for comment {comment.id}: {final_s3_url}")
        except Exception as e:
            logger.warning(f"⚠️ Could not rename S3 file for comment {comment.id}: {str(e)}")

    workflow_results = []
    try:
        if comment_in.content and comment_in.content.strip() and not comment_in.is_attachment_upload:
            workflow_service = WorkflowService(db)
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
            workflow_results = await workflow_service.process_message_for_workflows(
                comment_in.content,
                current_user.workspace_id,
                workflow_context
            )

            if workflow_results:
                logger.info(f"Executed {len(workflow_results)} workflows for comment {comment.id} on task {task_id}")
                for result in workflow_results:
                    try:
                        execution_result = result.get('execution_result', {})
                        if execution_result.get('status') == 'completed':
                            for action_result in execution_result.get('results', []):
                                if action_result.get('status') == 'success':
                                    action_data = action_result.get('result', {})
                                    if 'assigned_to' in action_data and not assignee_changed:
                                        assignee_stmt = select(AgentModel).filter(
                                            AgentModel.email == action_data['assigned_to'],
                                            AgentModel.workspace_id == current_user.workspace_id
                                        )
                                        assignee_result = await db.execute(assignee_stmt)
                                        assignee = assignee_result.scalar_one_or_none()
                                        if assignee:
                                            task.assignee_id = assignee.id
                                            assignee_changed = True
                                            logger.info(f"Auto-assigned task {task_id} to {assignee.email} via workflow")
                                    if 'priority' in action_data:
                                        task.priority = action_data['priority']
                                        logger.info(f"Auto-set priority of task {task_id} to {action_data['priority']} via workflow")
                                    if 'category' in action_data:
                                        task.category = action_data['category']
                                        logger.info(f"Auto-categorized task {task_id} as {action_data['category']} via workflow")

                    except Exception as e:
                        logger.error(f"Error applying workflow result {result.get('workflow_id')}: {str(e)}")
                        continue

                # Commit changes made by workflows
                await db.commit()
                await db.refresh(task)

    except Exception as e:
        logger.error(f"Error processing workflows for comment {comment.id}: {str(e)}")

    try:
        activity = Activity(
            agent_id=current_user.id,
            source_type="Comment",
            source_id=task_id,
            action=f"commented on ticket #{task_id}" if not comment_in.is_attachment_upload else f"uploaded attachment to ticket #{task_id}",
            workspace_id=current_user.workspace_id
        )
        db.add(activity)
        logger.info(f"Activity logged for comment creation: comment {comment.id} on task {task_id} by agent {current_user.id}")
    except Exception as e:
        logger.error(f"Error creating activity for comment {comment.id}: {e}")
    await db.commit()
    await db.refresh(task)
    await db.refresh(comment)

    try:
        context = {'ticket': task, 'comment': comment, 'agent': current_user}
        executed_workflows = await WorkflowService.execute_workflows(
            db=db,
            trigger='comment.added',
            workspace_id=task.workspace_id,
            context=context
        )

        if not comment_in.is_private:
            if current_user:  # Es un agente
                agent_workflows = await WorkflowService.execute_workflows(
                    db=db,
                    trigger='agent.replied',
                    workspace_id=task.workspace_id,
                    context=context
                )
                executed_workflows.extend(agent_workflows)
            else:
                customer_workflows = await WorkflowService.execute_workflows(
                    db=db,
                    trigger='customer.replied',
                    workspace_id=task.workspace_id,
                    context=context
                )
                executed_workflows.extend(customer_workflows)

        if executed_workflows:
            logger.info(f"Executed workflows for comment creation {comment.id}: {executed_workflows}")

    except Exception as e:
        logger.error(f"Error executing workflows for comment creation {comment.id}: {str(e)}")
    if assignee_changed and task.assignee_id != current_user.id:
        try:
            origin_url = None
            if request:
                origin_url = str(request.headers.get("origin", ""))
            if not origin_url:
                origin_url = settings.FRONTEND_URL
            logger.info(f"Using {origin_url} for assignment notification")
            assigned_agent_stmt = select(AgentModel).filter(AgentModel.id == task.assignee_id)
            assigned_agent_result = await db.execute(assigned_agent_stmt)
            assigned_agent = assigned_agent_result.scalar_one_or_none()
            if assigned_agent:
                task.assignee = assigned_agent
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
                task_user_stmt = select(User).filter(User.id == task.user_id)
                task_user_result = await db.execute(task_user_stmt)
                task_user = task_user_result.scalar_one_or_none()

            agents_stmt = select(AgentModel).filter(
                AgentModel.workspace_id == task.workspace_id,
                AgentModel.is_active == True,
                AgentModel.id != current_user.id  # Don't notify the commenting agent
            )
            agents_result = await db.execute(agents_stmt)
            agents = agents_result.scalars().all()

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
                        notification_type="new_response_agent",  # Corregir tipo para agentes
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
        await db.commit()
        await db.refresh(comment)
        await db.refresh(task)
    except Exception as e:
        logger.error(f"Error in final commit for comment {comment.id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Error saving comment")

    if not comment_in.is_private:
        try:
            # Get the database path for background task
            db_path = str(settings.DATABASE_URI)

            background_tasks.add_task(
                run_send_email_in_background,
                task_id=task_id,
                comment_id=comment.id,
                comment_content=comment_in.content,
                agent_id=current_user.id,
                agent_email=current_user.email,
                agent_name=current_user.name,
                is_private=comment_in.is_private,
                to_recipients=to_recipients,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                processed_attachment_ids=processed_attachment_ids,
                db_path=db_path
            )
            logger.info(f"Email background task queued for comment {comment.id} on task {task_id}")
        except Exception as e:
            logger.error(f"Error queuing email background task for comment {comment.id}: {e}")

    # Load the task with all necessary relationships to prevent lazy loading issues
    from sqlalchemy.orm import selectinload

    task_with_details_stmt = select(TaskModel).options(
        # Use selectinload for collections to avoid cartesian product, joinedload for one-to-one
        selectinload(TaskModel.comments).selectinload(CommentModel.agent),
        selectinload(TaskModel.comments).selectinload(CommentModel.attachments),
        selectinload(TaskModel.email_mappings), # For is_from_email property
        joinedload(TaskModel.assignee),
        joinedload(TaskModel.user).selectinload(User.company), # Eager load user and its company
        joinedload(TaskModel.workspace),
        joinedload(TaskModel.team),
        joinedload(TaskModel.company),
        joinedload(TaskModel.sent_from),
        joinedload(TaskModel.sent_to),
        joinedload(TaskModel.category),
        joinedload(TaskModel.body),
        joinedload(TaskModel.merged_by_agent)
    ).filter(TaskModel.id == task_id)
    task_with_details_result = await db.execute(task_with_details_stmt)
    task_with_details = task_with_details_result.unique().scalar_one_or_none()

    comment_with_agent_stmt = select(CommentModel).options(
        joinedload(CommentModel.agent),
        joinedload(CommentModel.attachments)
    ).filter(CommentModel.id == comment.id)
    comment_with_agent_result = await db.execute(comment_with_agent_stmt)
    comment_with_agent = comment_with_agent_result.unique().scalar_one_or_none()

    response_data = CommentResponseModel(
        comment=comment_with_agent,
        task=task_with_details,
        assignee_changed=assignee_changed
    )

    def get_avatar_url(sender_type: str, agent=None, user=None):

        if sender_type == "agent" and agent and agent.avatar_url:
            return agent.avatar_url
        elif sender_type == "user":
            if user and user.avatar_url:
                return user.avatar_url
            elif user and user.company and user.company.logo_url:
                return user.company.logo_url
        return None

    try:
        task_user_result = await db.execute(
            select(User).options(joinedload(User.company)).filter(User.id == task.user_id)
        )
        task_user = task_user_result.scalar_one_or_none()

        comment_data = {
            'id': comment.id,
            'ticket_id': task_id,
            'agent_id': current_user.id,
            'agent_name': current_user.name,
            'agent_email': current_user.email,
            'agent_avatar': get_avatar_url("agent", agent=current_user),
            'user_id': task.user_id,
            'user_name': task_user.name if task_user else None,
            'user_email': task_user.email if task_user else None,
            'user_avatar': get_avatar_url("user", user=task_user),
            'content': comment_in.content,
            'other_destinaries': comment_in.other_destinaries,
            'bcc_recipients': comment_in.bcc_recipients,
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

        # Emitir evento de forma asíncrona
        from app.core.socketio import emit_comment_update
        await emit_comment_update(
            workspace_id=current_user.workspace_id,
            comment_data=comment_data
        )

        logger.info(f"📤 Socket.IO comment_updated event queued for workspace {current_user.workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error emitting Socket.IO event for comment {comment.id}: {str(e)}")

    # --- Process Mention Notifications for Private Notes ---
    if comment_in.is_private and comment_in.content:
        try:
            # Obtener la URL de origen para usar el subdominio correcto
            origin_url = None
            if request:
                origin_url = str(request.headers.get("origin", ""))
            if not origin_url:
                origin_url = settings.FRONTEND_URL

            # Procesar menciones en background para no bloquear la respuesta
            from app.services.email_service import process_mention_notifications
            notified_agents = await process_mention_notifications(
                db=db,
                comment_content=comment_in.content,
                workspace_id=current_user.workspace_id,
                ticket_id=task_id,
                ticket_title=task.title,
                mentioning_agent_id=current_user.id,
                request_origin=origin_url
            )

            if notified_agents:
                logger.info(f"✅ Mention notifications sent for comment {comment.id} on ticket {task_id}: {notified_agents}")
            else:
                logger.info(f"📝 No mention notifications sent for comment {comment.id} on ticket {task_id}")

        except Exception as e:
            logger.error(f"❌ Error processing mention notifications for comment {comment.id}: {str(e)}", exc_info=True)
    # --- End Process Mention Notifications ---

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
    if comment.workspace_id != current_user.workspace_id:
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete comment from another workspace",
        )

    db.delete(comment)
    db.commit()

    return comment
def run_send_email_in_background(*args, **kwargs):
    """Wrapper to run email function in background task."""
    try:
        send_email_in_background(*args, **kwargs)
    except Exception as e:
        logger.error(f"Error running background email task: {e}", exc_info=True)

def send_email_in_background(
    task_id: int,
    comment_id: int,
    comment_content: str,
    agent_id: int,
    agent_email: str,
    agent_name: str,
    is_private: bool,
    to_recipients: List[str],
    cc_recipients: List[str],
    bcc_recipients: List[str],
    processed_attachment_ids: list,
    db_path: str
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, joinedload
    from sqlalchemy import select
    from app.models.task import Task as TaskModel
    from app.models.agent import Agent as AgentModel
    from app.models.microsoft import MailboxConnection

    engine = create_engine(db_path)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    with SessionLocal() as db:
        task_with_user = None

        try:
            from app.services.microsoft_service import MicrosoftGraphService
            agent = db.query(AgentModel).filter(AgentModel.id == agent_id).first()
            if not agent:
                logger.warning(f"Background email task: Agent {agent_id} not found.")
                return
                
            if is_private:
                logger.info(f"Background email task: Comment {comment_id} is private, skipping email.")
                return

            task_with_user = db.query(TaskModel).options(joinedload(TaskModel.user)).filter(TaskModel.id == task_id).first()

            if not task_with_user:
                logger.warning(f"Background email task: Task {task_id} not found.")
                return

            if task_with_user.mailbox_connection_id:
                logger.info(f"Background email task: Sending reply for task {task_id} via connected mailbox {task_with_user.mailbox_connection_id}")
                microsoft_service = MicrosoftGraphService(db)
                microsoft_service.send_reply_email(
                    task_id=task_id,
                    reply_content=comment_content,
                    agent=agent,
                    attachment_ids=processed_attachment_ids,
                    to_recipients=to_recipients,
                    cc_recipients=cc_recipients,
                    bcc_recipients=bcc_recipients
                )
            else:
                if not task_with_user.user or not task_with_user.user.email:
                    logger.warning(f"Background email task: No user or user email for task {task_id}. Cannot send new email.")
                    return

                recipient_email = task_with_user.user.email
                sender_mailbox_conn = db.query(MailboxConnection).filter(
                    MailboxConnection.workspace_id == task_with_user.workspace_id,
                    MailboxConnection.is_active == True
                ).first()

                if not sender_mailbox_conn:
                    logger.warning(f"Background email task: No active mailbox for workspace {task_with_user.workspace_id}.")
                    return

                sender_mailbox = sender_mailbox_conn.email
                subject = f"New comment on ticket #{task_id}: {task_with_user.title}"
                html_body = f"<p><strong>{agent_name} commented:</strong></p>{comment_content}"

                microsoft_service = MicrosoftGraphService(db)
                microsoft_service.send_new_email(
                    mailbox_email=sender_mailbox,
                    recipient_email=recipient_email,
                    subject=subject,
                    html_body=html_body,
                    attachment_ids=processed_attachment_ids,
                    task_id=task_id,
                    cc_recipients=cc_recipients,
                    bcc_recipients=bcc_recipients
                )
            logger.info(f"✅ Successfully sent email for comment {comment_id} on task {task_id}")

        except (MicrosoftAPIException, DatabaseException) as e:
            workspace_id = task_with_user.workspace_id if task_with_user else None
            logger.error(
                f"Error sending email in background for comment {comment_id}: {e}",
                extra={
                    "comment_id": comment_id,
                    "task_id": task_id,
                    "workspace_id": workspace_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
        except Exception as e:
            workspace_id = task_with_user.workspace_id if task_with_user else None
            logger.error(
                f"An unexpected error occurred in send_email_in_background for comment {comment_id}: {e}",
                extra={
                    "comment_id": comment_id,
                    "task_id": task_id,
                    "workspace_id": workspace_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )

@router.get("/comments/{comment_id}/s3-content")
def get_comment_s3_content(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
):
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
            ticket = db.query(TaskModel).filter(TaskModel.id == comment.ticket_id).first()
            if ticket:
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
            "content": processed_content,
            "s3_url": comment.s3_html_url,
            "message": "Content loaded from S3"
        }
        return response_data
    except Exception as e:
        logger.error(f"❌ Error getting S3 content for comment {comment_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get comment content: {str(e)}")
