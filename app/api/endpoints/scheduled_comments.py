from typing import Any, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.agent import Agent as AgentModel
from app.models.scheduled_comment import ScheduledComment, ScheduledCommentStatus
from app.models.task import Task as TaskModel
from app.schemas.scheduled_comment import (
    ScheduledCommentCreate,
    ScheduledCommentUpdate,
    ScheduledCommentResponse,
    ScheduledCommentListResponse,
    ScheduledCommentStats
)
from app.utils.logger import logger

router = APIRouter()


@router.get("/tasks/{task_id}/scheduled-comments", response_model=List[ScheduledCommentListResponse])
async def get_scheduled_comments_for_task(
    task_id: int,
    status_filter: ScheduledCommentStatus = None,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
) -> Any:
    """Get all scheduled comments for a specific task."""
    
    # Verify task exists and user has access
    task = db.query(TaskModel).filter(
        TaskModel.id == task_id,
        TaskModel.workspace_id == current_user.workspace_id
    ).first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    # Build query
    query = db.query(ScheduledComment).filter(
        ScheduledComment.ticket_id == task_id,
        ScheduledComment.workspace_id == current_user.workspace_id
    )
    
    # Apply status filter if provided
    if status_filter:
        query = query.filter(ScheduledComment.status == status_filter)
    
    # Order by scheduled send time
    scheduled_comments = query.order_by(ScheduledComment.scheduled_send_at.asc()).all()
    
    return scheduled_comments


@router.get("/scheduled-comments", response_model=List[ScheduledCommentListResponse])
async def get_user_scheduled_comments(
    status_filter: ScheduledCommentStatus = None,
    limit: int = 50,
    skip: int = 0,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
) -> Any:
    """Get all scheduled comments for the current user."""
    
    query = db.query(ScheduledComment).filter(
        ScheduledComment.agent_id == current_user.id,
        ScheduledComment.workspace_id == current_user.workspace_id
    )
    
    # Apply status filter if provided
    if status_filter:
        query = query.filter(ScheduledComment.status == status_filter)
    
    # Order by scheduled send time
    scheduled_comments = query.order_by(
        ScheduledComment.scheduled_send_at.asc()
    ).offset(skip).limit(limit).all()
    
    return scheduled_comments


@router.get("/scheduled-comments/{comment_id}", response_model=ScheduledCommentResponse)
async def get_scheduled_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
) -> Any:
    """Get a specific scheduled comment."""
    
    scheduled_comment = db.query(ScheduledComment).filter(
        ScheduledComment.id == comment_id,
        ScheduledComment.agent_id == current_user.id,
        ScheduledComment.workspace_id == current_user.workspace_id
    ).first()
    
    if not scheduled_comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled comment not found"
        )
    
    return scheduled_comment


@router.put("/scheduled-comments/{comment_id}", response_model=ScheduledCommentResponse)
async def update_scheduled_comment(
    comment_id: int,
    update_data: ScheduledCommentUpdate,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
) -> Any:
    """Update a scheduled comment (only if status is 'pending')."""
    
    scheduled_comment = db.query(ScheduledComment).filter(
        ScheduledComment.id == comment_id,
        ScheduledComment.agent_id == current_user.id,
        ScheduledComment.workspace_id == current_user.workspace_id
    ).first()
    
    if not scheduled_comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled comment not found"
        )
    
    if scheduled_comment.status != ScheduledCommentStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot update scheduled comment with status '{scheduled_comment.status}'"
        )
    
    # Update fields
    update_dict = update_data.dict(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(scheduled_comment, field, value)
    
    scheduled_comment.updated_at = datetime.now(timezone.utc)
    
    db.add(scheduled_comment)
    db.commit()
    db.refresh(scheduled_comment)
    
    logger.info(f"✅ Updated scheduled comment {comment_id}")
    
    return scheduled_comment


@router.delete("/scheduled-comments/{comment_id}")
async def cancel_scheduled_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
) -> Any:
    """Cancel a scheduled comment (set status to 'cancelled')."""
    
    scheduled_comment = db.query(ScheduledComment).filter(
        ScheduledComment.id == comment_id,
        ScheduledComment.agent_id == current_user.id,
        ScheduledComment.workspace_id == current_user.workspace_id
    ).first()
    
    if not scheduled_comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled comment not found"
        )
    
    if scheduled_comment.status != ScheduledCommentStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel scheduled comment with status '{scheduled_comment.status}'"
        )
    
    scheduled_comment.status = ScheduledCommentStatus.CANCELLED.value
    scheduled_comment.updated_at = datetime.now(timezone.utc)
    
    db.add(scheduled_comment)
    db.commit()
    
    logger.info(f"✅ Cancelled scheduled comment {comment_id}")
    
    return {"message": "Scheduled comment cancelled successfully"}


@router.post("/scheduled-comments/{comment_id}/send-now")
async def send_scheduled_comment_now(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
) -> Any:
    """Send a scheduled comment immediately."""
    
    scheduled_comment = db.query(ScheduledComment).filter(
        ScheduledComment.id == comment_id,
        ScheduledComment.agent_id == current_user.id,
        ScheduledComment.workspace_id == current_user.workspace_id
    ).first()
    
    if not scheduled_comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled comment not found"
        )
    
    if scheduled_comment.status != ScheduledCommentStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot send scheduled comment with status '{scheduled_comment.status}'"
        )
    
    # Import and call the scheduled comment processor
    try:
        from app.services.scheduled_comment_service import send_scheduled_comment
        result = await send_scheduled_comment(scheduled_comment.id, db)
        
        if result["success"]:
            return {"message": "Scheduled comment sent successfully", "comment_id": result["comment_id"]}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send scheduled comment: {result['error']}"
            )
    
    except Exception as e:
        logger.error(f"❌ Error sending scheduled comment {comment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send scheduled comment: {str(e)}"
        )


@router.get("/scheduled-comments/stats", response_model=ScheduledCommentStats)
async def get_scheduled_comments_stats(
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user)
) -> Any:
    """Get statistics for user's scheduled comments."""
    
    from sqlalchemy import func
    
    stats = db.query(
        func.count(ScheduledComment.id).label("total"),
        func.sum(func.case([(ScheduledComment.status == ScheduledCommentStatus.PENDING.value, 1)], else_=0)).label("pending"),
        func.sum(func.case([(ScheduledComment.status == ScheduledCommentStatus.SENT.value, 1)], else_=0)).label("sent"),
        func.sum(func.case([(ScheduledComment.status == ScheduledCommentStatus.FAILED.value, 1)], else_=0)).label("failed"),
        func.sum(func.case([(ScheduledComment.status == ScheduledCommentStatus.CANCELLED.value, 1)], else_=0)).label("cancelled")
    ).filter(
        ScheduledComment.agent_id == current_user.id,
        ScheduledComment.workspace_id == current_user.workspace_id
    ).first()
    
    return ScheduledCommentStats(
        total=stats.total or 0,
        pending=stats.pending or 0,
        sent=stats.sent or 0,
        failed=stats.failed or 0,
        cancelled=stats.cancelled or 0
    )