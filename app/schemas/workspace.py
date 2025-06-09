from typing import Optional
from pydantic import BaseModel, Field, validator
from datetime import datetime
import re


# Workspace schemas
class WorkspaceBase(BaseModel):
    """Base schema for Workspace."""
    subdomain: str = Field(..., description="Unique subdomain to access the workspace")
    
    @validator("subdomain")
    def validate_subdomain(cls, v):
        """Validate that subdomain only contains alphanumeric characters and hyphens."""
        if not re.match(r"^[a-zA-Z0-9\-]+$", v):
            raise ValueError("Subdomain can only contain letters, numbers, and hyphens")
        return v


class WorkspaceCreate(WorkspaceBase):
    """Schema for creating a new Workspace."""
    pass


class WorkspaceUpdate(BaseModel):
    """Schema for updating a Workspace."""
    subdomain: Optional[str] = None
    
    @validator("subdomain")
    def validate_subdomain(cls, v):
        """Validate that subdomain only contains alphanumeric characters and hyphens."""
        if v is not None and not re.match(r"^[a-zA-Z0-9\-]+$", v):
            raise ValueError("Subdomain can only contain letters, numbers, and hyphens")
        return v


class Workspace(WorkspaceBase):
    """Schema for a Workspace response."""
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Schema para el setup inicial
class WorkspaceSetupCreate(BaseModel):
    """Schema for workspace setup with first admin."""
    subdomain: str = Field(..., description="Unique subdomain for the workspace")
    admin_name: str = Field(..., description="Name of the first admin user")
    admin_email: str = Field(..., description="Email of the first admin user")
    admin_password: str = Field(..., min_length=8, description="Password for the first admin user")
    
    @validator("subdomain")
    def validate_subdomain(cls, v):
        """Validate that subdomain only contains alphanumeric characters and hyphens."""
        if not re.match(r"^[a-zA-Z0-9\-]+$", v):
            raise ValueError("Subdomain can only contain letters, numbers, and hyphens")
        return v


class WorkspaceSetupResponse(BaseModel):
    """Response for workspace setup."""
    workspace: Workspace
    admin: dict  # AgentSchema se importará más tarde para evitar dependencias circulares
    access_token: str
    token_type: str = "bearer" 