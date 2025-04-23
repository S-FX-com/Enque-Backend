from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, Boolean, ForeignKey, func, Index
from sqlalchemy.dialects.mysql import LONGTEXT # Import LONGTEXT
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class TicketBody(Base):
    """Stores the potentially large body content of tickets, especially those from emails."""
    __tablename__ = "ticket_bodies"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    # Change Text to LONGTEXT for larger email bodies
    email_body = Column(LONGTEXT, nullable=True)

    # Relationship back to the ticket
    ticket = relationship("Task", back_populates="body")

class Task(Base):
    """Task model (also referred to as Ticket in the frontend)"""
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    title = Column(String(255), nullable=False)
    # Description can now be used for manual descriptions or summaries
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
    mailbox_connection_id = Column(Integer, ForeignKey("mailbox_connections.id", ondelete="SET NULL"), nullable=True, index=True) # Added for email replies

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
    
    # Relationship to the separate body content
    body = relationship("TicketBody", back_populates="ticket", uselist=False, cascade="all, delete-orphan")
    mailbox_connection = relationship("MailboxConnection", back_populates="tasks") # Added for email replies

    # Helper para verificar si el ticket se creó a partir de un email
    @property
    def is_from_email(self):
        """Check if this task was created from an email"""
        return bool(self.email_mappings)
