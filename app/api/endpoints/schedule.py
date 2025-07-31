from datetime import datetime
from fastapi import APIRouter
from pytz import HOUR
from sqlalchemy.engine import create
from sqlalchemy.types import DateTime
from app.schemas.comment import Comment as CommentSchema, CommentCreate, CommentUpdate
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from app.database.session import get_db
from sqlalchemy.orm import Session, joinedload
from app.models.agent import Agent as AgentModel
from app.api.dependencies import get_current_active_user
from app.api.endpoints.comments import create_comment
from apscheduler.schedulers.blocking import BlockingScheduler

router = APIRouter

@router.post('/tasks/{task_id}/comments/schedule')
async def create_scheduled_comment(task_id: int,
comment_in: CommentCreate,
request: Request,
background_tasks: BackgroundTasks,
date: datetime,
db: Session = Depends(get_db),
current_user: AgentModel = Depends(get_current_active_user),
) -> Any:
    scheduled_task = BlockingScheduler()
    scheduled_task.add_job(create_comment(task_id, comment_in, request, background_tasks, db, current_user), 'cron', day=date.day, month = date.month, year=date.year, hour=date.hour, minute=date.minute)
    return
