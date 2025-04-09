from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.schemas.agent import AgentResponse
from app.schemas.ticket import TicketResponse
from app.schemas.workspace import WorkspaceResponse

class CommentBase(BaseModel):
    content: str


class CommentCreate(CommentBase):
    agent_id: int
    ticket_id: int
    workspace_id: int
    pass


class CommentUpdate(BaseModel):
    content: Optional[str] = None


class CommentResponse(CommentBase):
    id: int
    agent: AgentResponse
    ticket: TicketResponse
    workspace: WorkspaceResponse
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True