from sqlalchemy import Column, Integer, String, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    phone = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    # Specify foreign_keys to resolve ambiguity with Company.primary_contact_id
    company = relationship("Company", foreign_keys=[company_id], back_populates="users")
    workspace = relationship("Workspace", back_populates="users")
    tasks = relationship("Task", back_populates="user")


class UnassignedUser(Base):
    __tablename__ = "unassigned_users"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(50), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True) # Add workspace_id (nullable for now)
    created_at = Column(DateTime, default=func.now())

    # Optional: Add relationship back to workspace if needed
    # workspace = relationship("Workspace")
