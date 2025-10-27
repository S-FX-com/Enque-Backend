"""
Service for processing scheduled comments.
This service handles converting scheduled comments to regular comments and sending them.
"""

from typing import Dict, Any, List
from datetime import datetime, timezone
import pytz
from sqlalchemy.orm import Session, joinedload

from app.models.scheduled_comment import ScheduledComment, ScheduledCommentStatus
from app.models.comment import Comment as CommentModel
from app.models.task import Task as TaskModel
from app.models.agent import Agent as AgentModel
from app.models.user import User
from app.utils.logger import logger
from app.services.microsoft_service import get_microsoft_service


async def get_content_from_s3_if_needed(content: str, scheduled_comment_id: int) -> str:
    """
    Helper function to retrieve content from S3 if it's a migrated content.
    
    Args:
        content: The content string (may contain S3 URL)
        scheduled_comment_id: ID for logging purposes
    
    Returns:
        The actual content (either original or retrieved from S3)
    """
    if not content.startswith('[MIGRATED_TO_S3]'):
        logger.info(f"🔍 Content for scheduled comment {scheduled_comment_id} is not migrated to S3")
        return content
    
    logger.info(f"🔍 Content for scheduled comment {scheduled_comment_id} is migrated to S3, extracting...")

    import re
    s3_url_match = re.search(r'https://[^\s]+\.html', content)
    if not s3_url_match:
        logger.warning(f"⚠️ No S3 URL found in migrated content for scheduled comment {scheduled_comment_id}")
        logger.warning(f"   Content: {content[:200]}...")  # Log first 200 chars for debugging
        return content
    
    s3_url = s3_url_match.group()
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(s3_url)
            if response.status_code == 200:
                logger.info(f"✅ Retrieved content from S3 for scheduled comment {scheduled_comment_id}")
                return response.text
            else:
                logger.warning(f"⚠️ Failed to retrieve S3 content for scheduled comment {scheduled_comment_id}: {response.status_code}")
                return content
    except Exception as s3_error:
        logger.error(f"❌ Error retrieving S3 content for scheduled comment {scheduled_comment_id}: {str(s3_error)}")
        return content


async def send_scheduled_comment(scheduled_comment_id: int, db: Session) -> Dict[str, Any]:
    try:
        scheduled_comment = db.query(ScheduledComment).options(
            joinedload(ScheduledComment.ticket),
            joinedload(ScheduledComment.agent)
        ).filter(
            ScheduledComment.id == scheduled_comment_id,
            ScheduledComment.status == ScheduledCommentStatus.PENDING
        ).first()
        
        if not scheduled_comment:
            return {"success": False, "error": "Scheduled comment not found or already processed"}
        task = scheduled_comment.ticket
        agent = scheduled_comment.agent
        
        if not task or not agent:
            return {"success": False, "error": "Associated task or agent not found"}
        content_for_comment = await get_content_from_s3_if_needed(scheduled_comment.content, scheduled_comment.id)
        comment = CommentModel(
            ticket_id=scheduled_comment.ticket_id,
            agent_id=scheduled_comment.agent_id,
            workspace_id=scheduled_comment.workspace_id,
            content=content_for_comment,  # Use the retrieved content
            is_private=scheduled_comment.is_private,
            other_destinaries=scheduled_comment.other_destinaries,
            bcc_recipients=scheduled_comment.bcc_recipients
        )
        
        db.add(comment)
        if scheduled_comment.attachment_ids:
            from app.models.ticket_attachment import TicketAttachment
            db.commit()
            db.refresh(comment)
            for attachment_id in scheduled_comment.attachment_ids:
                attachment = db.query(TicketAttachment).filter(
                    TicketAttachment.id == attachment_id
                ).first()
                
                if attachment:
                    attachment.comment_id = comment.id
                    db.add(attachment)
        scheduled_comment.status = ScheduledCommentStatus.SENT.value
        scheduled_comment.sent_at = datetime.now(timezone.utc)
        scheduled_comment.updated_at = datetime.now(timezone.utc)
        db.add(scheduled_comment)
        task.last_update = datetime.now(timezone.utc)
        db.add(task)
        db.commit()
        db.refresh(comment)
        if not scheduled_comment.is_private:
            try:
                await send_scheduled_comment_email(scheduled_comment, comment, db)
            except Exception as e:
                logger.error(f"❌ Failed to send email for scheduled comment {scheduled_comment_id}: {str(e)}")
        try:
            await emit_scheduled_comment_sent_event(scheduled_comment, comment, db)
        except Exception as e:
            logger.error(f"❌ Failed to emit Socket.IO event for scheduled comment {scheduled_comment_id}: {str(e)}")
        
        logger.info(f"✅ Successfully sent scheduled comment {scheduled_comment_id} as comment {comment.id}")
        
        return {"success": True, "comment_id": comment.id}
        
    except Exception as e:
        logger.error(f"❌ Error sending scheduled comment {scheduled_comment_id}: {str(e)}")
        
        # Update scheduled comment with error
        try:
            scheduled_comment = db.query(ScheduledComment).filter(
                ScheduledComment.id == scheduled_comment_id
            ).first()
            
            if scheduled_comment:
                scheduled_comment.status = ScheduledCommentStatus.FAILED.value
                scheduled_comment.error_message = str(e)
                scheduled_comment.retry_count += 1
                scheduled_comment.updated_at = datetime.now(timezone.utc)
                db.add(scheduled_comment)
                db.commit()
        except Exception as update_error:
            logger.error(f"❌ Failed to update scheduled comment error status: {str(update_error)}")
        
        return {"success": False, "error": str(e)}


