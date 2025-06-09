from sqlalchemy import Column, Integer, String, Text, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base_class import Base
# Import related models for foreign_keys argument
from app.models.user import User
from app.models.agent import Agent

class Company(Base):
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=True)
    email_domain = Column(String(255), nullable=True)
    logo_url = Column(String(255), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    primary_contact_id = Column(Integer, ForeignKey("users.id"), nullable=True) # Added
    account_manager_id = Column(Integer, ForeignKey("agents.id"), nullable=True) # Added
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    workspace = relationship("Workspace", back_populates="companies")
    # Specify the foreign key for the 'users' relationship explicitly using the column object
    users = relationship("User", foreign_keys=[User.company_id], back_populates="company")
    tasks = relationship("Task", back_populates="company")
    primary_contact = relationship("User", foreign_keys=[primary_contact_id])
    account_manager = relationship("Agent", foreign_keys=[account_manager_id]) # Added relationship
