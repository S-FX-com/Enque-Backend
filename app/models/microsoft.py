from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, DateTime, Index, Enum, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.base_class import Base
from datetime import datetime

# Junction table for many-to-many relationship between mailboxes and teams
mailbox_team_assignments = Table(
    'mailbox_team_assignments',
    Base.metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('mailbox_connection_id', Integer, ForeignKey('mailbox_connections.id', ondelete='CASCADE'), nullable=False),
    Column('team_id', Integer, ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
    Column('created_at', DateTime, default=func.now()),
    Index('idx_mailbox_team_assignments_mailbox_id', 'mailbox_connection_id'),
    Index('idx_mailbox_team_assignments_team_id', 'team_id'),
    Index('idx_unique_mailbox_team', 'mailbox_connection_id', 'team_id', unique=True)
)

class MailboxConnection(Base):
    __tablename__ = "mailbox_connections"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    created_by_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    is_global = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # Relaciones
    workspace = relationship("Workspace", back_populates="mailbox_connections")
    created_by_agent = relationship("Agent", back_populates="created_mailboxes")
    teams = relationship("Team", secondary=mailbox_team_assignments, back_populates="mailbox_connections")
    tokens = relationship("MicrosoftToken", back_populates="mailbox_connection")
    sync_configs = relationship("EmailSyncConfig", back_populates="mailbox_connection")
    tasks = relationship("Task", back_populates="mailbox_connection") # Added inverse relationship
    
    def __repr__(self):
        return f"<MailboxConnection email={self.email}>"

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
    mailbox_connection_id = Column(Integer, ForeignKey("mailbox_connections.id", ondelete="CASCADE"), nullable=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    token_type = Column(String(50), nullable=False, default="Bearer")
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    integration = relationship("MicrosoftIntegration", back_populates="tokens")
    agent = relationship("Agent", back_populates="microsoft_tokens")
    mailbox_connection = relationship("MailboxConnection", back_populates="tokens")

    # Indexes
    __table_args__ = (
        Index("idx_microsoft_tokens_integration_id", "integration_id"),
    )

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
    email_subject = Column(String(1000), nullable=True)  # Increased for long forwarded subjects
    email_sender = Column(String(1000), nullable=True)   # Increased for long forwarded email addresses
    email_received_at = Column(DateTime, nullable=True)
    is_processed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    ticket = relationship("Task", back_populates="email_mappings")

    # Indexes (already defined in the SQL but included here for completeness)
    __table_args__ = (
        Index("idx_email_ticket_mapping_task_id", "ticket_id"),
        Index("idx_email_ticket_mapping_conversation_id", "email_conversation_id"),
    )

class EmailSyncConfig(Base):
    __tablename__ = "email_sync_config"

    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("microsoft_integration.id", ondelete="CASCADE"), nullable=False)
    mailbox_connection_id = Column(Integer, ForeignKey("mailbox_connections.id", ondelete="CASCADE"), nullable=False)
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
    mailbox_connection = relationship("MailboxConnection", back_populates="sync_configs")

    # Indexes
    __table_args__ = (
        Index("idx_email_sync_config_integration_id", "integration_id"),
        Index("idx_email_sync_config_mailbox_id", "mailbox_connection_id"),
    )
