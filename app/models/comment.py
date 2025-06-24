from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, func, Boolean
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    other_destinaries = Column(Text, nullable=True)  # CC recipients
    bcc_recipients = Column(Text, nullable=True)     # BCC recipients
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    content = Column(Text, nullable=True)  # Ahora puede ser NULL si está en S3
    s3_html_url = Column(Text, nullable=True)  # URL del HTML almacenado en S3
    is_private = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    ticket = relationship("Task", back_populates="comments")
    agent = relationship("Agent", back_populates="comments")
    workspace = relationship("Workspace", back_populates="comments")
    attachments = relationship("TicketAttachment", back_populates="comment", cascade="all, delete-orphan")
