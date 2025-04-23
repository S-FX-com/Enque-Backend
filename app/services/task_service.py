from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime
import threading

from app.models.task import Task
from app.models.microsoft import EmailTicketMapping
# from app.models.activity import Activity # No longer needed here
# Import the renamed schemas TicketCreate and TicketUpdate
from app.schemas.task import TicketCreate, TicketUpdate
from app.schemas.microsoft import EmailInfo
from app.utils.logger import logger, log_important
from app.database.session import SessionLocal # Import SessionLocal


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
        EmailTicketMapping.ticket_id == task.id
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


def create_task(db: Session, task_in: TicketCreate, current_user_id: int = None) -> Task: # Use TicketCreate
    """Create a new task"""
    task_data = task_in.dict()
    
    # Set the current user as the sent_from user if not specified
    if not task_data.get('sent_from_id') and current_user_id:
        task_data['sent_from_id'] = current_user_id
    
    task = Task(**task_data)
    db.add(task)
    db.commit()
    db.refresh(task)
    
    # --- Removed Activity Logging Logic ---
    # Activity logging should happen in the endpoint that calls this,
    # or the endpoint should call this service and pass the necessary user info.
    # Currently, the endpoint creates the task directly.

    return task


# Función auxiliar para marcar email como leído en segundo plano
def _mark_email_read_bg(task_id: int): # Remove db_session argument
    """Marcar email como leído en segundo plano usando una nueva sesión de DB."""
    db: Session = None # Initialize db to None
    try:
        # Create a new session specifically for this thread
        db = SessionLocal()
        if db is None:
             logger.error(f"Failed to create DB session for background task (ticket #{task_id})")
             return

        from app.services.microsoft_service import mark_email_as_read_by_task_id
        # Pass the new session to the service function
        success = mark_email_as_read_by_task_id(db, task_id)
        if success:
            log_important(f"Email successfully marked as read in background for ticket #{task_id}")
        else:
            logger.error(f"Could not mark email as read in background for ticket #{task_id}")
    except Exception as e:
        logger.error(f"Error in background email marking for ticket #{task_id}: {str(e)}")
    finally:
        # Ensure the session is closed even if an error occurs
        if db:
            db.close()


def update_task(db: Session, task_id: int, task_in: TicketUpdate) -> Optional[Dict[str, Any]]: # Use TicketUpdate
    """Update a task"""
    task = db.query(Task).filter(Task.id == task_id, Task.is_deleted == False).first()
    if not task:
        return None
    
    # Store the old status for comparison
    old_status = task.status

    # Update task attributes
    # Use exclude_unset=True to only include fields explicitly provided in the request
    update_data = task_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        # Pydantic validation ensures fields exist and have correct types (or None if Optional)
        # The previous change to TicketUpdate schema allows assignee_id to be None
        # setattr will correctly handle setting assignee_id to None if provided in update_data
        setattr(task, field, value)

    db.commit()
    db.refresh(task)

    # Explicitly reload relationships needed by TaskWithDetails after refresh
    # to ensure they are present in the returned object for serialization.
    db.refresh(task, attribute_names=['user', 'assignee', 'sent_from', 'sent_to', 'team', 'company', 'workspace', 'body'])

    # Check if task has email mapping
    email_mapping = db.query(EmailTicketMapping).filter(
        EmailTicketMapping.ticket_id == task.id
    ).first()
    
    # Preparar respuesta inmediatamente
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
    
    # Si status cambió de "Unread" a "Open" y tiene email mapping,
    # marcar el email como leído en Microsoft en segundo plano
    if email_mapping and old_status == "Unread" and task.status == "Open":
        log_important(f"Iniciando proceso de marcado de email como leído para ticket #{task.id}")
        
        # Crear un hilo para marcar email como leído en segundo plano
        # Pass only task.id, not the original db session
        mark_thread = threading.Thread(
            target=_mark_email_read_bg,
            args=(task.id,) # Note the comma to make it a tuple
        )
        mark_thread.daemon = True  # El hilo se cerrará cuando la aplicación termine
        mark_thread.start()

    # Return the refreshed Task ORM object directly.
    # FastAPI will serialize it using the TaskWithDetails response_model.
    # Note: Relationships might need explicit reloading if not handled by refresh/existing loads.
    return task


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
