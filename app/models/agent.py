# backend/app/models/agent.py
from sqlalchemy import Column, Integer, String, Enum, DateTime, func, Boolean, ForeignKey, Text # Import Text
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False, unique=True, index=True)
    password = Column(String(255), nullable=True) # Make password nullable
    avatar = Column(String(255), nullable=True)
    # Add 'manager' to the Enum definition
    role = Column(Enum('admin', 'agent', 'manager', name='agent_role'), default='agent', nullable=False)
    # Add new fields
    job_title = Column(String(255), nullable=True)
    phone_number = Column(String(50), nullable=True)
    email_signature = Column(Text, nullable=True) # Add email_signature field (use Text)
    is_active = Column(Boolean, default=True, nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="agents")
    assigned_tasks = relationship("Task", back_populates="assignee", foreign_keys="[Task.assignee_id]", cascade="all, delete-orphan") # Cascade deletes
    sent_tasks = relationship("Task", back_populates="sent_from", foreign_keys="[Task.sent_from_id]", cascade="all, delete-orphan") # Cascade deletes (Check if needed)
    teams = relationship("TeamMember", back_populates="agent", cascade="all, delete-orphan") # Cascade deletes
    comments = relationship("Comment", back_populates="agent", cascade="all, delete-orphan") # Cascade deletes
    activities = relationship("Activity", back_populates="agent", cascade="all, delete-orphan") # Cascade deletes
    # Check cascade needs for these relationships too - might depend on business logic
    created_mailboxes = relationship("MailboxConnection", back_populates="created_by_agent") # Cascade might be needed if agent deletion should remove mailboxes they created
    microsoft_tokens = relationship("MicrosoftToken", back_populates="agent", cascade="all, delete-orphan") # Cascade deletes for tokens seems appropriate
