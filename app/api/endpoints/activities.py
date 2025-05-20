from typing import Any, List, Dict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

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
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all activities
    """
    activities = db.query(Activity).order_by(Activity.created_at.desc()).offset(skip).limit(limit).all()
    return activities
@router.get("/notifications", response_model=List[ActivityWithDetails])
async def read_notifications(
    db: Session = Depends(get_db),
    limit: int = 10,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve recent activities relevant for notifications (e.g., ticket creations).
    Filters by the current user's workspace.
    """
    notifications = db.query(Activity).options(
        joinedload(Activity.agent) 
    ).filter(
        Activity.workspace_id == current_user.workspace_id,
        Activity.source_type == 'Ticket',
    ).order_by(
        Activity.created_at.desc()
    ).limit(limit).all()

    results = []
    for activity in notifications:
        activity_detail = ActivityWithDetails.from_orm(activity)
        activity_detail.creator_user_name = None
        activity_detail.creator_user_email = None
        activity_detail.creator_user_id = None
        if activity.source_type == 'Ticket':
            task = db.query(Task).options(
                joinedload(Task.user) 
            ).filter(Task.id == activity.source_id).first()
            if task and task.user: 
                activity_detail.creator_user_name = task.user.name
                activity_detail.creator_user_email = task.user.email 
                activity_detail.creator_user_id = task.user.id 
        results.append(activity_detail)
    background_tasks = BackgroundTasks()
    background_tasks.add_task(clean_old_notifications, db)

    return results


def clean_old_notifications(db: Session) -> None:
    """
    Helper function to delete notifications older than 2 days.
    This runs in the background to avoid impacting API response time.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=2)
        old_notifications = db.query(Activity).filter(
            Activity.created_at < cutoff_date,
            Activity.source_type == 'Ticket'  
        ).all()
        if old_notifications:
            count = len(old_notifications)
            for notification in old_notifications:
                db.delete(notification)
            
            db.commit()
            logger.info(f"Cleaned {count} notifications older than 2 days")
        
    except Exception as e:
        db.rollback()  
        logger.error(f"Error cleaning old notifications: {str(e)}")


@router.delete("/clean-old-notifications", response_model=Dict[str, Any])
async def manual_clean_old_notifications(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),  
) -> Dict[str, Any]:
    """
    Manually trigger cleanup of old notifications (older than 2 days).
    Admin access only.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=2)
        deleted = db.query(Activity).filter(
            Activity.created_at < cutoff_date,
            Activity.source_type == 'Ticket' 
        ).delete(synchronize_session=False)
        
        db.commit()
        
        logger.info(f"Manually cleaned {deleted} notifications older than 2 days by admin {current_user.id}")
        return {"success": True, "deleted_count": deleted, "message": f"Successfully deleted {deleted} old notifications"}
        
    except Exception as e:
        db.rollback()
        error_msg = f"Error cleaning old notifications: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/activities", response_model=ActivitySchema)
async def create_activity(
    activity_in: ActivityCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create a new activity record
    """
    user_id = activity_in.user_id if activity_in.user_id else current_user.id
    activity = Activity(
        user_id=user_id,
        task_id=activity_in.task_id,
        action=activity_in.action
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    
    return activity


@router.get("/tasks/{task_id}/activities", response_model=List[ActivitySchema])
async def read_task_activities(
    task_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all activities for a specific task
    """
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    activities = db.query(Activity).filter(Activity.task_id == task_id).order_by(Activity.created_at.desc()).offset(skip).limit(limit).all()
    return activities


@router.get("/agents/{agent_id}/activities", response_model=List[ActivitySchema])
async def read_user_activities(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all activities for a specific user
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    
    activities = db.query(Activity).filter(Activity.user_id == agent_id).order_by(Activity.created_at.desc()).offset(skip).limit(limit).all()
    return activities


@router.delete("/notifications/all", response_model=Dict[str, Any])
async def delete_all_notifications(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Delete all notifications for the current user's workspace.
    This endpoint is used by the 'Clear all' button in the notifications panel.
    """
    try:
        deleted = db.query(Activity).filter(
            Activity.workspace_id == current_user.workspace_id,
            Activity.source_type == 'Ticket'  
        ).delete(synchronize_session=False)
        
        db.commit()
        
        logger.info(f"Deleted all {deleted} notifications for workspace {current_user.workspace_id} by user {current_user.id}")
        return {"success": True, "deleted_count": deleted, "message": f"Successfully deleted all notifications"}
        
    except Exception as e:
        db.rollback()
        error_msg = f"Error deleting notifications: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
