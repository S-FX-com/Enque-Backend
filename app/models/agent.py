from sqlalchemy import Column, Integer, String, Enum, DateTime, func
from sqlalchemy.orm import relationship
from app.database.base import Base

class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False, unique=True, index=True)
    password = Column(String(255), nullable=False)
    avatar = Column(String(255), nullable=True)
    role = Column(Enum('admin', 'manager', 'agent', name='agent_role'), default='agent', nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships - usando strings para evitar importaciones circulares
    assigned_tasks = relationship("Task", back_populates="assignee", foreign_keys="[Task.assignee_id]")
    sent_tasks = relationship("Task", back_populates="sent_from", foreign_keys="[Task.sent_from_id]")
    teams = relationship("TeamMember", back_populates="agent")
    comments = relationship("Comment", back_populates="user")
    activities = relationship("Activity", back_populates="user") 