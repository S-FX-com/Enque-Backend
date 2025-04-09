from typing import Optional, List, ForwardRef
from pydantic import BaseModel
from datetime import datetime

# Forward references
WorkspaceRef = ForwardRef("Workspace")

class CompanyBase(BaseModel):
    name: str
    description: Optional[str] = None
    email_domain: Optional[str] = None
    logo_url: Optional[str] = None


class CompanyCreate(CompanyBase):
    workspace_id: int


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    email_domain: Optional[str] = None
    logo_url: Optional[str] = None


class CompanyInDBBase(CompanyBase):
    id: int
    workspace_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class Company(CompanyInDBBase):
    pass


class CompanyWithDetails(Company):
    workspace: WorkspaceRef
    
    class Config:
        from_attributes = True


# Update forward references
from app.schemas.workspace import Workspace

CompanyWithDetails.update_forward_refs() 