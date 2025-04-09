from typing import Optional, ForwardRef
from pydantic import BaseModel
from datetime import datetime

# Forward references
WorkspaceRef = ForwardRef("Workspace")
AgentRef = ForwardRef("Agent")
TicketRef = ForwardRef("Ticket")

class CommentBase(BaseModel):
    content: str


class CommentCreate(CommentBase):
    ticket_id: int
    agent_id: int
    workspace_id: int


class CommentUpdate(BaseModel):
    content: Optional[str] = None


class CommentInDBBase(CommentBase):
    id: int
    ticket_id: int
    agent_id: int
    workspace_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class Comment(CommentInDBBase):
    pass


class CommentWithDetails(Comment):
    ticket: TicketRef
    agent: AgentRef
    workspace: WorkspaceRef
    
    class Config:
        from_attributes = True


# Update forward references
from app.schemas.workspace import Workspace
from app.schemas.agent import Agent
from app.schemas.task import Task as Ticket

CommentWithDetails.update_forward_refs() 