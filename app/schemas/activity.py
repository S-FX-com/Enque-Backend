from pydantic import BaseModel
from typing import Union, Literal, Optional
from datetime import datetime
from app.schemas.agent import AgentResponse
from app.schemas.ticket import TicketResponse
from app.schemas.team import TeamResponse
from app.schemas.company import CompanyResponse
from app.schemas.user import UserResponse
from app.schemas.workspace import WorkspaceResponse

ActivitySourceTypes = Literal["Workspace", "Ticket", "Team", "Company", "User"]
ActivitySource = Union[WorkspaceResponse, TicketResponse, TeamResponse, CompanyResponse, UserResponse]


class ActivityBase(BaseModel):
    action: str
    source_type: ActivitySourceTypes


class ActivityCreate(ActivityBase):
    agent_id: int
    source_id: int
    workspace_id: int


class ActivityUpdate(ActivityBase):
    agent_id: int
    source_id: int


class ActivityResponse(ActivityBase):
    id: int
    agent: AgentResponse
    source: ActivitySource
    workspace: WorkspaceResponse
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
