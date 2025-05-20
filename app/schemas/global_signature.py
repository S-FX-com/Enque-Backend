from typing import Optional
from pydantic import BaseModel, Field


class GlobalSignatureBase(BaseModel):
    """Base schema for GlobalSignature."""
    content: str = Field(..., description="The HTML content of the global email signature")
    workspace_id: int = Field(..., description="The ID of the workspace this signature belongs to")
    is_enabled: bool = Field(True, description="Whether the global signature is enabled")


class GlobalSignatureCreate(GlobalSignatureBase):
    """Schema for creating a GlobalSignature."""
    pass


class GlobalSignatureUpdate(BaseModel):
    """Schema for updating a GlobalSignature."""
    content: Optional[str] = Field(None, description="The HTML content of the global email signature")
    is_enabled: Optional[bool] = Field(None, description="Whether the global signature is enabled")


class GlobalSignature(GlobalSignatureBase):
    """Schema for a complete GlobalSignature."""
    id: int = Field(..., description="The ID of the global signature")

    class Config:
        from_attributes = True 