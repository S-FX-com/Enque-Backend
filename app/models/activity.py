from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.libs.database import Base
import enum


class ActivitySourceTypes(enum.Enum):
    workspace = "Workspace"
    ticket = "Ticket"
    team = "Team"
    company = "Company"
    user = "User"


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(255), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(Enum(ActivitySourceTypes), nullable=False)
    source_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    agent = relationship("Agent", foreign_keys=[agent_id])
    workspace = relationship("Workspace", foreign_keys=[workspace_id])
