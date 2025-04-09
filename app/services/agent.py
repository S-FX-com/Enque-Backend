from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate
from app.core.security import get_password_hash


def create_agent(db: Session, agent_data: AgentCreate) -> Agent:
    if db.query(Agent).filter(Agent.email == agent_data.email).first():
        raise ValueError("Email already registered")

    hashed_password = get_password_hash(agent_data.password)
    db_agent = Agent(
        name=agent_data.name,
        email=agent_data.email,
        hashed_password=hashed_password,
        workspace_id=agent_data.workspace_id
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)
    return db_agent


def get_agents(
    db: Session,
    filters: Optional[Dict[str, Any]] = None,
    skip: int = 0,
    limit: int = 100
) -> List[Agent]:
    query = db.query(Agent)

    if filters:
        filter_conditions = []
        for field_name, value in filters.items():
            if hasattr(Agent, field_name):
                column = getattr(Agent, field_name)
                col_type = column.property.columns[0].type.python_type

                try:
                    if col_type == int:
                        value = int(value)
                    elif col_type == float:
                        value = float(value)
                    elif col_type == bool:
                        value = str(value).lower() in ["true", "1", "yes"]
                except Exception:
                    continue

                if isinstance(value, str):
                    filter_conditions.append(column.ilike(f"%{value}%"))
                else:
                    filter_conditions.append(column == value)

        if filter_conditions:
            query = query.filter(and_(*filter_conditions))

    return query.offset(skip).limit(limit).all()


def get_agent_by_id(db: Session, agent_id: int) -> Optional[Agent]:
    return db.query(Agent).filter(Agent.id == agent_id).first()


def update_agent(
    db: Session,
    agent_id: int,
    update_data: AgentUpdate
) -> Optional[Agent]:
    db_agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if db_agent is None:
        return None

    for key, value in update_data.dict(exclude_unset=True).items():
        setattr(db_agent, key, value)

    db.commit()
    db.refresh(db_agent)
    return db_agent


def delete_agent(db: Session, agent_id: int) -> bool:
    db_agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if db_agent is None:
        return False

    db.delete(db_agent)
    db.commit()
    return True
