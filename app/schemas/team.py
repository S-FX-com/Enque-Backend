from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

# Team schemas
class TeamBase(BaseModel):
    name: str
    description: Optional[str] = None


class TeamCreate(TeamBase):
    pass


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamInDBBase(TeamBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class Team(TeamInDBBase):
    pass


class TeamWithDetails(Team):
    # members: List["TeamMember"] = []
    pass


# TeamMember schemas
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
    # team: Team
    # agent: "Agent"
    pass 