from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List

from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.services.agent import (
    create_agent,
    get_agents,
    get_agent_by_id,
    update_agent,
    delete_agent
)

router = APIRouter()


@router.post("/", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent_route(
    agent: AgentCreate,
    db: Session = Depends(get_db)
):
    try:
        return create_agent(db, agent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[AgentResponse])
def get_agents_route(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    filters = {
        key[7:-1]: value
        for key, value in request.query_params.items()
        if key.startswith("filter[") and key.endswith("]")
    }

    return get_agents(db=db, filters=filters, skip=skip, limit=limit)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent_route(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    agent = get_agent_by_id(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentResponse)
def update_agent_route(
    agent_id: int,
    agent: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    updated = update_agent(db, agent_id, agent)
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return updated


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_route(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
):
    success = delete_agent(db, agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return None
