from typing import Optional, List
from pydantic import BaseModel, EmailStr
from datetime import datetime

# User schemas
class UserBase(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    company_id: Optional[int] = None


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    company_id: Optional[int] = None


class UserInDBBase(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class User(UserInDBBase):
    pass


class UserWithDetails(User):
    # company: Optional["Company"] = None
    # tasks: List["Task"] = []
    pass


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