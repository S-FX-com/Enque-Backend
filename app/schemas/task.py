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
CategoryRef = ForwardRef("Category") # Add CategoryRef
# Forward reference for the new body schema
TicketBodyRef = ForwardRef("TicketBodySchema")

class TaskStatus(str, PyEnum):
    UNREAD = "Unread"
    OPEN = "Open"
    WITH_USER = "With User" # Added
    IN_PROGRESS = "In Progress" # Added
    CLOSED = "Closed"
    RESOLVED = "Resolved" # Added Resolved


class TaskPriority(str, PyEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical" # Added Critical


class TaskBase(BaseModel):
    title: str
    # Description is now optional, not primarily for email body
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
    category_id: Optional[int] = None # Add category_id
    
    @validator("status")
    def validate_status(cls, v):
        # Use the Enum members for validation
        if v not in TaskStatus.__members__.values():
             raise ValueError(f"Status must be one of {list(TaskStatus.__members__.values())}")
        return v
    
    @validator("priority")
    def validate_priority(cls, v):
        # Use the Enum members for validation
        if v not in TaskPriority.__members__.values():
             raise ValueError(f"Priority must be one of {list(TaskPriority.__members__.values())}")
        return v


# TicketCreate needs description for manually created tickets
class TicketCreate(BaseModel):
    title: str
    # Add description back, make it optional
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.UNREAD
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    due_date: Optional[datetime] = None
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    user_id: int # User who originally sent the email/request
    company_id: Optional[int] = None
    workspace_id: int
    category_id: Optional[int] = None # Add category_id


# TicketUpdate can still update the manual description
class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None # Allow updating manual description
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[int] = None # Add assignee_id
    company_id: Optional[int] = None
    # user_id: int # Removing potentially incorrect required user_id on update
    # sent_from_id: Optional[int] = None # Assuming these are not typically updated here
    # sent_to_id: Optional[int] = None
    due_date: Optional[datetime] = None
    team_id: Optional[int] = None
    # company_id: Optional[int] = None # Duplicate removed
    # user_id: Optional[int] = None # Duplicate removed, and likely shouldn't be updated here
    # sent_from_id: Optional[int] = None # Duplicate removed
    # sent_to_id: Optional[int] = None # Duplicate removed
    category_id: Optional[int] = None # Add category_id
    
    @validator("status")
    def validate_status(cls, v):
        if v is not None:
            # Use the Enum members for validation
            if v not in TaskStatus.__members__.values():
                 raise ValueError(f"Status must be one of {list(TaskStatus.__members__.values())}")
        return v
    
    @validator("priority")
    def validate_priority(cls, v):
        if v is not None:
            # Use the Enum members for validation
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


# Base schema for reading from DB, description is optional
class TicketInDBBase(BaseModel): 
    id: int
    title: str
    description: Optional[str] = None # Manual description
    status: TaskStatus
    priority: TaskPriority
    assignee_id: Optional[int] = None
    # team_id is defined once below
    due_date: Optional[datetime] = None
    # sent_from_id is defined once below
    # sent_to_id is defined once below
    user_id: Optional[int] = None # Changed to Optional
    # company_id is defined once below
    workspace_id: int # workspace_id should probably be Optional[int] = None if it can be None
    team_id: Optional[int] = None
    company_id: Optional[int] = None
    # user_id: int # Duplicate removed
    sent_from_id: Optional[int] = None
    sent_to_id: Optional[int] = None
    category_id: Optional[int] = None # Add category_id
    created_at: datetime
    updated_at: datetime
    last_update: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# Basic Ticket schema for responses
class Ticket(TicketInDBBase): 
    is_from_email: bool = False
    email_info: Optional[EmailInfo] = None


# Schema for the separate ticket body content
class TicketBodySchema(BaseModel):
    email_body: Optional[str] = None
    
    class Config:
        from_attributes = True


# Detailed Ticket schema including relationships AND the body
class TicketWithDetails(Ticket): 
    workspace: WorkspaceRef
    team: Optional[TeamRef] = None
    company: Optional[CompanyRef] = None
    user: Optional[UserRef] = None # Make user optional
    sent_from: Optional[AgentRef] = None # Agent who created/processed
    sent_to: Optional[AgentRef] = None
    category: Optional[CategoryRef] = None # Add category object
    body: Optional[TicketBodyRef] = None # Include the related body object
    
    class Config:
        from_attributes = True


# Update forward references
from app.schemas.workspace import Workspace
from app.schemas.agent import Agent
from app.schemas.team import Team
from app.schemas.user import User
from app.schemas.company import Company
from app.schemas.category import Category # Import Category schema

# Update refs for all models in this module that use ForwardRefs
# Call without arguments for Pydantic v2 compatibility
TicketWithDetails.update_forward_refs() 
TicketBodySchema.update_forward_refs() # Keep this for consistency

# Alias Task to Ticket for backward compatibility (adjust if needed)
Task = Ticket 
# TaskBase needs re-aliasing if its definition changed significantly
# TaskCreate needs re-aliasing as its definition changed
# TaskUpdate needs re-aliasing
# TaskInDBBase needs re-aliasing
TaskWithDetails = TicketWithDetails
