from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, Boolean, ForeignKey, func, Index
from sqlalchemy.dialects.mysql import LONGTEXT 
from sqlalchemy.orm import relationship
from app.database.base_class import Base
from .category import Category 

class TicketBody(Base):
    """Stores the potentially large body content of tickets, especially those from emails."""
    __tablename__ = "ticket_bodies"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    email_body = Column(LONGTEXT, nullable=True)
    ticket = relationship("Task", back_populates="body")

class Task(Base):
    """Task model (also referred to as Ticket in the frontend)"""
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum('Unread', 'Open', 'With User', 'In Progress', 'Closed', name='ticket_status'), default='Unread', nullable=False) 
    priority = Column(Enum('Low', 'Medium', 'High', 'Critical', name='ticket_priority'), default='Medium', nullable=False)
    assignee_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    last_update = Column(DateTime, nullable=True)
    sent_from_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    sent_to_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    is_read = Column(Boolean, default=False)
    mailbox_connection_id = Column(Integer, ForeignKey("mailbox_connections.id", ondelete="SET NULL"), nullable=True, index=True) 
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True) 

    # Email-related columns
    email_message_id = Column(String(255), nullable=True, index=True)
    email_internet_message_id = Column(String(255), nullable=True, index=True)
    email_conversation_id = Column(String(255), nullable=True)
    email_sender = Column(String(1000), nullable=True)  # Increased for long forwarded email addresses
    to_recipients = Column(Text, nullable=True)
    cc_recipients = Column(Text, nullable=True)
    bcc_recipients = Column(Text, nullable=True)

    # Merge-related columns
    merged_to_ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    is_merged = Column(Boolean, default=False, index=True)
    merged_at = Column(DateTime, nullable=True)
    merged_by_agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    workspace = relationship("Workspace", back_populates="tasks")
    assignee = relationship("Agent", back_populates="assigned_tasks", foreign_keys=[assignee_id])
    sent_from = relationship("Agent", back_populates="sent_tasks", foreign_keys=[sent_from_id])
    sent_to = relationship("Agent", foreign_keys=[sent_to_id])
    team = relationship("Team", back_populates="tasks")
    user = relationship("User", back_populates="tasks")
    company = relationship("Company", back_populates="tasks")
    comments = relationship("Comment", back_populates="ticket", cascade="all, delete-orphan") 
    scheduled_comments = relationship("ScheduledComment", back_populates="ticket", cascade="all, delete-orphan")
    email_mappings = relationship("EmailTicketMapping", back_populates="ticket", cascade="all, delete-orphan")
    body = relationship("TicketBody", back_populates="ticket", uselist=False, cascade="all, delete-orphan")
    mailbox_connection = relationship("MailboxConnection", back_populates="tasks") 
    category = relationship("Category", back_populates="tasks") 
    
    # Merge relationships
    merged_to_ticket = relationship("Task", remote_side=[id], foreign_keys=[merged_to_ticket_id])
    merged_tickets = relationship("Task", foreign_keys=[merged_to_ticket_id], overlaps="merged_to_ticket")
    merged_by_agent = relationship("Agent", foreign_keys=[merged_by_agent_id])
    
    @property
    def is_from_email(self):
        """Check if this task was created from an email"""
        return bool(self.email_mappings)
