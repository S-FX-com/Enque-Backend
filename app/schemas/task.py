from typing import Optional, List, ForwardRef, Dict, Any
from pydantic import BaseModel, validator
from datetime import datetime
from enum import Enum as PyEnum
WorkspaceRef = ForwardRef("Workspace")
AgentRef = ForwardRef("Agent")
TeamRef = ForwardRef("Team")
UserRef = ForwardRef("User")
CompanyRef = ForwardRef("Company")
CategoryRef = ForwardRef("Category") 
TicketBodyRef = ForwardRef("TicketBodySchema")

class TaskStatus(str, PyEnum):
    UNREAD = "Unread"
    OPEN = "Open"
    WITH_USER = "With User" 
    IN_PROGRESS = "In Progress" 
    CLOSED = "Closed"
    RESOLVED = "Resolved" 


class TaskPriority(str, PyEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical" 


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
    category_id: Optional[int] = None 
    
    @validator("status")
    def validate_status(cls, v):
        if v not in TaskStatus.__members__.values():
             raise ValueError(f"Status must be one of {list(TaskStatus.__members__.values())}")
        return v
    
    @validator("priority")
    def validate_priority(cls, v):
        if v not in TaskPriority.__members__.values():
             raise ValueError(f"Priority must be one of {list(TaskPriority.__members__.values())}")
        return v

class TicketCreate(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.UNREAD
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    due_date: Optional[datetime] = None
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    user_id: int
    company_id: Optional[int] = None
    workspace_id: int
    category_id: Optional[int] = None
    cc_recipients: Optional[str] = None

class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    due_date: Optional[datetime] = None
    category_id: Optional[int] = None
    cc_recipients: Optional[str] = None
    
    @validator("status")
    def validate_status(cls, v):
        if v is not None:
            if v not in TaskStatus.__members__.values():
                 raise ValueError(f"Status must be one of {list(TaskStatus.__members__.values())}")
        return v
    
    @validator("priority")
    def validate_priority(cls, v):
        if v is not None:
            if v not in TaskPriority.__members__.values():
                 raise ValueError(f"Priority must be one of {list(TaskPriority.__members__.values())}")
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

class TicketInDBBase(BaseModel): 
    id: int
    title: str
    description: Optional[str] = None 
    status: TaskStatus
    priority: TaskPriority
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None
    user_id: Optional[int] = None 
    workspace_id: int 
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    category_id: Optional[int] = None 
    created_at: datetime
    updated_at: datetime
    last_update: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class Ticket(TicketInDBBase): 
    is_from_email: bool = False
    email_info: Optional[EmailInfo] = None

class TicketBodySchema(BaseModel):
    email_body: Optional[str] = None
    
    class Config:
        from_attributes = True
class TicketWithDetails(Ticket): 
    workspace: WorkspaceRef
    team: Optional[TeamRef] = None
    company: Optional[CompanyRef] = None
    user: Optional[UserRef] = None 
    sent_from: Optional[AgentRef] = None 
    sent_to: Optional[AgentRef] = None
    category: Optional[CategoryRef] = None 
    body: Optional[TicketBodyRef] = None 
    
    class Config:
        from_attributes = True


# Update forward references
from app.schemas.workspace import Workspace
from app.schemas.agent import Agent
from app.schemas.team import Team
from app.schemas.user import User
from app.schemas.company import Company
from app.schemas.category import Category 

TicketWithDetails.update_forward_refs() 
TicketBodySchema.update_forward_refs() 
Task = Ticket 
TaskWithDetails = TicketWithDetails
