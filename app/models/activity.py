from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class Activity(Base):
    __tablename__ = "activities"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False)
    source_id = Column(Integer, nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    agent = relationship("Agent", back_populates="activities")
    workspace = relationship("Workspace", back_populates="activities")
    
    # Helper method to get ticket
    def get_ticket(self, db):
        """Get the ticket associated with this activity if source_type is 'Ticket' or 'Comment'"""
        if self.source_type in ['Ticket', 'Comment']:
            from app.models.task import Task
            return db.query(Task).filter(Task.id == self.source_id).first()
        return None