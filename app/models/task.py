from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database.base import Base

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum('Unread', 'Open', 'Closed', name='task_status'), default='Unread', nullable=False)
    priority = Column(Enum('Low', 'Medium', 'High', name='task_priority'), default='Medium', nullable=False)
    assignee_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    sent_from_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    is_read = Column(Boolean, default=False)
    
    # Relationships
    assignee = relationship("Agent", back_populates="assigned_tasks", foreign_keys=[assignee_id])
    sent_from = relationship("Agent", back_populates="sent_tasks", foreign_keys=[sent_from_id])
    team = relationship("Team", back_populates="tasks")
    user = relationship("User", back_populates="tasks")
    company = relationship("Company", back_populates="tasks")
    comments = relationship("Comment", back_populates="task")
    activities = relationship("Activity", back_populates="task")
    
    # Relación con los emails (Microsoft 365 integration)
    email_mappings = relationship("EmailTicketMapping", back_populates="task", cascade="all, delete-orphan")
    
    # Helper para verificar si el ticket se creó a partir de un email
    @property
    def is_from_email(self):
        """Check if this task was created from an email"""
        return bool(self.email_mappings) 