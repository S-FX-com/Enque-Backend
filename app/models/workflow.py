from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

from app.database.base_class import Base

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    trigger = Column(String(100), nullable=False)  # 'ticket.created', 'ticket.updated', etc.
    message_analysis_rules = Column(JSON, nullable=True)  # Reglas de análisis de mensajes para triggers basados en contenido
    conditions = Column(JSON, nullable=True, default=list)  # Lista de condiciones
    actions = Column(JSON, nullable=True, default=list)  # Lista de acciones
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="workflows") 