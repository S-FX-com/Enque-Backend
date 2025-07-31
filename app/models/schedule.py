from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, UniqueConstraint, DateTime, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.schemas.schedule import ScheduleStatus
from app.database.base_class import Base

class schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    created_by_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    scheduled_for = Column(DateTime, nullable=False)
    status = Column(Enum(ScheduleStatus), default=ScheduleStatus.PENDING, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    # Relationship
    comment = relationship("Comment", back_populates="schedules")
    created_by_agent = relationship("Agent", back_populates="schedules")
    workspace = relationship("Workspace")
