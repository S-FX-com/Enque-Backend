from typing import Any, List, Optional 
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func 

from app.api.dependencies import get_current_active_user, get_current_active_admin, get_current_workspace
from app.database.session import get_db
from app.models.agent import Agent
from app.models.team import Team, TeamMember
from app.models.task import Task 
from app.models.workspace import Workspace
from app.schemas.agent import Agent as AgentSchema, AgentCreate, AgentUpdate
from app.schemas.team import Team as TeamSchema
from app.core.security import get_password_hash
from app.utils.logger import logger 

router = APIRouter()

@router.get("/", response_model=List[AgentSchema])
async def read_agents(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0), 
    limit: int = Query(100, ge=1, le=200), 
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve agents for the current workspace with pagination.
    """
    logger.info(f"Fetching agents for workspace {current_workspace.id} with skip={skip}, limit={limit}")
    agents = db.query(Agent).filter(
        Agent.workspace_id == current_workspace.id
    ).order_by(Agent.name).offset(skip).limit(limit).all()
    logger.info(f"Retrieved {len(agents)} agents.")
    return agents


@router.post("/", response_model=AgentSchema)
async def create_agent(
    agent_in: AgentCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Create a new agent (admin only)
    """
    agent = db.query(Agent).filter(
        Agent.email == agent_in.email,
        Agent.workspace_id == current_workspace.id
    ).first()
    if agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in this workspace",
        )

    agent = Agent(
        name=agent_in.name,
        email=agent_in.email,
        password=get_password_hash(agent_in.password),
        role=agent_in.role,
        workspace_id=current_workspace.id,
        is_active=True,
        job_title=agent_in.job_title,
        phone_number=agent_in.phone_number,
        email_signature=agent_in.email_signature
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    return agent


@router.get("/{agent_id}", response_model=AgentSchema)
async def read_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get agent by ID
    """
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return agent


@router.put("/{agent_id}", response_model=AgentSchema)
async def update_agent(
    agent_id: int,
    agent_in: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Update an agent (admin only)
    """
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    update_data = agent_in.dict(exclude_unset=True)

    if "password" in update_data and update_data["password"]:
        update_data["password"] = get_password_hash(update_data["password"])
    elif "password" in update_data:
         del update_data["password"]


    for field, value in update_data.items():
        setattr(agent, field, value)

    db.commit()
    db.refresh(agent)

    return agent


@router.delete("/{agent_id}", response_model=AgentSchema)
async def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Delete an agent (admin only)
    """
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    if agent.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    db.delete(agent)
    db.commit()

    return agent


@router.get("/{agent_id}/teams", response_model=List[TeamSchema])
async def read_agent_teams(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user), 
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve teams that a specific agent belongs to within the current workspace.
    """
    target_agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    if not target_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found in this workspace",
        )
    teams_query = db.query(Team).join(TeamMember).filter(
        TeamMember.agent_id == agent_id,
        Team.workspace_id == current_workspace.id
    ).all()

    teams_with_counts = []
    for team_model in teams_query:

        ticket_count = db.query(func.count(Task.id)).filter(
            Task.team_id == team_model.id,
            Task.status.notin_(['Closed', 'Resolved']) 
        ).scalar() or 0
        
        team_schema = TeamSchema.from_orm(team_model)
        team_schema.ticket_count = ticket_count
        teams_with_counts.append(team_schema)
        
    return teams_with_counts
