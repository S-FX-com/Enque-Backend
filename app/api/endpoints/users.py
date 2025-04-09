from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from typing import List

from app.models.agent import Agent
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.services.user import (
    create_user,
    get_users,
    get_user,
    update_user,
    delete_user,
)

router = APIRouter()


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_route(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return create_user(db, user)


@router.get("/", response_model=List[UserResponse])
def get_users_route(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_users(db, request, skip, limit)


@router.get("/{user_id}", response_model=UserResponse)
def get_user_route(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_user(db, user_id)


@router.put("/{user_id}", response_model=UserResponse)
def update_user_route(
    user_id: int,
    user: UserUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return update_user(db, user_id, user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_route(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    delete_user(db, user_id)
    return
