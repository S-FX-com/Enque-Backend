from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.base_class import Base


class CannedReply(Base):
    __tablename__ = "canned_replies"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    created_by_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    usage_count = Column(Integer, nullable=False, default=0)  # Track how often it's used
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # Relationships
    workspace = relationship("Workspace", back_populates="canned_replies")
    created_by_agent = relationship("Agent", back_populates="created_canned_replies")
    
    # Indexes for better performance
    __table_args__ = (
        Index("idx_canned_replies_workspace_id", "workspace_id"),
        Index("idx_canned_replies_workspace_enabled", "workspace_id", "is_enabled"),
        Index("idx_canned_replies_name_workspace", "name", "workspace_id"),
    )
    
    def __repr__(self):
        return f"<CannedReply name={self.name} workspace_id={self.workspace_id}>"
    
    def increment_usage(self):
        """Helper method to increment usage count"""
        self.usage_count += 1