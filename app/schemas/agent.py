
from typing import Optional, List, ForwardRef
from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
WorkspaceRef = ForwardRef("Workspace")

class AgentBase(BaseModel):
    name: str
    email: EmailStr
    role: str = "agent"
    is_active: bool = True
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    email_signature: Optional[str] = None 

    @validator("role")
    def validate_role(cls, v):
        allowed_roles = ["admin", "agent", "manager"] 
        if v == "Agent":
            return "agent"
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of {allowed_roles}")
        return v
class AgentInviteCreate(BaseModel):
    name: str
    email: EmailStr
    role: str = "agent" 
    workspace_id: int 

    @validator("role")
    def validate_role(cls, v):
        allowed_roles = ["admin", "agent", "manager"]
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of {allowed_roles}")
        return v

class AgentCreate(AgentBase):
    password: Optional[str] = None 
    workspace_id: int
    is_active: bool = False 
    invitation_token: Optional[str] = None
    invitation_token_expires_at: Optional[datetime] = None
    password_reset_token: Optional[str] = None
    password_reset_token_expires_at: Optional[datetime] = None

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    email_signature: Optional[str] = None 

    @validator("role")
    def validate_role(cls, v):
        if v is not None:
            allowed_roles = ["admin", "agent", "manager"] 
            if v == "Agent":
                return "agent"
            if v not in allowed_roles:
                raise ValueError(f"Role must be one of {allowed_roles}")
        return v

class AgentInDBBase(AgentBase):
    id: int
    workspace_id: int
    created_at: Optional[datetime] = None 
    updated_at: Optional[datetime] = None 
    invitation_token: Optional[str] = None
    invitation_token_expires_at: Optional[datetime] = None
    password_reset_token: Optional[str] = None
    password_reset_token_expires_at: Optional[datetime] = None
    class Config:
        from_attributes = True
class Agent(AgentInDBBase):

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

class AgentAcceptInvitation(BaseModel):
    token: str
    password: str
class AgentPasswordResetRequest(BaseModel):
    email: EmailStr
class AgentResetPassword(BaseModel):
    token: str
    new_password: str
class AgentWithDetails(Agent):
    workspace: WorkspaceRef

    class Config:
        from_attributes = True
from app.schemas.workspace import Workspace

AgentWithDetails.update_forward_refs()
