from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class Task(Base):
    """Task model (also referred to as Ticket in the frontend)"""
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum('Unread', 'Open', 'Closed', name='ticket_status'), default='Unread', nullable=False)
    priority = Column(Enum('Low', 'Medium', 'High', name='ticket_priority'), default='Medium', nullable=False)
    assignee_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    sent_from_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    sent_to_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    is_read = Column(Boolean, default=False)
    
    # Relationships
    workspace = relationship("Workspace", back_populates="tasks")
    assignee = relationship("Agent", back_populates="assigned_tasks", foreign_keys=[assignee_id])
    sent_from = relationship("Agent", back_populates="sent_tasks", foreign_keys=[sent_from_id])
    sent_to = relationship("Agent", foreign_keys=[sent_to_id])
    team = relationship("Team", back_populates="tasks")
    user = relationship("User", back_populates="tasks")
    company = relationship("Company", back_populates="tasks")
    comments = relationship("Comment", back_populates="ticket")
    
    # Relación con los emails (Microsoft 365 integration)
    email_mappings = relationship("EmailTicketMapping", back_populates="ticket", cascade="all, delete-orphan")
    
    # Helper para verificar si el ticket se creó a partir de un email
    @property
    def is_from_email(self):
        """Check if this task was created from an email"""
        return bool(self.email_mappings) 