async def send_scheduled_comment_email(
    scheduled_comment: ScheduledComment, 
    comment: CommentModel, 
    db: Session
) -> None:
    try:
        task = db.query(TaskModel).options(
            joinedload(TaskModel.user)
        ).filter(TaskModel.id == scheduled_comment.ticket_id).first()
        
        if not task or not task.user:
            logger.warning(f"⚠️ No task or user found for scheduled comment {scheduled_comment.id}")
            return
        
        # Get Microsoft service
        ms_service = get_microsoft_service(db)
        if not ms_service:
            logger.warning(f"⚠️ Microsoft service not available for scheduled comment {scheduled_comment.id}")
            return
        content_to_send = await get_content_from_s3_if_needed(scheduled_comment.content, scheduled_comment.id)
        if task.mailbox_connection_id:
            logger.info(f"📧 Sending reply email for scheduled comment {scheduled_comment.id}")
            ms_service.send_reply_email(
                task_id=scheduled_comment.ticket_id,
                reply_content=content_to_send,
                agent=scheduled_comment.agent,
                attachment_ids=[],  # Handle attachments if needed
                cc_recipients=[],   # Handle CC if needed
                bcc_recipients=[]   # Handle BCC if needed
            )
        else:
            # Task was created manually, send a new email notification
            if not task.user or not task.user.email:
                logger.warning(f"⚠️ No user email found for scheduled comment {scheduled_comment.id}")
                return
            
            recipient_email = task.user.email
            from app.models.microsoft import MailboxConnection
            sender_mailbox_conn = db.query(MailboxConnection).filter(
                MailboxConnection.workspace_id == scheduled_comment.workspace_id,
                MailboxConnection.is_active == True
            ).first()
            
            if not sender_mailbox_conn:
                logger.warning(f"⚠️ No active mailbox connection found for workspace {scheduled_comment.workspace_id}")
                return
            
            sender_mailbox = sender_mailbox_conn.email
            subject = f"New comment on ticket #{scheduled_comment.ticket_id}: {task.title}"
            html_body = f"<p><strong>{scheduled_comment.agent.name} commented:</strong></p>{content_to_send}"
            
            logger.info(f"📧 Sending new email for scheduled comment {scheduled_comment.id}")
            email_sent = ms_service.send_new_email(
                mailbox_email=sender_mailbox,
                recipient_email=recipient_email,
                subject=subject,
                html_body=html_body,
                attachment_ids=[],  # Handle attachments if needed
                task_id=scheduled_comment.ticket_id,
                cc_recipients=[],   # Handle CC if needed
                bcc_recipients=[]   # Handle BCC if needed
            )
            
            if not email_sent:
                logger.error(f"❌ Failed to send new email for scheduled comment {scheduled_comment.id}")
                return
            
            logger.info(f"✅ Successfully sent new email for scheduled comment {scheduled_comment.id}")
        
        logger.info(f"✅ Email sent for scheduled comment {scheduled_comment.id}")
        
    except Exception as e:
        logger.error(f"❌ Failed to send email for scheduled comment {scheduled_comment.id}: {str(e)}")
        raise


