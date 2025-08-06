from sqlalchemy import Column, Integer, String, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    avatar_url = Column(String(500), nullable=True)  # URL del avatar del usuario
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    phone = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    company = relationship("Company", foreign_keys=[company_id], back_populates="users")
    workspace = relationship("Workspace", back_populates="users")
    tasks = relationship("Task", back_populates="user")
    comments = relationship("Comment", back_populates="user")


class UnassignedUser(Base):
    __tablename__ = "unassigned_users"
    
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(50), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True) 
    created_at = Column(DateTime, default=func.now())

