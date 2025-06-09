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
    primary_contact_id: Optional[int] = None # Added
    account_manager_id: Optional[int] = None # Added


class CompanyCreate(CompanyBase):
    # workspace_id is now handled by the endpoint using context
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    email_domain: Optional[str] = None
    logo_url: Optional[str] = None
    primary_contact_id: Optional[int] = None # Added
    account_manager_id: Optional[int] = None # Added


class CompanyInDBBase(CompanyBase):
    id: int
    workspace_id: int
    # primary_contact_id and account_manager_id are already included via CompanyBase
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
