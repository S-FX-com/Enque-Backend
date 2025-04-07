from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.task import Task
from app.models.microsoft import EmailTicketMapping
from app.schemas.task import TaskCreate, TaskUpdate, EmailInfo


def get_tasks(db: Session, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get all tasks"""
    return db.query(Task).filter(Task.is_deleted == False).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


def get_task_by_id(db: Session, task_id: int) -> Optional[Dict[str, Any]]:
    """Get a task by ID with email info if available"""
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        return None
    
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


def create_task(db: Session, task_in: TaskCreate, current_user_id: int = None) -> Task:
    """Create a new task"""
    task_data = task_in.dict()
    
    # Set the current user as the sent_from user if not specified
    if not task_data.get('sent_from_id') and current_user_id:
        task_data['sent_from_id'] = current_user_id
    
    task = Task(**task_data)
    db.add(task)
    db.commit()
    db.refresh(task)
    
    return task


def update_task(db: Session, task_id: int, task_in: TaskUpdate) -> Optional[Dict[str, Any]]:
    """Update a task"""
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        return None
    
    # Update task attributes
    update_data = task_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)
    
    db.commit()
    db.refresh(task)
    
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


def delete_task(db: Session, task_id: int) -> Optional[Task]:
    """Soft delete a task"""
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        return None
    
    # Soft delete (mark as deleted)
    task.is_deleted = True
    task.deleted_at = datetime.utcnow()
    
    db.commit()
    db.refresh(task)
    
    return task


def get_user_tasks(db: Session, user_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks for a specific user"""
    return db.query(Task).filter(
        Task.user_id == user_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


def get_assigned_tasks(db: Session, agent_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks assigned to a specific agent"""
    return db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


def get_team_tasks(db: Session, team_id: int, skip: int = 0, limit: int = 100) -> List[Task]:
    """Get tasks for a specific team"""
    return db.query(Task).filter(
        Task.team_id == team_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).offset(skip).limit(limit).all() 