from sqlalchemy import Column, Integer, String, Enum, DateTime, func, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False, unique=True, index=True)
    password = Column(String(255), nullable=False)
    avatar = Column(String(255), nullable=True)
    # Add 'manager' to the Enum definition
    role = Column(Enum('admin', 'agent', 'manager', name='agent_role'), default='agent', nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    workspace = relationship("Workspace", back_populates="agents")
    assigned_tasks = relationship("Task", back_populates="assignee", foreign_keys="[Task.assignee_id]")
    sent_tasks = relationship("Task", back_populates="sent_from", foreign_keys="[Task.sent_from_id]")
    teams = relationship("TeamMember", back_populates="agent")
    comments = relationship("Comment", back_populates="agent")
    activities = relationship("Activity", back_populates="agent")
    created_mailboxes = relationship("MailboxConnection", back_populates="created_by_agent")
    microsoft_tokens = relationship("MicrosoftToken", back_populates="agent")
