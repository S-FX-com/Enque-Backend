from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List

from app.models.agent import Agent
from app.schemas.activity import ActivityCreate, ActivityResponse, ActivityUpdate
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.services.activity import (
    create_activity,
    get_activities,
    get_activity_by_id,
    update_activity,
    delete_activity,
)

router = APIRouter()


@router.post("/", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED)
def create_activity_route(
    activity: ActivityCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    return create_activity(db, activity)


@router.get("/", response_model=List[ActivityResponse])
def get_activities_route(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    filters = {
        key[7:-1]: value
        for key, value in request.query_params.items()
        if key.startswith("filter[") and key.endswith("]")
    }

    return get_activities(db=db, filters=filters, skip=skip, limit=limit)


@router.get("/{activity_id}", response_model=ActivityResponse)
def get_activity_route(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    activity = get_activity_by_id(db, activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity


@router.put("/{activity_id}", response_model=ActivityResponse)
def update_activity_route(
    activity_id: int,
    activity: ActivityUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    updated = update_activity(db, activity_id, activity)
    if updated is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return updated


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity_route(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    success = delete_activity(db, activity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Activity not found")
    return None
