from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.base_class import Base
import enum


class ScheduledCommentStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent" 
    CANCELLED = "cancelled"
    FAILED = "failed"


class ScheduledComment(Base):
    __tablename__ = "scheduled_comments"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    
    # Content fields
    content = Column(Text, nullable=False)
    is_private = Column(Boolean, default=False, nullable=False)
    other_destinaries = Column(Text, nullable=True)  # CC recipients
    bcc_recipients = Column(Text, nullable=True)     # BCC recipients
    attachment_ids = Column(JSON, nullable=True)     # Array of attachment IDs
    
    # Scheduling fields
    scheduled_send_at = Column(DateTime(timezone=False), nullable=False, index=True)
    status = Column(String(20), default=ScheduledCommentStatus.PENDING.value, nullable=False, index=True)
    
    # Audit fields
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    
    # Relationships
    ticket = relationship("Task", back_populates="scheduled_comments")
    agent = relationship("Agent")
    workspace = relationship("Workspace")