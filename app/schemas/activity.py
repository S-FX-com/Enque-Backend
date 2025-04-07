from typing import Optional
from pydantic import BaseModel
from datetime import datetime

class ActivityBase(BaseModel):
    user_id: Optional[int] = None
    task_id: Optional[int] = None
    action: str


class ActivityCreate(ActivityBase):
    pass


class ActivityInDBBase(ActivityBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class Activity(ActivityInDBBase):
    pass


class ActivityWithDetails(Activity):
    # user: Optional["Agent"] = None
    # task: Optional["Task"] = None
    pass 