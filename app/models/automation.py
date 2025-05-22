from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, JSON, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base_class import Base


class Automation(Base):
    __tablename__ = "automations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)  # 'scheduled', 'event-based', etc.
    is_enabled = Column(Boolean, default=False)
    schedule = Column(JSON, nullable=False)  # {frequency, day, time}
    template = Column(JSON, nullable=False)  # {subject, content}
    filters = Column(JSON, nullable=True)  # Any additional filters for the automation
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship
    workspace = relationship("Workspace", back_populates="automations") 