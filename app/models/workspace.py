from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.sql.sqltypes import TIMESTAMP
from app.database.base_class import Base

class Workspace(Base):
    """Workspace model for the database."""
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, index=True)
    subdomain = Column(String(255), nullable=False, unique=True, index=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    users = relationship("User", back_populates="workspace", cascade="all, delete-orphan")
    agents = relationship("Agent", back_populates="workspace")
    teams = relationship("Team", back_populates="workspace")
    companies = relationship("Company", back_populates="workspace")
    tasks = relationship("Task", back_populates="workspace", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="workspace")
    activities = relationship("Activity", back_populates="workspace")
    mailbox_connections = relationship("MailboxConnection", back_populates="workspace")
    global_signature = relationship("GlobalSignature", back_populates="workspace", uselist=False, cascade="all, delete-orphan")
    notification_templates = relationship("NotificationTemplate", back_populates="workspace", cascade="all, delete-orphan")
    notification_settings = relationship("NotificationSetting", back_populates="workspace", cascade="all, delete-orphan")
    workflows = relationship("Workflow", back_populates="workspace", cascade="all, delete-orphan")
    canned_replies = relationship("CannedReply", back_populates="workspace", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Workspace {self.subdomain}>" 