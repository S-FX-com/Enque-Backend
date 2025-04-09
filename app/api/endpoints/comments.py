from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from typing import List

from app.models.agent import Agent
from app.schemas.comment import CommentCreate, CommentResponse, CommentUpdate
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.services.comment import (
    create_comment,
    get_comments,
    get_comment,
    update_comment,
    delete_comment,
)

router = APIRouter()


@router.post("/", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def create_comment_route(
    comment: CommentCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return create_comment(db, comment)


@router.get("/", response_model=List[CommentResponse])
def get_comments_route(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_comments(db, request, skip, limit)


@router.get("/{comment_id}", response_model=CommentResponse)
def get_comment_route(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_comment(db, comment_id)


@router.put("/{comment_id}", response_model=CommentResponse)
def update_comment_route(
    comment_id: int,
    comment: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return update_comment(db, comment_id, comment)


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment_route(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    delete_comment(db, comment_id)
    return None
