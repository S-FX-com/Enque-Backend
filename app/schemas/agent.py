from typing import Optional, List
from pydantic import BaseModel, EmailStr, validator
from datetime import datetime

# Base schema with common attributes
class AgentBase(BaseModel):
    name: str
    email: EmailStr
    role: str = "agent"
    
    @validator("role")
    def validate_role(cls, v):
        allowed_roles = ["admin", "manager", "agent"]
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of {allowed_roles}")
        return v


# Schema for creating a new agent
class AgentCreate(AgentBase):
    password: str


# Schema for updating an agent
class AgentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    avatar: Optional[str] = None
    role: Optional[str] = None
    
    @validator("role")
    def validate_role(cls, v):
        if v is not None:
            allowed_roles = ["admin", "manager", "agent"]
            if v not in allowed_roles:
                raise ValueError(f"Role must be one of {allowed_roles}")
        return v


# Schema for agent in DB
class AgentInDBBase(AgentBase):
    id: int
    avatar: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Schema for returning agent details
class Agent(AgentInDBBase):
    pass


# Schema for returning agent with all details including relationships
class AgentWithDetails(Agent):
    # These would be populated when relationships are needed
    # assigned_tasks: List["Task"] = []
    # teams: List["TeamMember"] = []
    pass 