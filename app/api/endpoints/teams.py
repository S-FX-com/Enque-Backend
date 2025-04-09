from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from typing import List

from app.models.agent import Agent
from app.schemas.team import TeamCreate, TeamResponse, TeamUpdate
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.services.team import (
    create_team,
    get_teams,
    get_team,
    update_team,
    delete_team,
)

router = APIRouter()


@router.post("/", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team_route(
    team: TeamCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return create_team(db, team)


@router.get("/", response_model=List[TeamResponse])
def get_teams_route(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_teams(db, request, skip, limit)


@router.get("/{team_id}", response_model=TeamResponse)
def get_team_route(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_team(db, team_id)


@router.put("/{team_id}", response_model=TeamResponse)
def update_team_route(
    team_id: int,
    team: TeamUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return update_team(db, team_id, team)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team_route(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    delete_team(db, team_id)
    return None
