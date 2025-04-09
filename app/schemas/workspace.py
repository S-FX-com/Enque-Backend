from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime


class WorkspaceBase(BaseModel):
    name: str
    local_subdomain: str
    email_domain: str
    logo_url: Optional[HttpUrl] = None


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    local_subdomain: Optional[str] = None
    email_domain: Optional[str] = None
    logo_url: Optional[HttpUrl] = None


class WorkspaceResponse(WorkspaceBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
