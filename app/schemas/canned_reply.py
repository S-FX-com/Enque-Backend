from typing import Optional, List
from pydantic import BaseModel, Field


class CannedReplyBase(BaseModel):
    """Base schema for CannedReply."""
    name: str = Field(..., description="The name of the canned reply", max_length=255)
    description: Optional[str] = Field(None, description="Optional description of the canned reply")
    content: str = Field(..., description="The content/text of the canned reply")
    workspace_id: int = Field(..., description="The ID of the workspace this canned reply belongs to")
    is_enabled: bool = Field(True, description="Whether the canned reply is enabled")


class CannedReplyCreate(CannedReplyBase):
    """Schema for creating a CannedReply."""
    pass


class CannedReplyUpdate(BaseModel):
    """Schema for updating a CannedReply."""
    name: Optional[str] = Field(None, description="The name of the canned reply", max_length=255)
    description: Optional[str] = Field(None, description="Optional description of the canned reply")
    content: Optional[str] = Field(None, description="The content/text of the canned reply")
    is_enabled: Optional[bool] = Field(None, description="Whether the canned reply is enabled")


class CannedReply(CannedReplyBase):
    """Schema for a complete CannedReply."""
    id: int = Field(..., description="The ID of the canned reply")
    
    class Config:
        from_attributes = True


class CannedReplyListResponse(BaseModel):
    """Schema for paginated canned reply list response."""
    items: List[CannedReply] = Field(..., description="List of canned replies")
    total: int = Field(..., description="Total number of canned replies")
    skip: int = Field(..., description="Number of items skipped")
    limit: int = Field(..., description="Maximum number of items returned")


class CannedReplyStats(BaseModel):
    """Schema for canned reply statistics."""
    total_count: int = Field(..., description="Total number of canned replies")
    enabled_count: int = Field(..., description="Number of enabled canned replies")