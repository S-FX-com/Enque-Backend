from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, validator
from datetime import datetime

class WorkflowConditionBase(BaseModel):
    field: str
    operator: str
    value: Union[str, int, float, bool]

class WorkflowCondition(WorkflowConditionBase):
    pass

class WorkflowActionBase(BaseModel):
    type: str
    config: Dict[str, Any] = {}

class WorkflowAction(WorkflowActionBase):
    pass

class MessageAnalysisRule(BaseModel):
    """Rules for analyzing message content"""
    keywords: List[str] = []
    exclude_keywords: List[str] = []
    sentiment_threshold: Optional[float] = None  # -1 to 1 scale
    urgency_keywords: List[str] = []
    language: Optional[str] = None
    min_confidence: float = 0.7

class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_enabled: bool = True
    trigger: str
    message_analysis_rules: Optional[MessageAnalysisRule] = None
    conditions: List[WorkflowCondition] = []
    actions: List[WorkflowAction] = []

class WorkflowCreate(WorkflowBase):
    @validator('name')
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()

    @validator('trigger')
    def trigger_must_be_valid(cls, v):
        # Static valid triggers
        static_triggers = [
            # Content-based triggers
            'message.contains_keywords',
            'message.sentiment_negative',
            'message.sentiment_positive',
            'message.urgency_high',
            'message.urgency_medium',
            'message.language_detected',
            'message.category_support',
            'message.category_billing',
            'message.category_technical',
            'message.category_complaint',
            'message.category_praise',
            # Traditional event triggers (legacy support)
            'ticket.created',
            'ticket.updated',
            'comment.added',
            'customer.replied',
            'agent.replied'
        ]
        
        # Check static triggers first
        if v in static_triggers:
            return v
        
        # Check dynamic trigger patterns
        if v.startswith('message.category_custom_'):
            # Dynamic workspace category triggers
            return v
        
        # If none match, raise error
        raise ValueError(f'Invalid trigger. Must be one of the predefined triggers or a valid dynamic pattern like "message.category_custom_*"')
        return v

class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    trigger: Optional[str] = None
    message_analysis_rules: Optional[MessageAnalysisRule] = None
    conditions: Optional[List[WorkflowCondition]] = None
    actions: Optional[List[WorkflowAction]] = None

    @validator('name')
    def name_must_not_be_empty(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('Name cannot be empty')
        return v.strip() if v else v

    @validator('trigger')
    def trigger_must_be_valid(cls, v):
        if v is not None:
            # Static valid triggers
            static_triggers = [
                # Content-based triggers
                'message.contains_keywords',
                'message.sentiment_negative',
                'message.sentiment_positive',
                'message.urgency_high',
                'message.urgency_medium',
                'message.language_detected',
                'message.category_support',
                'message.category_billing',
                'message.category_technical',
                'message.category_complaint',
                'message.category_praise',
                # Traditional event triggers (legacy support)
                'ticket.created',
                'ticket.updated',
                'comment.added',
                'customer.replied',
                'agent.replied'
            ]
            
            # Check static triggers first
            if v in static_triggers:
                return v
            
            # Check dynamic trigger patterns
            if v.startswith('message.category_custom_'):
                # Dynamic workspace category triggers
                return v
            
            # If none match, raise error
            raise ValueError(f'Invalid trigger. Must be one of the predefined triggers or a valid dynamic pattern like "message.category_custom_*"')
        return v

class WorkflowInDBBase(WorkflowBase):
    id: int
    workspace_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class Workflow(WorkflowInDBBase):
    pass

class WorkflowInDB(WorkflowInDBBase):
    pass

# Response schemas for triggers and actions
class WorkflowTriggerOption(BaseModel):
    value: str
    label: str
    description: str

class WorkflowActionOption(BaseModel):
    id: str
    name: str
    description: str
    config_schema: Dict[str, Any] = {}

# Bulk operations
class WorkflowToggle(BaseModel):
    is_enabled: bool

# Message analysis result
class MessageAnalysisResult(BaseModel):
    sentiment: float  # -1 to 1
    urgency_level: str  # low, medium, high
    keywords_found: List[str]
    categories: List[str]
    language: str
    confidence: float 