from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.libs.database import Base

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=False)
    status = Column(Enum("Unread", "Open", "Closed", name="ticket_status"), nullable=False, default="Unread")
    priority = Column(Enum("Low", "Medium", "High", name="ticket_priority"), nullable=False, default="Medium")
    due_date = Column(DateTime, nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sent_from_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    sent_to_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    deleted_at = Column(DateTime, nullable=True)

    workspace = relationship("Workspace", foreign_keys=[workspace_id])
    team = relationship("Team", foreign_keys=[team_id])
    company = relationship("Company", foreign_keys=[company_id])
    user = relationship("User", foreign_keys=[user_id])
    sent_from = relationship("Agent", foreign_keys=[sent_from_id])
    sent_to = relationship("Agent", foreign_keys=[sent_to_id])
    email_mappings = relationship("EmailTicketMapping", back_populates="ticket")
