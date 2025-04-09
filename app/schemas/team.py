from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime
from app.schemas.workspace import WorkspaceResponse


class TeamBase(BaseModel):
    name: str
    description: Optional[str] = None
    logo_url: Optional[HttpUrl] = None


class TeamCreate(TeamBase):
    workspace_id: Optional[int] = None
    pass


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[HttpUrl] = None


class TeamResponse(TeamBase):
    id: int
    workspace: Optional[WorkspaceResponse] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
