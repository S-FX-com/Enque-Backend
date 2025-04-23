from typing import Optional, List, ForwardRef
from pydantic import BaseModel, EmailStr, validator
from datetime import datetime

# Forward references
WorkspaceRef = ForwardRef("Workspace")

# Base schema with common attributes
class AgentBase(BaseModel):
    name: str
    email: EmailStr
    role: str = "agent"
    is_active: bool = True
    
    @validator("role")
    def validate_role(cls, v):
        allowed_roles = ["admin", "agent", "manager"] # Add manager
        # Normalizar el rol si viene en mayúsculas
        if v == "Agent":
            return "agent"
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of {allowed_roles}")
        return v


# Schema for creating a new agent
class AgentCreate(AgentBase):
    password: str
    workspace_id: int


# Schema for updating an agent
class AgentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    
    @validator("role")
    def validate_role(cls, v):
        if v is not None:
            allowed_roles = ["admin", "agent", "manager"] # Add manager
            # Normalizar el rol si viene en mayúsculas
            if v == "Agent":
                return "agent"
            if v not in allowed_roles:
                raise ValueError(f"Role must be one of {allowed_roles}")
        return v


# Schema for agent in DB
class AgentInDBBase(AgentBase):
    id: int
    workspace_id: int
    created_at: Optional[datetime] = None # Make optional
    updated_at: Optional[datetime] = None # Make optional

    class Config:
        from_attributes = True


# Schema for returning agent details
class Agent(AgentInDBBase):
    pass


# Schema for returning agent with all details including relationships
class AgentWithDetails(Agent):
    workspace: WorkspaceRef
    
    class Config:
        from_attributes = True


# Update forward references
from app.schemas.workspace import Workspace

AgentWithDetails.update_forward_refs()
