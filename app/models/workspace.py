from sqlalchemy import Column, Integer, String, DateTime, func
from sqlalchemy.orm import relationship

from app.libs.database import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    local_subdomain = Column(String(255), nullable=False)
    email_domain = Column(String(255), nullable=False)
    logo_url = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    activities = relationship("Activity", back_populates="workspace")
    agents = relationship("Agent", back_populates="workspace")
    comments = relationship("Comment", back_populates="workspace")
    companies = relationship("Company", back_populates="workspace")
    teams = relationship("Team", back_populates="workspace")
    tickets = relationship("Ticket", back_populates="workspace")
    users = relationship("User", back_populates="workspace")
