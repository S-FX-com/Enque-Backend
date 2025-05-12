# backend/app/schemas/agent.py
from typing import Optional, List, ForwardRef
from pydantic import BaseModel, EmailStr, validator
from datetime import datetime

# Forward references
WorkspaceRef = ForwardRef("Workspace")

# Base schema with common attributes
class AgentBase(BaseModel):
    name: str
    email: EmailStr
    role: str = "agent"
    is_active: bool = True
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    email_signature: Optional[str] = None # Add email_signature

    @validator("role")
    def validate_role(cls, v):
        allowed_roles = ["admin", "agent", "manager"] # Add manager
        # Normalizar el rol si viene en mayúsculas
        if v == "Agent":
            return "agent"
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of {allowed_roles}")
        return v


# Schema for an admin to invite a new agent
class AgentInviteCreate(BaseModel):
    name: str
    email: EmailStr
    role: str = "agent" # Default role, can be overridden
    workspace_id: int # Need to know which workspace to invite them to

    @validator("role")
    def validate_role(cls, v):
        allowed_roles = ["admin", "agent", "manager"]
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of {allowed_roles}")
        return v

# Schema for creating a new agent in the database (internal use or direct creation)
class AgentCreate(AgentBase):
    password: Optional[str] = None # Password is not set during invitation
    workspace_id: int
    is_active: bool = False # Invited agents are not active until they accept
    invitation_token: Optional[str] = None
    invitation_token_expires_at: Optional[datetime] = None
    password_reset_token: Optional[str] = None
    password_reset_token_expires_at: Optional[datetime] = None


# Schema for updating an agent
class AgentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    email_signature: Optional[str] = None # Add email_signature

    @validator("role")
    def validate_role(cls, v):
        if v is not None:
            allowed_roles = ["admin", "agent", "manager"] # Add manager
            # Normalizar el rol si viene en mayúsculas
            if v == "Agent":
                return "agent"
            if v not in allowed_roles:
                raise ValueError(f"Role must be one of {allowed_roles}")
        return v


# Schema for agent in DB
class AgentInDBBase(AgentBase):
    id: int
    workspace_id: int
    created_at: Optional[datetime] = None # Make optional
    updated_at: Optional[datetime] = None # Make optional
    # Invitation fields are in DB but not typically exposed unless needed
    invitation_token: Optional[str] = None
    invitation_token_expires_at: Optional[datetime] = None
    password_reset_token: Optional[str] = None
    password_reset_token_expires_at: Optional[datetime] = None


    class Config:
        from_attributes = True


# Schema for returning agent details (typically excludes sensitive/internal fields like tokens)
class Agent(AgentInDBBase):
    # Explicitly exclude invitation token fields from the default Agent response model
    # If they are needed in some specific response, a different schema can be used.
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "name": "John Doe",
                "email": "john.doe@example.com",
                "role": "agent",
                "is_active": True,
                "job_title": "Support Specialist",
                "phone_number": "123-456-7890",
                "email_signature": "Regards, John",
                "workspace_id": 1,
                "created_at": "2023-01-01T12:00:00Z",
                "updated_at": "2023-01-01T12:00:00Z",
            }
        }
    }
    # Removed problematic Pydantic V1 style validator

# Schema for agent accepting invitation
class AgentAcceptInvitation(BaseModel):
    token: str
    password: str

# Schema for requesting a password reset
class AgentPasswordResetRequest(BaseModel):
    email: EmailStr

# Schema for resetting password
class AgentResetPassword(BaseModel):
    token: str
    new_password: str


# Schema for returning agent with all details including relationships
class AgentWithDetails(Agent):
    workspace: WorkspaceRef

    class Config:
        from_attributes = True


# Update forward references
from app.schemas.workspace import Workspace

AgentWithDetails.update_forward_refs()
