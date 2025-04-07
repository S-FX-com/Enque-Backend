from pydantic import BaseModel, Field, validator, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime

# Microsoft Integration Schemas
class MicrosoftIntegrationBase(BaseModel):
    tenant_id: str = Field(..., description="Directory (tenant) ID from Azure AD")
    client_id: str = Field(..., description="Application (client) ID from Azure AD")
    client_secret: str = Field(..., description="Client secret from Azure AD")
    redirect_uri: str = Field(..., description="Redirect URI for OAuth flow")
    scope: str = Field("offline_access User.Read Mail.Read Mail.ReadWrite Mail.ReadBasic Mail.ReadBasic.All Mail.Read.All", description="Microsoft Graph API permissions")
    is_active: bool = Field(True, description="Whether this integration is active")

    class Config:
        from_attributes = True

class MicrosoftIntegrationCreate(MicrosoftIntegrationBase):
    pass

class MicrosoftIntegrationUpdate(BaseModel):
    tenant_id: Optional[str] = Field(None, description="Directory (tenant) ID from Azure AD")
    client_id: Optional[str] = Field(None, description="Application (client) ID from Azure AD")
    client_secret: Optional[str] = Field(None, description="Client secret from Azure AD")
    redirect_uri: Optional[str] = Field(None, description="Redirect URI for OAuth flow")
    scope: Optional[str] = Field(None, description="Microsoft Graph API permissions")
    is_active: Optional[bool] = Field(None, description="Whether this integration is active")

    class Config:
        from_attributes = True

class MicrosoftIntegrationInDB(MicrosoftIntegrationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class MicrosoftIntegration(MicrosoftIntegrationInDB):
    class Config:
        from_attributes = True

# Microsoft Token Schemas
class MicrosoftTokenBase(BaseModel):
    integration_id: int = Field(..., description="Reference to microsoft_integration table")
    agent_id: Optional[int] = Field(None, description="Reference to the agent who owns this token")
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str = Field(..., description="OAuth refresh token")
    token_type: str = Field("Bearer", description="Token type, typically Bearer")
    expires_at: datetime = Field(..., description="When the access token expires")

    class Config:
        from_attributes = True

class MicrosoftTokenCreate(BaseModel):
    integration_id: int = Field(..., description="Reference to microsoft_integration table")
    agent_id: Optional[int] = Field(None, description="Reference to the agent who owns this token")
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str = Field(..., description="OAuth refresh token")
    token_type: str = Field("Bearer", description="Token type, typically Bearer")
    expires_in: int = Field(..., description="Token expiration in seconds")

    class Config:
        from_attributes = True

class MicrosoftTokenUpdate(BaseModel):
    access_token: Optional[str] = Field(None, description="OAuth access token")
    refresh_token: Optional[str] = Field(None, description="OAuth refresh token")
    token_type: Optional[str] = Field(None, description="Token type, typically Bearer")
    expires_at: Optional[datetime] = Field(None, description="When the access token expires")

    class Config:
        from_attributes = True

class MicrosoftTokenInDB(MicrosoftTokenBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class MicrosoftToken(MicrosoftTokenInDB):
    is_expired: bool = False

    class Config:
        from_attributes = True

# Email Mapping Schemas
class EmailTicketMappingBase(BaseModel):
    email_id: str = Field(..., description="Unique ID of the email from Microsoft")
    email_conversation_id: Optional[str] = Field(None, description="Conversation ID from email for threading")
    task_id: int = Field(..., description="Reference to the task/ticket")
    email_subject: Optional[str] = Field(None, description="Subject of the email")
    email_sender: Optional[str] = Field(None, description="Sender email address")
    email_received_at: Optional[datetime] = Field(None, description="When the email was received")
    is_processed: bool = Field(False, description="Whether this email has been processed")

    class Config:
        from_attributes = True

class EmailTicketMappingCreate(EmailTicketMappingBase):
    pass

class EmailTicketMappingUpdate(BaseModel):
    email_conversation_id: Optional[str] = Field(None, description="Conversation ID from email for threading")
    email_subject: Optional[str] = Field(None, description="Subject of the email")
    email_sender: Optional[str] = Field(None, description="Sender email address")
    email_received_at: Optional[datetime] = Field(None, description="When the email was received")
    is_processed: Optional[bool] = Field(None, description="Whether this email has been processed")

    class Config:
        from_attributes = True

class EmailTicketMapping(EmailTicketMappingBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Email Sync Config Schemas
class EmailSyncConfigBase(BaseModel):
    integration_id: int = Field(..., description="Reference to microsoft_integration table")
    folder_name: str = Field("Inbox", description="Email folder to monitor")
    sync_interval: int = Field(5, description="Interval in minutes between syncs")
    last_sync_time: Optional[datetime] = Field(None, description="Last successful sync time")
    default_priority: str = Field("Medium", description="Default priority for tickets from email")
    auto_assign: bool = Field(False, description="Whether to auto-assign tickets")
    default_assignee_id: Optional[int] = Field(None, description="Default agent to assign tickets to if auto_assign is true")
    is_active: bool = Field(True, description="Whether sync is active")

    class Config:
        from_attributes = True

class EmailSyncConfigCreate(EmailSyncConfigBase):
    pass

class EmailSyncConfigUpdate(BaseModel):
    folder_name: Optional[str] = None
    sync_interval: Optional[int] = None
    default_priority: Optional[str] = None
    auto_assign: Optional[bool] = None
    default_assignee_id: Optional[int] = None
    is_active: Optional[bool] = None

    class Config:
        from_attributes = True

class EmailSyncConfigInDB(EmailSyncConfigBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class EmailSyncConfig(EmailSyncConfigInDB):
    class Config:
        from_attributes = True

# OAuth Flow schemas
class OAuthRequest(BaseModel):
    redirect_uri: Optional[str] = None
    tenant_id: Optional[str] = None

    class Config:
        from_attributes = True

class OAuthCallback(BaseModel):
    code: str
    state: Optional[str] = None
    error: Optional[str] = None
    error_description: Optional[str] = None

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    scope: str

    class Config:
        from_attributes = True

# Email schemas for processing
class EmailAttachment(BaseModel):
    id: str
    name: str
    content_type: str
    size: int
    content: Optional[bytes] = None
    is_inline: bool = False

    class Config:
        from_attributes = True

class EmailAddress(BaseModel):
    name: Optional[str] = None
    address: EmailStr

    class Config:
        from_attributes = True

class EmailData(BaseModel):
    id: str
    conversation_id: Optional[str] = None
    subject: str
    sender: EmailAddress
    to_recipients: List[EmailAddress]
    cc_recipients: Optional[List[EmailAddress]] = []
    bcc_recipients: Optional[List[EmailAddress]] = []
    body_content: str
    body_type: str = "html"  # html or text
    received_at: datetime
    attachments: Optional[List[EmailAttachment]] = []
    importance: Optional[str] = "normal"
    has_attachments: bool = False
    
    @validator('to_recipients')
    def validate_recipients(cls, v):
        if not v:
            raise ValueError('At least one recipient is required')
        return v 
    
    @property
    def from_email(self) -> str:
        """Alias to get the sender's email address"""
        return self.sender.address if self.sender else ""

    class Config:
        from_attributes = True 