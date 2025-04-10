from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime, func, Enum
from sqlalchemy.orm import relationship

from app.libs.database import Base

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    role = Column(Enum("Agent", "Admin", name="agent_role"), nullable=False, default="Agent")
    is_active = Column(Boolean, default=True)
    hashed_password = Column(String(100))
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    workspace = relationship("Workspace", foreign_keys=[workspace_id])