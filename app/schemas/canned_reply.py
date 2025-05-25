from typing import Optional, List
from pydantic import BaseModel, Field


class CannedReplyBase(BaseModel):
    """Base schema for CannedReply."""
    title: str = Field(..., description="The title/name of the canned reply", max_length=255)
    content: str = Field(..., description="The content/text of the canned reply")
    workspace_id: int = Field(..., description="The ID of the workspace this canned reply belongs to")
    is_enabled: bool = Field(True, description="Whether the canned reply is enabled")
    category: Optional[str] = Field(None, description="Category to organize canned replies", max_length=100)
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for easier searching and filtering")


class CannedReplyCreate(CannedReplyBase):
    """Schema for creating a CannedReply."""
    pass


class CannedReplyUpdate(BaseModel):
    """Schema for updating a CannedReply."""
    title: Optional[str] = Field(None, description="The title/name of the canned reply", max_length=255)
    content: Optional[str] = Field(None, description="The content/text of the canned reply")
    is_enabled: Optional[bool] = Field(None, description="Whether the canned reply is enabled")
    category: Optional[str] = Field(None, description="Category to organize canned replies", max_length=100)
    tags: Optional[List[str]] = Field(None, description="Tags for easier searching and filtering")


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
    categories: List[str] = Field(..., description="List of unique categories")
    tags: List[str] = Field(..., description="List of unique tags")