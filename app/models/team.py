from sqlalchemy import Column, Integer, String, Text, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class Team(Base):
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    logo_url = Column(String(255), nullable=True)
    icon_name = Column(String(50), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    manager_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    workspace = relationship("Workspace", back_populates="teams")
    # Add cascade="all, delete-orphan" to automatically delete members when a team is deleted
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    # Add cascade to delete tasks associated with the team
    tasks = relationship("Task", back_populates="team", cascade="all, delete-orphan")
    manager = relationship("Agent", foreign_keys=[manager_id])


class TeamMember(Base):
    __tablename__ = "team_members"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    team = relationship("Team", back_populates="members")
    agent = relationship("Agent", back_populates="teams")
