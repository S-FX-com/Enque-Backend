from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.team import Team, TeamMember
from app.models.agent import Agent
from app.schemas.team import Team as TeamSchema, TeamCreate, TeamUpdate
from app.schemas.team import TeamMember as TeamMemberSchema, TeamMemberCreate

router = APIRouter()


@router.get("/teams", response_model=List[TeamSchema])
async def read_teams(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all teams
    """
    teams = db.query(Team).order_by(Team.name).offset(skip).limit(limit).all()
    return teams


@router.post("/teams", response_model=TeamSchema)
async def create_team(
    team_in: TeamCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create a new team
    """
    team = Team(**team_in.dict())
    db.add(team)
    db.commit()
    db.refresh(team)
    
    return team


@router.get("/teams/{team_id}", response_model=TeamSchema)
async def read_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get team by ID
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    return team


@router.put("/teams/{team_id}", response_model=TeamSchema)
async def update_team(
    team_id: int,
    team_in: TeamUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Update a team
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    # Update team attributes
    update_data = team_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(team, field, value)
    
    db.commit()
    db.refresh(team)
    
    return team


@router.delete("/teams/{team_id}", response_model=TeamSchema)
async def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Delete a team
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    db.delete(team)
    db.commit()
    
    return team


# Team Members endpoints
@router.get("/teams/{team_id}/members", response_model=List[TeamMemberSchema])
async def read_team_members(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all members of a team
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
    return members


@router.post("/teams/{team_id}/members", response_model=TeamMemberSchema)
async def add_team_member(
    team_id: int,
    member_in: TeamMemberCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Add a member to a team
    """
    # Check if team exists
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    # Check if agent exists
    agent = db.query(Agent).filter(Agent.id == member_in.agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    
    # Check if member already exists in team
    existing_member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.agent_id == member_in.agent_id
    ).first()
    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent is already a member of this team",
        )
    
    # Create team member
    member = TeamMember(team_id=team_id, agent_id=member_in.agent_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    
    return member


@router.delete("/teams/{team_id}/members/{agent_id}", response_model=TeamMemberSchema)
async def remove_team_member(
    team_id: int,
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Remove a member from a team
    """
    member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.agent_id == agent_id
    ).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team member not found",
        )
    
    db.delete(member)
    db.commit()
    
    return member 