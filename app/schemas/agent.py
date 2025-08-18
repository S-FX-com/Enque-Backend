from typing import Optional, List, ForwardRef
from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
import re
WorkspaceRef = ForwardRef("Workspace")

class AgentBase(BaseModel):
    name: str
    email: EmailStr
    role: str = "agent"
    auth_method: str = "password"
    is_active: bool = True
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    email_signature: Optional[str] = None
    avatar_url: Optional[str] = None
    microsoft_id: Optional[str] = None
    microsoft_email: Optional[str] = None
    microsoft_tenant_id: Optional[str] = None
    microsoft_profile_data: Optional[str] = None

    @validator("role")
    def validate_role(cls, v):
        allowed_roles = ["admin", "agent", "manager"]
        if v == "Agent":
            return "agent"
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of {allowed_roles}")
        return v

    @validator("auth_method")
    def validate_auth_method(cls, v):
        allowed_auth_methods = ["password", "microsoft", "both"]
        if v not in allowed_auth_methods:
            raise ValueError(f"Auth method must be one of {allowed_auth_methods}")
        return v

class AgentInviteCreate(BaseModel):
    name: str
    email: EmailStr
    role: str = "agent"
    workspace_id: int
    job_title: Optional[str] = None

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
    auth_method: Optional[str] = None
    is_active: Optional[bool] = None
    job_title: Optional[str] = None
    phone_number: Optional[str] = None
    email_signature: Optional[str] = None
    avatar_url: Optional[str] = None  # URL del avatar del agente
    microsoft_id: Optional[str] = None
    microsoft_email: Optional[str] = None
    microsoft_tenant_id: Optional[str] = None
    microsoft_profile_data: Optional[str] = None

    @validator("role")
    def validate_role(cls, v):
        if v is not None:
            allowed_roles = ["admin", "agent", "manager"]
            if v == "Agent":
                return "agent"
            if v not in allowed_roles:
                raise ValueError(f"Role must be one of {allowed_roles}")
        return v

    @validator("auth_method")
    def validate_auth_method(cls, v):
        if v is not None:
            allowed_auth_methods = ["password", "microsoft", "both"]
            if v not in allowed_auth_methods:
                raise ValueError(f"Auth method must be one of {allowed_auth_methods}")
        return v

    @validator("password")
    def validate_password(cls, v):
        if v is not None:
            return cls._validate_password_strength(v)
        return v

    @staticmethod
    def _validate_password_strength(password: str) -> str:
        """
        Validates that the password meets security requirements
        """
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        if len(password) > 128:
            raise ValueError("Password cannot be more than 128 characters long")

        if not re.search(r"[a-z]", password):
            raise ValueError("Password must contain at least one lowercase letter")

        if not re.search(r"[A-Z]", password):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"\d", password):
            raise ValueError("Password must contain at least one number")

        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?~`]", password):
            raise ValueError("Password must contain at least one special character (!@#$%^&*()_+-=[]{}|;':\"\\,.<>?/~`)")

        # Check that it's not a common password
        common_passwords = [
            "password", "123456", "password123", "admin", "qwerty",
            "letmein", "welcome", "monkey", "dragon", "master",
            "hello", "freedom", "whatever", "qazwsx", "trustno1"
        ]

        if password.lower() in common_passwords:
            raise ValueError("Password cannot be a common password")

        return password

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
                "avatar_url": "https://example.com/avatar.jpg",
                "workspace_id": 1,
                "created_at": "2023-01-01T12:00:00Z",
                "updated_at": "2023-01-01T12:00:00Z",
            }
        }
    }

class AgentAcceptInvitation(BaseModel):
    token: str
    password: str

    @validator("password")
    def validate_password(cls, v):
        return AgentUpdate._validate_password_strength(v)

class AgentPasswordResetRequest(BaseModel):
    email: EmailStr

class AgentResetPassword(BaseModel):
    token: str
    new_password: str

    @validator("new_password")
    def validate_new_password(cls, v):
        return AgentUpdate._validate_password_strength(v)

# Esquemas para autenticación de Microsoft
class AgentMicrosoftLinkRequest(BaseModel):
    microsoft_id: str
    microsoft_email: str
    microsoft_tenant_id: str
    microsoft_profile_data: Optional[str] = None

class AgentMicrosoftLogin(BaseModel):
    microsoft_id: str
    microsoft_email: str
    microsoft_tenant_id: str
    microsoft_profile_data: Optional[str] = None
    access_token: str
    expires_in: int
    workspace_id: Optional[int] = None

class AgentWithDetails(Agent):
    workspace: WorkspaceRef

    class Config:
        from_attributes = True
from app.schemas.workspace import Workspace

AgentWithDetails.update_forward_refs()
