from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum
from app.schemas.agent import AgentResponse
from app.schemas.workspace import WorkspaceResponse
from app.schemas.team import TeamResponse
from app.schemas.company import CompanyResponse
from app.schemas.user import UserResponse


class TicketStatus(str, Enum):
    unread = "Unread"
    open = "Open"
    closed = "Closed"


class TicketPriority(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"


class TicketBase(BaseModel):
    title: str
    description: str
    status: TicketStatus = TicketStatus.unread
    priority: TicketPriority = TicketPriority.medium
    due_date: Optional[datetime] = None


class TicketCreate(TicketBase):
    workspace_id: int
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    user_id: int
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    pass


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    due_date: Optional[datetime] = None
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    user_id: Optional[int] = None
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    deleted_at: Optional[bool] = None


class TicketResponse(TicketBase):
    id: int
    workspace: WorkspaceResponse
    team: Optional[TeamResponse] = None
    company: Optional[CompanyResponse] = None
    user: UserResponse
    sent_from: Optional[AgentResponse] = None
    sent_to: Optional[AgentResponse] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True
