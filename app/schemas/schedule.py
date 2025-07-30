from typing import Optional, List, ForwardRef, Dict, Any
from pydantic import BaseModel, validator
from datetime import datetime
from enum import Enum as PyEnum

class ScheduleStatus(str, PyEnum):
    SENT = "Sent"
    PENDING = "Pending"
    FAIL = "Fail"

class ScheduleBase(BaseModel):
    created_by_agent_id:Optional[int]
    comment_id: Optional[int]
    created_at:datetime
    updated_at:datetime
    scheduled_for:datetime
    status:ScheduleStatus
