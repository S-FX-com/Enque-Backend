from typing import Optional, ForwardRef, Literal
from pydantic import BaseModel
from datetime import datetime

# Forward references
WorkspaceRef = ForwardRef("Workspace")
AgentRef = ForwardRef("Agent")

# Activity source types
ActivitySourceType = Literal["Workspace", "Ticket", "Team", "Company", "User"]

class ActivityBase(BaseModel):
    action: str
    agent_id: Optional[int] = None
    source_type: ActivitySourceType
    source_id: int
    workspace_id: int


class ActivityCreate(ActivityBase):
    pass


class ActivityUpdate(ActivityBase):
    pass


class ActivityInDBBase(ActivityBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class Activity(ActivityInDBBase):
    pass


class ActivityWithDetails(Activity):
    agent: Optional[AgentRef] = None
    workspace: WorkspaceRef
    
    class Config:
        from_attributes = True


# Update forward references
from app.schemas.workspace import Workspace
from app.schemas.agent import Agent

ActivityWithDetails.update_forward_refs() 