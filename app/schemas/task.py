from typing import Optional, List
from pydantic import BaseModel, validator
from datetime import datetime

class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "Unread"
    priority: str = "Medium"
    due_date: Optional[datetime] = None
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    sent_from_id: int
    user_id: Optional[int] = None
    company_id: Optional[int] = None
    is_read: bool = False
    
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


class TaskCreate(TaskBase):
    user_id: Optional[int] = None
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    sent_from_id: int


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    user_id: Optional[int] = None
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    is_read: Optional[bool] = None
    
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
    """Information about an email associated with a task"""
    id: int
    email_id: str
    email_conversation_id: Optional[str] = None
    email_subject: Optional[str] = None
    email_sender: Optional[str] = None
    email_received_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class TaskInDBBase(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
    user_id: Optional[int] = None
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    is_read: bool = False
    
    class Config:
        from_attributes = True


class Task(TaskInDBBase):
    is_from_email: bool = False
    email_info: Optional[EmailInfo] = None


class TaskWithDetails(Task):
    # assignee: Optional["Agent"] = None
    # sent_from: "Agent"
    # team: Optional["Team"] = None
    # user: Optional["User"] = None
    # company: Optional["Company"] = None
    # comments: List["Comment"] = []
    # activities: List["Activity"] = []
    pass 