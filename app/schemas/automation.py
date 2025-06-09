from typing import Optional, List
from pydantic import BaseModel, validator, Field
from datetime import datetime
from enum import Enum


class ConditionType(str, Enum):
    DESCRIPTION = "DESCRIPTION"
    NOTE = "NOTE"
    USER = "USER"
    AGENT = "AGENT"
    COMPANY = "COMPANY"
    PRIORITY = "PRIORITY"
    CATEGORY = "CATEGORY"


class ConditionOperator(str, Enum):
    EQL = "eql"
    NEQL = "neql"
    CON = "con"
    NCON = "ncon"


class ActionType(str, Enum):
    SET_AGENT = "SET_AGENT"
    SET_PRIORITY = "SET_PRIORITY"
    SET_STATUS = "SET_STATUS"
    SET_TEAM = "SET_TEAM"


# Condition schemas
class AutomationConditionBase(BaseModel):
    condition_type: ConditionType
    condition_operator: Optional[ConditionOperator] = ConditionOperator.EQL
    condition_value: Optional[str] = None


class AutomationConditionCreate(AutomationConditionBase):
    pass


class AutomationConditionUpdate(BaseModel):
    condition_type: Optional[ConditionType] = None
    condition_operator: Optional[ConditionOperator] = None
    condition_value: Optional[str] = None


class AutomationCondition(AutomationConditionBase):
    id: int
    automation_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Action schemas
class AutomationActionBase(BaseModel):
    action_type: ActionType
    action_value: Optional[str] = None


class AutomationActionCreate(AutomationActionBase):
    pass


class AutomationActionUpdate(BaseModel):
    action_type: Optional[ActionType] = None
    action_value: Optional[str] = None


class AutomationAction(AutomationActionBase):
    id: int
    automation_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Automation schemas
class AutomationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    workspace_id: int
    is_active: Optional[bool] = True


class AutomationCreate(AutomationBase):
    conditions: List[AutomationConditionCreate] = Field(..., min_length=1)
    actions: List[AutomationActionCreate] = Field(..., min_length=1)

    @validator("conditions")
    def validate_conditions(cls, v):
        if not v:
            raise ValueError("At least one condition is required")
        return v

    @validator("actions")
    def validate_actions(cls, v):
        if not v:
            raise ValueError("At least one action is required")
        return v


class AutomationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    conditions: Optional[List[AutomationConditionCreate]] = None
    actions: Optional[List[AutomationActionCreate]] = None


class AutomationInDBBase(AutomationBase):
    id: int
    workspace_id: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None

    class Config:
        from_attributes = True


class Automation(AutomationInDBBase):
    conditions: List[AutomationCondition] = []
    actions: List[AutomationAction] = []

    class Config:
        from_attributes = True


class AutomationSummary(BaseModel):
    total_automations: int
    active_automations: int
    inactive_automations: int 