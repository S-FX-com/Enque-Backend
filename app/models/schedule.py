from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database.base_class import Base

class Category(Base):
    __tablename__ = "schedule"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True) # Name is indexed, uniqueness handled by constraint
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True) # Added workspace_id FK
    created_by_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    scheduled_for = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Define unique constraint for name within a workspace
    __table_args__ = (UniqueConstraint('name', 'workspace_id', name='uk_category_name_workspace'),)

    # Relationship to Workspace
    workspace = relationship("Workspace") # Assuming Workspace model exists and has a relationship back

    # Relationship to tasks (one category can have many tasks)
    # The 'back_populates' should match the relationship name in the Task model
    tasks = relationship("Task", back_populates="category")
