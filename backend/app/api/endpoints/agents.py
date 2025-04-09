from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user, get_current_active_admin, get_current_workspace
from app.database.session import get_db
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.schemas.agent import Agent as AgentSchema, AgentCreate, AgentUpdate
from app.core.security import get_password_hash

router = APIRouter()


@router.get("/", response_model=List[AgentSchema])
async def read_agents(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve all agents
    """
    agents = db.query(Agent).filter(
        Agent.workspace_id == current_workspace.id
    ).order_by(Agent.name).offset(skip).limit(limit).all()
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
    # Check if email already exists in this workspace
    agent = db.query(Agent).filter(
        Agent.email == agent_in.email,
        Agent.workspace_id == current_workspace.id
    ).first()
    if agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in this workspace",
        )
    
    # Create new agent
    agent = Agent(
        name=agent_in.name,
        email=agent_in.email,
        password=get_password_hash(agent_in.password),
        role=agent_in.role,
        workspace_id=current_workspace.id,
        is_active=True
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
    
    # Update agent attributes
    update_data = agent_in.dict(exclude_unset=True)
    
    # Hash password if it's being updated
    if "password" in update_data and update_data["password"]:
        update_data["password"] = get_password_hash(update_data["password"])
    
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
    
    # Prevent deleting self
    if agent.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    
    db.delete(agent)
    db.commit()
    
    return agent 