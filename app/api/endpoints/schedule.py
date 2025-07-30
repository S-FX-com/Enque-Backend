from fastapi import APIRouter
from sqlalchemy.types import DateTime
from app.schemas.comment import Comment as CommentSchema, CommentCreate, CommentUpdate
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from app.database.session import get_db
from sqlalchemy.orm import Session, joinedload
from app.models.agent import Agent as AgentModel
from app.api.dependencies import get_current_active_user

router = APIRouter

@router.post('/tasks/{task_id}/comments/schedule')
async def create_scheduled_comment(task_id: int,
comment_in: CommentCreate,
request: Request,
background_tasks: BackgroundTasks,
db: Session = Depends(get_db),
current_user: AgentModel = Depends(get_current_active_user)
date:DateTime):
