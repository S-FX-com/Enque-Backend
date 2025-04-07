from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.task import Task
from app.models.agent import Agent
from app.models.microsoft import EmailTicketMapping
from app.schemas.task import Task as TaskSchema, TaskCreate, TaskUpdate, EmailInfo
from app.services.task_service import get_tasks, create_task, update_task, get_task_by_id

router = APIRouter()


@router.get("/tasks", response_model=List[TaskSchema])
async def read_tasks(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all tasks
    """
    tasks = db.query(Task).filter(Task.is_deleted == False).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return tasks


@router.post("/tasks", response_model=TaskSchema)
async def create_task(
    task_in: TaskCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create a new task
    """
    # Set the current user as the sent_from user if not specified
    if not task_in.sent_from_id:
        task_in.sent_from_id = current_user.id
    
    task = Task(**task_in.dict())
    db.add(task)
    db.commit()
    db.refresh(task)
    
    return task


@router.get("/tasks/{task_id}", response_model=TaskSchema)
async def read_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get task by ID
    """
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    # Check if task has email mapping
    email_mapping = db.query(EmailTicketMapping).filter(
        EmailTicketMapping.task_id == task.id
    ).first()
    
    task_dict = task.__dict__.copy()
    task_dict['is_from_email'] = email_mapping is not None
    
    if email_mapping:
        task_dict['email_info'] = EmailInfo(
            id=email_mapping.id,
            email_id=email_mapping.email_id,
            email_conversation_id=email_mapping.email_conversation_id,
            email_subject=email_mapping.email_subject,
            email_sender=email_mapping.email_sender,
            email_received_at=email_mapping.email_received_at
        )
    else:
        task_dict['email_info'] = None
    
    return task_dict


@router.put("/tasks/{task_id}", response_model=TaskSchema)
async def update_task_endpoint(
    task_id: int,
    task_in: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Update a task
    """
    # Use the service function which handles email marking as read logic
    task_dict = update_task(db, task_id, task_in)
    if not task_dict:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    return task_dict


@router.delete("/tasks/{task_id}", response_model=TaskSchema)
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Delete a task (soft delete)
    """
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    # Soft delete (mark as deleted)
    from datetime import datetime
    task.is_deleted = True
    task.deleted_at = datetime.utcnow()
    
    db.commit()
    db.refresh(task)
    
    return task


@router.get("/tasks/user/{user_id}", response_model=List[TaskSchema])
async def read_user_tasks(
    user_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all tasks for a specific user
    """
    tasks = db.query(Task).filter(
        Task.user_id == user_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    return tasks


@router.get("/tasks/assignee/{agent_id}", response_model=List[TaskSchema])
async def read_assigned_tasks(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all tasks assigned to a specific agent
    """
    tasks = db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    return tasks


@router.get("/tasks/team/{team_id}", response_model=List[TaskSchema])
async def read_team_tasks(
    team_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all tasks assigned to a specific team
    """
    tasks = db.query(Task).filter(
        Task.team_id == team_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    return tasks 