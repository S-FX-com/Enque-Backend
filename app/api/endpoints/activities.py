from typing import Any, List, Dict
from datetime import datetime, timedelta
from sqlalchemy import select, delete

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user, get_current_active_admin
from app.database.session import get_db
from sqlalchemy.orm import joinedload
from app.models.agent import Agent
from app.models.activity import Activity
from app.models.task import Task
from app.models.user import User 
from app.schemas.activity import Activity as ActivitySchema, ActivityCreate, ActivityWithDetails
from app.utils.logger import logger 

router = APIRouter()


@router.get("/activities", response_model=List[ActivitySchema])
async def read_activities(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all activities
    """
    result = await db.execute(
        select(Activity).order_by(Activity.created_at.desc()).offset(skip).limit(limit)
    )
    activities = result.scalars().all()
    return activities
@router.get("/notifications", response_model=List[ActivityWithDetails])
async def read_notifications(
    db: AsyncSession = Depends(get_db),
    limit: int = 10,
    current_user: Agent = Depends(get_current_active_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> Any:
    """
    Retrieve recent activities relevant for notifications.
    Only shows:
    1. New tickets created by external users (not agents)
    2. Comments from external users (replied via email)
    Filters by the current user's workspace.
    """
    result = await db.execute(
        select(Activity).options(
            joinedload(Activity.agent),
            joinedload(Activity.workspace)
        ).filter(
            Activity.workspace_id == current_user.workspace_id,
            Activity.source_type.in_(['Ticket', 'Comment']),
        ).order_by(
            Activity.created_at.desc()
        ).limit(limit * 2)  # Get more to filter
    )
    notifications = result.scalars().all()

    results = []
    for activity in notifications:
        include_activity = False
        activity_detail = ActivityWithDetails.from_orm(activity)
        activity_detail.creator_user_name = None
        activity_detail.creator_user_email = None
        activity_detail.creator_user_id = None

        if activity.source_type == 'Ticket':
            task_result = await db.execute(
                select(Task).options(
                    joinedload(Task.user)
                ).filter(Task.id == activity.source_id)
            )
            task = task_result.scalars().first()
            if task and task.user and task.email_sender:
                activity_detail.creator_user_name = task.user.name
                activity_detail.creator_user_email = task.user.email
                activity_detail.creator_user_id = task.user.id
                include_activity = True

        elif activity.source_type == 'Comment':
            if activity.action and (" replied via email" in activity.action or " commented on ticket" in activity.action):
                user_name_part = activity.action.replace(" replied via email", "").replace(" commented on ticket", "")
                activity_detail.creator_user_name = user_name_part
                include_activity = True

        if include_activity:
            results.append(activity_detail)
        
        if len(results) >= limit:
            break
    
    background_tasks.add_task(clean_old_notifications, db)
    return results


async def clean_old_notifications(db: AsyncSession) -> None:
    """
    Helper function to delete notifications older than 2 days.
    This runs in the background to avoid impacting API response time.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=2)
        
        # This is a background task, so we can't pass the session from the request.
        # We need to create a new session.
        from app.database.session import AsyncSessionLocal
        async with AsyncSessionLocal() as async_db:
            stmt = delete(Activity).where(
                Activity.created_at < cutoff_date,
                Activity.source_type.in_(['Ticket', 'Comment'])
            )
            result = await async_db.execute(stmt)
            await async_db.commit()
            logger.info(f"Cleaned {result.rowcount} notifications older than 2 days")

    except Exception as e:
        logger.error(f"Error cleaning old notifications: {str(e)}")


@router.delete("/clean-old-notifications", response_model=Dict[str, Any])
async def manual_clean_old_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
) -> Dict[str, Any]:
    """
    Manually trigger cleanup of old notifications (older than 2 days).
    Admin access only.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=2)
        stmt = delete(Activity).where(
            Activity.created_at < cutoff_date,
            Activity.source_type.in_(['Ticket', 'Comment'])
        )
        result = await db.execute(stmt)
        await db.commit()
        
        deleted_count = result.rowcount
        logger.info(f"Manually cleaned {deleted_count} notifications older than 2 days by admin {current_user.id}")
        return {"success": True, "deleted_count": deleted_count, "message": f"Successfully deleted {deleted_count} old notifications"}
        
    except Exception as e:
        await db.rollback()
        error_msg = f"Error cleaning old notifications: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/activities", response_model=ActivitySchema)
async def create_activity(
    activity_in: ActivityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create a new activity record
    """
    user_id = activity_in.user_id if activity_in.user_id else current_user.id
    activity = Activity(
        user_id=user_id,
        task_id=activity_in.task_id,
        action=activity_in.action,
        workspace_id=current_user.workspace_id
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    
    return activity


@router.get("/tasks/{task_id}/activities", response_model=List[ActivitySchema])
async def read_task_activities(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all activities for a specific task
    """
    result = await db.execute(select(Task).filter(Task.id == task_id, Task.is_deleted == False))
    task = result.scalars().first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    result = await db.execute(
        select(Activity).filter(Activity.task_id == task_id).order_by(Activity.created_at.desc()).offset(skip).limit(limit)
    )
    activities = result.scalars().all()
    return activities


@router.get("/agents/{agent_id}/activities", response_model=List[ActivitySchema])
async def read_user_activities(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all activities for a specific user
    """
    result = await db.execute(select(Agent).filter(Agent.id == agent_id))
    agent = result.scalars().first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    
    result = await db.execute(
        select(Activity).filter(Activity.user_id == agent_id).order_by(Activity.created_at.desc()).offset(skip).limit(limit)
    )
    activities = result.scalars().all()
    return activities


@router.delete("/notifications/all", response_model=Dict[str, Any])
async def delete_all_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Delete all notifications for the current user's workspace.
    This endpoint is used by the 'Clear all' button in the notifications panel.
    """
    try:
        stmt = delete(Activity).where(
            Activity.workspace_id == current_user.workspace_id,
            Activity.source_type.in_(['Ticket', 'Comment'])
        )
        result = await db.execute(stmt)
        await db.commit()
        
        deleted_count = result.rowcount
        logger.info(f"Deleted all {deleted_count} notifications for workspace {current_user.workspace_id} by user {current_user.id}")
        return {"success": True, "deleted_count": deleted_count, "message": f"Successfully deleted all notifications"}
        
    except Exception as e:
        await db.rollback()
        error_msg = f"Error deleting notifications: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
