from pydantic import BaseModel, validator
from datetime import datetime, timezone
from typing import Optional, List
from app.models.scheduled_comment import ScheduledCommentStatus


class ScheduledCommentBase(BaseModel):
    content: str
    scheduled_send_at: datetime
    is_private: bool = False
    other_destinaries: Optional[str] = None
    bcc_recipients: Optional[str] = None
    attachment_ids: Optional[List[int]] = None
    
    @validator('scheduled_send_at')
    def validate_future_date(cls, v):
        if v <= datetime.now(timezone.utc):
            raise ValueError('Scheduled send time must be in the future')
        return v
    
    @validator('content')
    def validate_content(cls, v):
        if not v or not v.strip():
            raise ValueError('Content cannot be empty')
        return v.strip()


class ScheduledCommentCreate(ScheduledCommentBase):
    """Schema for creating a scheduled comment"""
    pass


class ScheduledCommentUpdate(BaseModel):
    """Schema for updating a scheduled comment"""
    content: Optional[str] = None
    scheduled_send_at: Optional[datetime] = None
    is_private: Optional[bool] = None
    other_destinaries: Optional[str] = None
    bcc_recipients: Optional[str] = None
    attachment_ids: Optional[List[int]] = None
    
    @validator('scheduled_send_at')
    def validate_future_date(cls, v):
        if v is not None and v <= datetime.now(timezone.utc):
            raise ValueError('Scheduled send time must be in the future')
        return v
    
    @validator('content')
    def validate_content(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Content cannot be empty')
        return v.strip() if v else v


class ScheduledCommentResponse(BaseModel):
    """Schema for scheduled comment response"""
    id: int
    ticket_id: int
    agent_id: int
    workspace_id: int
    content: str
    scheduled_send_at: datetime
    is_private: bool
    other_destinaries: Optional[str]
    bcc_recipients: Optional[str]
    attachment_ids: Optional[List[int]]
    status: ScheduledCommentStatus
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime]
    error_message: Optional[str]
    retry_count: int
    
    class Config:
        from_attributes = True


class ScheduledCommentListResponse(BaseModel):
    """Schema for listing scheduled comments"""
    id: int
    ticket_id: int
    content: str
    scheduled_send_at: datetime
    status: ScheduledCommentStatus
    created_at: datetime
    is_private: bool
    
    class Config:
        from_attributes = True


class ScheduledCommentStats(BaseModel):
    """Schema for scheduled comment statistics"""
    total: int
    pending: int
    sent: int
    failed: int
    cancelled: int