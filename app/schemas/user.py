from typing import Optional, List, ForwardRef
from pydantic import BaseModel, EmailStr
from datetime import datetime

# Forward references
CompanyRef = ForwardRef("Company")
WorkspaceRef = ForwardRef("Workspace")

# User schemas
class UserBase(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None


class UserCreate(UserBase):
    company_id: Optional[int] = None
    workspace_id: int


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class UserInDBBase(UserBase):
    id: int
    company_id: Optional[int] = None
    # Allow workspace_id to be None to match potential DB values
    workspace_id: Optional[int] = None 
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class User(UserInDBBase):
    pass


class UserWithDetails(User):
    company: Optional[CompanyRef] = None
    workspace: WorkspaceRef
    
    class Config:
        from_attributes = True


# UnassignedUser schemas
class UnassignedUserBase(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None


class UnassignedUserCreate(UnassignedUserBase):
    pass


class UnassignedUserInDBBase(UnassignedUserBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class UnassignedUser(UnassignedUserInDBBase):
    pass


# Update forward references
from app.schemas.company import Company
from app.schemas.workspace import Workspace

UserWithDetails.update_forward_refs()
