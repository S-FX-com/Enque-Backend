from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime
from app.schemas.workspace import WorkspaceResponse

class CompanyBase(BaseModel):
    name: str
    description: Optional[str] = None
    logo_url: Optional[HttpUrl] = None
    email_domain: str


class CompanyCreate(CompanyBase):
    workspace_id: int
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[HttpUrl] = None
    email_domain: Optional[str] = None


class CompanyResponse(CompanyBase):
    id: int
    workspace: WorkspaceResponse
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
