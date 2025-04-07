from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

class CompanyBase(BaseModel):
    name: str
    email_domain: Optional[str] = None
    logo_url: Optional[str] = None


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    email_domain: Optional[str] = None
    logo_url: Optional[str] = None


class CompanyInDBBase(CompanyBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class Company(CompanyInDBBase):
    pass


class CompanyWithDetails(Company):
    # users: List["User"] = []
    # tasks: List["Task"] = []
    pass 