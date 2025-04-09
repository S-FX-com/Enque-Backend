from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.schemas.workspace import WorkspaceResponse
from app.schemas.company import CompanyResponse

class UserBase(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None


class UserCreate(UserBase):
    company_id: Optional[int] = None
    workspace_id: int
    pass


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class UserResponse(UserBase):
    id: int
    company: Optional[CompanyResponse] = None
    workspace: WorkspaceResponse
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True