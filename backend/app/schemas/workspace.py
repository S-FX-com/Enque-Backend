from typing import Optional
from pydantic import BaseModel, Field, validator
import re


# Workspace schemas
class WorkspaceBase(BaseModel):
    """Base schema for Workspace."""
    name: str = Field(..., description="Workspace name")
    subdomain: str = Field(..., description="Unique subdomain to access the workspace")
    email_domain: str = Field(..., description="Email domain associated with this workspace")
    description: Optional[str] = Field(None, description="Workspace description")
    logo_url: Optional[str] = Field(None, description="URL for the workspace logo")
    
    @validator("subdomain")
    def validate_subdomain(cls, v):
        """Validate that subdomain only contains alphanumeric characters and hyphens."""
        if not re.match(r"^[a-z0-9\-]+$", v):
            raise ValueError("Subdomain can only contain lowercase letters, numbers, and hyphens")
        return v


class WorkspaceCreate(WorkspaceBase):
    """Schema for creating a new Workspace."""
    pass


class WorkspaceUpdate(BaseModel):
    """Schema for updating a Workspace."""
    name: Optional[str] = None
    subdomain: Optional[str] = None
    description: Optional[str] = None
    email_domain: Optional[str] = None
    logo_url: Optional[str] = None
    
    @validator("subdomain")
    def validate_subdomain(cls, v):
        """Validate that subdomain only contains alphanumeric characters and hyphens."""
        if v is not None and not re.match(r"^[a-z0-9\-]+$", v):
            raise ValueError("Subdomain can only contain lowercase letters, numbers, and hyphens")
        return v


class Workspace(WorkspaceBase):
    """Schema for a Workspace response."""
    id: int
    
    class Config:
        from_attributes = True 