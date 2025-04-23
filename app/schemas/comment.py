from typing import Optional, ForwardRef
from pydantic import BaseModel, Field
from datetime import datetime
from app.schemas.agent import Agent as AgentSchema

class CommentBase(BaseModel):
    content: str
    is_private: bool = False

class CommentCreate(CommentBase):
    ticket_id: int
    agent_id: int
    workspace_id: int

class CommentUpdate(BaseModel):
    content: Optional[str] = None
    is_private: Optional[bool] = None

class CommentInDBBase(CommentBase):
    id: int
    ticket_id: int
    agent_id: Optional[int] = None
    workspace_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class Comment(CommentInDBBase):
    agent: Optional[AgentSchema] = None

    class Config:
        from_attributes = True
