from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declared_attr

from app.database.base_class import Base


class NotificationTemplate(Base):
    """Modelo para las plantillas de notificaciones"""
    __tablename__ = "notification_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(100), nullable=False)  # 'ticket_created', 'ticket_resolved', etc.
    name = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    template = Column(Text, nullable=False)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="notification_templates")
    notification_settings = relationship(
        "NotificationSetting", 
        back_populates="template",
        primaryjoin="NotificationTemplate.id == NotificationSetting.template_id"
    )

    __table_args__ = (
        {"comment": "Tabla para almacenar plantillas de notificación"},
    )


class NotificationSetting(Base):
    """Modelo para la configuración de notificaciones"""
    __tablename__ = "notification_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(100), nullable=False)  # 'agents', 'users', etc.
    type = Column(String(100), nullable=False)  # 'new_ticket_created', 'ticket_resolved', etc.
    is_enabled = Column(Boolean, default=True)
    channels = Column(JSON, nullable=False)  # ["email", "teams", etc.]
    template_id = Column(Integer, ForeignKey("notification_templates.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="notification_settings")
    template = relationship(
        "NotificationTemplate", 
        back_populates="notification_settings",
        primaryjoin="NotificationSetting.template_id == NotificationTemplate.id"
    )

    __table_args__ = (
        {"comment": "Tabla para configuración de notificaciones"},
    ) 