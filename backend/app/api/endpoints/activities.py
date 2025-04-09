from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.agent import Agent
from app.models.activity import Activity
from app.models.task import Task
from app.schemas.activity import Activity as ActivitySchema, ActivityCreate

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


@router.post("/activities", response_model=ActivitySchema)
async def create_activity(
    activity_in: ActivityCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create a new activity record
    """
    # Asignar el usuario actual si no se especifica
    user_id = activity_in.user_id if activity_in.user_id else current_user.id
    
    # Crear el registro de actividad
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
    # Verificar que la tarea existe
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
    # Verificar que el agente existe
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    
    activities = db.query(Activity).filter(Activity.user_id == agent_id).order_by(Activity.created_at.desc()).offset(skip).limit(limit).all()
    return activities 