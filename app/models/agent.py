from sqlalchemy import Column, Integer, String, Enum, DateTime, func, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False, index=True)
    password = Column(String(255), nullable=True) 
    avatar_url = Column(String(500), nullable=True) 
    role = Column(Enum('admin', 'agent', 'manager', name='agent_role'), default='agent', nullable=False)
    auth_method = Column(Enum('password', 'microsoft', 'both', name='auth_method'), default='password', nullable=False)
    job_title = Column(String(255), nullable=True)
    phone_number = Column(String(50), nullable=True)
    email_signature = Column(Text, nullable=True) 
    is_active = Column(Boolean, default=True, nullable=False)
    # Microsoft 365 integration fields
    microsoft_id = Column(String(255), nullable=True, unique=True, index=True)
    microsoft_email = Column(String(255), nullable=True, index=True)
    microsoft_tenant_id = Column(String(255), nullable=True)
    microsoft_profile_data = Column(Text, nullable=True)
    invitation_token = Column(String(255), nullable=True, unique=True, index=True)
    invitation_token_expires_at = Column(DateTime, nullable=True)
    password_reset_token = Column(String(255), nullable=True, unique=True, index=True)
    password_reset_token_expires_at = Column(DateTime, nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    last_login = Column(DateTime, nullable=True)
    last_login_origin = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint('email', 'workspace_id', name='uix_agent_email_workspace'),
    )
    workspace = relationship("Workspace", back_populates="agents")
    assigned_tasks = relationship("Task", back_populates="assignee", foreign_keys="[Task.assignee_id]", cascade="all, delete-orphan") 
    sent_tasks = relationship("Task", back_populates="sent_from", foreign_keys="[Task.sent_from_id]", cascade="all, delete-orphan") 
    teams = relationship("TeamMember", back_populates="agent", cascade="all, delete-orphan") 
    comments = relationship("Comment", back_populates="agent", cascade="all, delete-orphan") 
    activities = relationship("Activity", back_populates="agent", cascade="all, delete-orphan")
    created_mailboxes = relationship("MailboxConnection", back_populates="created_by_agent") 
    microsoft_tokens = relationship("MicrosoftToken", back_populates="agent", cascade="all, delete-orphan") 
    created_canned_replies = relationship("CannedReply", back_populates="created_by_agent", cascade="all, delete-orphan")
