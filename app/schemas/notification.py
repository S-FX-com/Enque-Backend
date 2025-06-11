from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from pydantic import BaseModel, Field


class NotificationTemplateBase(BaseModel):
    """Base schema for notification templates."""
    type: str
    name: str
    subject: str
    template: str
    is_enabled: bool = True


class NotificationTemplateCreate(NotificationTemplateBase):
    """Schema for creating a notification template."""
    workspace_id: int


class NotificationTemplateUpdate(BaseModel):
    """Schema for updating a notification template."""
    name: Optional[str] = None
    subject: Optional[str] = None
    template: Optional[str] = None
    is_enabled: Optional[bool] = None


class NotificationTemplateInDB(NotificationTemplateBase):
    """Schema for notification template from DB."""
    id: int
    workspace_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class NotificationSettingBase(BaseModel):
    """Base schema for notification settings."""
    category: str  # 'agents', 'users', etc.
    type: str  # 'new_ticket_created', 'ticket_resolved', etc.
    is_enabled: bool = True
    channels: List[str]  # ["email", "teams", etc.]
    template_id: Optional[int] = None


class NotificationSettingCreate(NotificationSettingBase):
    """Schema for creating a notification setting."""
    workspace_id: int


class NotificationSettingUpdate(BaseModel):
    """Schema for updating a notification setting."""
    is_enabled: Optional[bool] = None
    channels: Optional[List[str]] = None
    template_id: Optional[int] = None


class NotificationSettingInDB(NotificationSettingBase):
    """Schema for notification setting from DB."""
    id: int
    workspace_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class NotificationSettingWithTemplate(NotificationSettingInDB):
    """Schema for notification setting with template."""
    template: Optional[NotificationTemplateInDB] = None


class NotificationChannelConfig(BaseModel):
    """Configuration for a notification channel."""
    is_connected: bool = False
    is_enabled: bool = False
    id: Optional[int] = None
    connection_data: Dict[str, Any] = {}


class NotificationTypeConfig(BaseModel):
    """Configuration for a notification type."""
    is_enabled: bool = False
    id: Optional[int] = None
    template: Optional[str] = None


class AgentEmailNotificationsConfig(BaseModel):
    """Configuration for agent email notifications."""
    new_ticket_created: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)
    new_response: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)
    ticket_assigned: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)


class AgentEnquePopupConfig(BaseModel):
    """Configuration for agent Enque popup notifications."""
    new_ticket_created: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)
    new_response: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)
    ticket_assigned: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)


class AgentTeamsConfig(BaseModel):
    """Configuration for agent Teams notifications."""
    is_connected: bool = False
    is_enabled: bool = False
    id: Optional[int] = None


class AgentNotificationsConfig(BaseModel):
    """Configuration for agent notifications."""
    email: AgentEmailNotificationsConfig = Field(default_factory=AgentEmailNotificationsConfig)
    enque_popup: AgentEnquePopupConfig = Field(default_factory=AgentEnquePopupConfig)
    teams: AgentTeamsConfig = Field(default_factory=AgentTeamsConfig)


class UserEmailNotificationsConfig(BaseModel):
    """Configuration for user email notifications."""
    new_ticket_created: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)
    ticket_resolved: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)
    new_agent_response: NotificationTypeConfig = Field(default_factory=NotificationTypeConfig)


class UserNotificationsConfig(BaseModel):
    """Configuration for user notifications."""
    email: UserEmailNotificationsConfig = Field(default_factory=UserEmailNotificationsConfig)


class NotificationSettingsResponse(BaseModel):
    """Response schema for notification settings."""
    agents: AgentNotificationsConfig = Field(default_factory=AgentNotificationsConfig)
    users: UserNotificationsConfig = Field(default_factory=UserNotificationsConfig)


class NotificationToggleRequest(BaseModel):
    """Request schema for toggling a notification setting."""
    is_enabled: bool


class NotificationTeamsConnectRequest(BaseModel):
    """Request schema for connecting Teams notification channel."""
    webhook_url: str


class NotificationTemplateCreateRequest(BaseModel):
    """Request schema for creating a notification template."""
    type: str
    name: str
    subject: str
    template: str


class NotificationTemplateUpdateRequest(BaseModel):
    """Request schema for updating a notification template."""
    content: str 

    