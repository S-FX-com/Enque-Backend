from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload # Re-import joinedload

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
# Use aliases for clarity if needed, or use original names
from app.models.agent import Agent as AgentModel
from app.models.comment import Comment as CommentModel
from app.models.task import Task as TaskModel
# CommentSchema now includes the agent object due to previous edit
from app.schemas.comment import Comment as CommentSchema, CommentCreate, CommentUpdate
from app.services.microsoft_service import get_microsoft_service, MicrosoftGraphService
from app.utils.logger import logger

router = APIRouter()


@router.get("/tasks/{task_id}/comments", response_model=List[CommentSchema])
async def read_comments(
    task_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Retrieve all comments for a task, ensuring the task belongs to the user's workspace.
    Includes agent details for each comment.
    """
    # Verificar que la tarea existe y pertenece al workspace del usuario (using model alias)
    task = db.query(TaskModel).filter(
        TaskModel.id == task_id,
        TaskModel.workspace_id == current_user.workspace_id, # Check workspace
        TaskModel.is_deleted == False
    ).first()

    if not task:
        # Log corrected message
        logger.error(f"Endpoint read_comments: Query failed to find active Task with id={task_id} in workspace {current_user.workspace_id}. Raising 404.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found", # Keep detail generic for security
        )

    # Query comments and explicitly load the 'agent' relationship
    # because the updated CommentSchema now expects it.
    comments_orm = db.query(CommentModel).options(
        joinedload(CommentModel.agent) # Eager load the agent relationship
    ).filter(
        CommentModel.ticket_id == task_id # Use correct column name
    )

    # Filter out private comments if the user is not an agent or admin
    #if current_user.role != "admin":
    #    comments_orm = comments_orm.filter(CommentModel.is_private == False)

    comments_orm = comments_orm.order_by(
        CommentModel.created_at.asc()  # Order ascending for conversation flow
    ).offset(skip).limit(limit).all()

    # Return the ORM objects directly. Pydantic's from_attributes=True
    return comments_orm


@router.post("/tasks/{task_id}/comments", response_model=CommentSchema)
async def create_comment(
    task_id: int,
    comment_in: CommentCreate,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Create a new comment for a task
    """
    # Verificar que la tarea existe (using model alias)
    task = db.query(TaskModel).filter(TaskModel.id == task_id, TaskModel.is_deleted == False).first()
    if not task:
        # Ensure the task belongs to the agent's workspace before allowing comment creation
        # This check might be redundant if task creation enforces workspace, but good practice.
        if task.workspace_id != current_user.workspace_id:
             logger.error(f"Attempt to create comment on task {task_id} from different workspace ({task.workspace_id}) by agent {current_user.id} in workspace {current_user.workspace_id}.")
             raise HTTPException(
                 status_code=status.HTTP_403_FORBIDDEN,
                 detail="Cannot comment on tasks outside your workspace.",
             )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    # Crear el comentario
    # Ensure workspace_id is available on the current_user (Agent) object
    if not hasattr(current_user, 'workspace_id') or not current_user.workspace_id:
         # Log an error and potentially raise an exception if workspace_id is missing
         logger.error(f"Agent {current_user.id} ({current_user.email}) is missing workspace_id. Cannot create comment.")
         raise HTTPException(
             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
             detail="Agent configuration error: Missing workspace ID.",
         )

    comment = CommentModel( # Use model alias
        ticket_id=task_id,
        agent_id=current_user.id,
        workspace_id=current_user.workspace_id,
        content=comment_in.content,
        is_private=comment_in.is_private
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Attempt to send the comment as an email reply if the task originated from email
    if not comment.is_private:
        try:
            logger.info(f"Attempting to send comment ID {comment.id} as email reply for task ID {task_id}")
            microsoft_service = get_microsoft_service(db)
            # Pass the agent object (current_user)
            # The send_reply_email function handles its own logging for success, failure, or non-applicability.
            # It returns True if successful OR if not applicable (e.g., task not from email).
            # It returns False only if an actual error occurred during the sending attempt.
            microsoft_service.send_reply_email(task_id=task_id, reply_content=comment.content, agent=current_user)
            # No need for additional logging here as the service function logs appropriately.

        except Exception as e:
            # Catch unexpected errors during the email sending process
            logger.error(f"Unexpected error trying to send email reply for comment ID {comment.id}, task ID {task_id}: {str(e)}", exc_info=True)
            # Do not re-raise, as the primary operation (saving comment) succeeded.

    return comment


@router.get("/comments/{comment_id}", response_model=CommentSchema)
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
    return comment


@router.put("/comments/{comment_id}", response_model=CommentSchema)
async def update_comment(
    comment_id: int,
    comment_in: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Update a comment, ensuring it belongs to the user's workspace.
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

    # Verificar que el agente actual es el propietario del comentario o es admin
    # Corrected: Check against agent_id, not user_id
    if comment.agent_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this comment",
        )

    # Check if the comment belongs to the current user's workspace before updating
    # Although agent check above might suffice, this adds an explicit layer.
    if comment.workspace_id != current_user.workspace_id:
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update comment from another workspace",
        )

    # Actualizar el comentario
    update_data = comment_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(comment, field, value)
    
    db.commit()
    db.refresh(comment)
    
    return comment


@router.delete("/comments/{comment_id}", response_model=CommentSchema)
async def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: AgentModel = Depends(get_current_active_user), # Use alias AgentModel
) -> Any:
    """
    Delete a comment, ensuring it belongs to the user's workspace.
    """
    # No need to load agent for delete, just find the comment
    comment = db.query(CommentModel).filter(CommentModel.id == comment_id).first()
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )

    # Verificar que el agente actual es el propietario del comentario o es admin
    # Corrected: Check against agent_id, not user_id
    if comment.agent_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to delete this comment",
        )

    # Check if the comment belongs to the current user's workspace before deleting
    if comment.workspace_id != current_user.workspace_id:
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete comment from another workspace",
        )

    db.delete(comment)
    db.commit()
    
    return comment
