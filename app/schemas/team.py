from typing import Optional, List, ForwardRef
from pydantic import BaseModel
from datetime import datetime

WorkspaceRef = ForwardRef("Workspace")
AgentRef = ForwardRef("Agent")

class TeamBase(BaseModel):
    name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    icon_name: Optional[str] = None
    manager_id: Optional[int] = None

class TeamCreate(TeamBase):
    workspace_id: int

class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    icon_name: Optional[str] = None
    manager_id: Optional[int] = None

class TeamInDBBase(TeamBase):
    id: int
    workspace_id: int
    created_at: datetime
    updated_at: datetime
    ticket_count: Optional[int] = None 
    
    class Config:
        from_attributes = True

class Team(TeamInDBBase):
    pass

class TeamWithDetails(Team):
    workspace: WorkspaceRef
    
    class Config:
        from_attributes = True
class TeamMemberBase(BaseModel):
    team_id: int
    agent_id: int

class TeamMemberCreate(TeamMemberBase):
    pass

class TeamMemberInDBBase(TeamMemberBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class TeamMember(TeamMemberInDBBase):
    pass

class TeamMemberWithDetails(TeamMember):
    team: Team
    agent: AgentRef
    
    class Config:
        from_attributes = True
from app.schemas.workspace import Workspace
from app.schemas.agent import Agent

TeamWithDetails.update_forward_refs()
TeamMemberWithDetails.update_forward_refs()
