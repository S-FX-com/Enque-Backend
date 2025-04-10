from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, DateTime, Index, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.libs.database import Base
from datetime import datetime

class MicrosoftIntegration(Base):
    __tablename__ = "microsoft_integration"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(100), nullable=False)
    client_id = Column(String(100), nullable=False)
    client_secret = Column(String(255), nullable=False)
    redirect_uri = Column(String(255), nullable=False)
    scope = Column(String(512), nullable=False, default="offline_access Mail.Read Mail.ReadWrite")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    tokens = relationship("MicrosoftToken", back_populates="integration", cascade="all, delete-orphan")
    sync_configs = relationship("EmailSyncConfig", back_populates="integration", cascade="all, delete-orphan")

class MicrosoftToken(Base):
    __tablename__ = "microsoft_tokens"

    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("microsoft_integration.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    token_type = Column(String(20), nullable=False, default="Bearer")
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    integration = relationship("MicrosoftIntegration", back_populates="tokens")
    agent = relationship("Agent")

    # Helpers
    def is_expired(self):
        """Check if the access token is expired"""
        return datetime.utcnow() > self.expires_at

class EmailTicketMapping(Base):
    __tablename__ = "email_ticket_mapping"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(String(255), nullable=False, unique=True)
    email_conversation_id = Column(String(255), nullable=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    email_subject = Column(String(255), nullable=True)
    email_sender = Column(String(255), nullable=True)
    email_received_at = Column(DateTime, nullable=True)
    is_processed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    ticket = relationship("Ticket", back_populates="email_mappings")

    # Indexes (already defined in the SQL but included here for completeness)
    __table_args__ = (
        Index("idx_email_ticket_mapping_task_id", "ticket_id"),
        Index("idx_email_ticket_mapping_conversation_id", "email_conversation_id"),
    )

class EmailSyncConfig(Base):
    __tablename__ = "email_sync_config"

    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("microsoft_integration.id", ondelete="CASCADE"), nullable=False)
    folder_name = Column(String(100), nullable=False, default="Inbox")
    sync_interval = Column(Integer, nullable=False, default=5)  # minutes
    last_sync_time = Column(DateTime, nullable=True)
    default_priority = Column(String(50), nullable=True, default="Medium")
    auto_assign = Column(Boolean, nullable=False, default=False)
    default_assignee_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    integration = relationship("MicrosoftIntegration", back_populates="sync_configs")
    default_assignee = relationship("Agent")
    workspace = relationship("Workspace")

    # Indexes
    __table_args__ = (
        Index("idx_email_sync_config_integration_id", "integration_id"),
    ) 