from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.schemas.schedule import ScheduleStatus
from app.database.base_class import Base

class schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    created_by_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    comment_id = Column(Integer, ForeignKey("comments.id"), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    scheduled_for = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)

    # Define unique constraint for name within a workspace
    #__table_args__ = (UniqueConstraint('name', 'workspace_id', name='uk_schedule_canned_reply_name_workspace'),)
    comment = relationship("Comment", back_populates="schedules")
    agent = relationship("Agent", back_populates="schedules")

    # Relationship to Workspace
    #workspace = relationship("Workspace") # Assuming Workspace model exists and has a relationship back

    # Relationship to tasks (one category can have many tasks)
    # The 'back_populates' should match the relationship name in the Task model
    #tasks = relationship("Task", back_populates="category")
