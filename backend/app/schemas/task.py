from typing import Optional, List, ForwardRef, Dict, Any
from pydantic import BaseModel, validator
from datetime import datetime
from enum import Enum as PyEnum

# Forward references
WorkspaceRef = ForwardRef("Workspace")
AgentRef = ForwardRef("Agent")
TeamRef = ForwardRef("Team")
UserRef = ForwardRef("User")
CompanyRef = ForwardRef("Company")

class TaskStatus(str, PyEnum):
    UNREAD = "Unread"
    OPEN = "Open"
    CLOSED = "Closed"


class TaskPriority(str, PyEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.UNREAD
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    due_date: Optional[datetime] = None
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    user_id: Optional[int] = None
    company_id: Optional[int] = None
    workspace_id: Optional[int] = None
    
    @validator("status")
    def validate_status(cls, v):
        allowed_statuses = ["Unread", "Open", "Closed"]
        if v not in allowed_statuses:
            raise ValueError(f"Status must be one of {allowed_statuses}")
        return v
    
    @validator("priority")
    def validate_priority(cls, v):
        allowed_priorities = ["Low", "Medium", "High"]
        if v not in allowed_priorities:
            raise ValueError(f"Priority must be one of {allowed_priorities}")
        return v


class TicketCreate(TaskBase):
    workspace_id: int
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    user_id: int
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    user_id: Optional[int] = None
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    
    @validator("status")
    def validate_status(cls, v):
        if v is not None:
            allowed_statuses = ["Unread", "Open", "Closed"]
            if v not in allowed_statuses:
                raise ValueError(f"Status must be one of {allowed_statuses}")
        return v
    
    @validator("priority")
    def validate_priority(cls, v):
        if v is not None:
            allowed_priorities = ["Low", "Medium", "High"]
            if v not in allowed_priorities:
                raise ValueError(f"Priority must be one of {allowed_priorities}")
        return v


class EmailInfo(BaseModel):
    """Information about an email associated with a ticket"""
    id: int
    email_id: str
    email_conversation_id: Optional[str] = None
    email_subject: Optional[str] = None
    email_sender: Optional[str] = None
    email_received_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class TicketInDBBase(TaskBase):
    id: int
    workspace_id: int
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    user_id: int
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class Ticket(TicketInDBBase):
    is_from_email: bool = False
    email_info: Optional[EmailInfo] = None


class TicketWithDetails(Ticket):
    workspace: WorkspaceRef
    team: Optional[TeamRef] = None
    company: Optional[CompanyRef] = None
    user: UserRef
    sent_from: Optional[AgentRef] = None
    sent_to: Optional[AgentRef] = None
    
    class Config:
        from_attributes = True


# Update forward references
from app.schemas.workspace import Workspace
from app.schemas.agent import Agent
from app.schemas.team import Team
from app.schemas.user import User
from app.schemas.company import Company

TicketWithDetails.update_forward_refs()

# Alias Task to Ticket for backward compatibility
Task = Ticket
TaskBase = TaskBase
TaskCreate = TicketCreate
TaskUpdate = TicketUpdate
TaskInDBBase = TicketInDBBase
TaskWithDetails = TicketWithDetails 