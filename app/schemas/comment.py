from typing import Optional
from pydantic import BaseModel
from datetime import datetime

class CommentBase(BaseModel):
    task_id: int
    user_id: int
    content: str


class CommentCreate(CommentBase):
    pass


class CommentUpdate(BaseModel):
    content: Optional[str] = None


class CommentInDBBase(CommentBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class Comment(CommentInDBBase):
    pass


class CommentWithDetails(Comment):
    # task: "Task"
    # user: "Agent"
    pass 