async def emit_scheduled_comment_sent_event(
    scheduled_comment: ScheduledComment,
    comment: CommentModel, 
    db: Session
) -> None:
    try:
        # Get task user with company relationship for avatar fallback
        task_user = db.query(User).options(
            joinedload(User.company)
        ).filter(User.id == scheduled_comment.ticket_id).first()
        
        # Helper function for avatar URL (same as in comments.py)
        def get_avatar_url(sender_type: str, agent=None, user=None):
            if sender_type == "agent" and agent and agent.avatar_url:
                return agent.avatar_url
            elif sender_type == "user":
                if user and user.avatar_url:
                    return user.avatar_url
                elif user and user.company and user.company.logo_url:
                    return user.company.logo_url
            return None
        
        comment_data = {
            'id': comment.id,
            'ticket_id': scheduled_comment.ticket_id,
            'agent_id': scheduled_comment.agent_id,
            'agent_name': scheduled_comment.agent.name,
            'agent_email': scheduled_comment.agent.email,
            'agent_avatar': get_avatar_url("agent", agent=scheduled_comment.agent),
            'user_id': task_user.id if task_user else None,
            'user_name': task_user.name if task_user else None,
            'user_email': task_user.email if task_user else None,
            'user_avatar': get_avatar_url("user", user=task_user),
            'content': scheduled_comment.content,
            'other_destinaries': scheduled_comment.other_destinaries,
            'bcc_recipients': scheduled_comment.bcc_recipients,
            'is_private': scheduled_comment.is_private,
            'created_at': comment.created_at.isoformat() if comment.created_at else None,
            'attachments': [],  # TODO: Load actual attachments if needed
            'was_scheduled': True,  # Flag to indicate this was originally scheduled
            'original_scheduled_time': scheduled_comment.scheduled_send_at.isoformat()
        }
        
        # Emit the event
        from app.core.socketio import emit_comment_update
        await emit_comment_update(
            workspace_id=scheduled_comment.workspace_id,
            comment_data=comment_data
        )
        
        logger.info(f"✅ Socket.IO event emitted for scheduled comment {scheduled_comment.id}")
        
    except Exception as e:
        logger.error(f"❌ Failed to emit Socket.IO event for scheduled comment {scheduled_comment.id}: {str(e)}")
        raise


def get_pending_scheduled_comments(db: Session) -> List[ScheduledComment]:
    eastern = pytz.timezone('US/Eastern')
    now_et = datetime.now(eastern)
    now_utc = now_et.astimezone(timezone.utc)
    # Convert to naive datetime for comparison with database
    now_utc_naive = now_utc.replace(tzinfo=None)
    
    logger.info(f"🕐 Current time - ET: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}, UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info(f"🕐 Comparing with naive UTC: {now_utc_naive}")
    
    pending_comments = db.query(ScheduledComment).filter(
        ScheduledComment.status == ScheduledCommentStatus.PENDING.value,
        ScheduledComment.scheduled_send_at <= now_utc_naive
    ).order_by(ScheduledComment.scheduled_send_at.asc()).all()
    
    if pending_comments:
        logger.info(f"🔍 Found {len(pending_comments)} scheduled comments ready to send")
        for comment in pending_comments:
            logger.info(f"  - Comment {comment.id}: scheduled for {comment.scheduled_send_at} UTC")
    
    return pending_comments


async def process_pending_scheduled_comments(db: Session) -> Dict[str, Any]:
    try:
        pending_comments = get_pending_scheduled_comments(db)
        
        if not pending_comments:
            return {
                "processed": 0,
                "successful": 0,
                "failed": 0,
                "errors": []
            }
        
        logger.info(f"🔄 Processing {len(pending_comments)} scheduled comments")
        
        successful = 0
        failed = 0
        errors = []
        
        for scheduled_comment in pending_comments:
            try:
                result = await send_scheduled_comment(scheduled_comment.id, db)
                
                if result["success"]:
                    successful += 1
                    logger.info(f"✅ Processed scheduled comment {scheduled_comment.id}")
                else:
                    failed += 1
                    errors.append(f"Comment {scheduled_comment.id}: {result['error']}")
                    logger.error(f"❌ Failed to process scheduled comment {scheduled_comment.id}: {result['error']}")
            
            except Exception as e:
                failed += 1
                error_msg = f"Comment {scheduled_comment.id}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"❌ Exception processing scheduled comment {scheduled_comment.id}: {str(e)}")
        
        logger.info(f"📊 Scheduled comments processing complete: {successful} successful, {failed} failed")
        
        return {
            "processed": len(pending_comments),
            "successful": successful,
            "failed": failed,
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"❌ Error in process_pending_scheduled_comments: {str(e)}")
        return {
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "errors": [str(e)]
        }