from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from enum import Enum
from app.schemas.workspace import WorkspaceResponse

class AgentRole(str, Enum):
    agent = "Agent"
    admin = "Admin"

class AgentBase(BaseModel):
    name: str
    email: EmailStr
    role: AgentRole = AgentRole.agent
    is_active: bool = True

class AgentCreate(AgentBase):
    password: str
    workspace_id: int

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    workspace_id: Optional[int] = None

class AgentResponse(AgentBase):
    id: int
    workspace: WorkspaceResponse
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True