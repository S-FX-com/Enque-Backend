from sqlalchemy import Column, Integer, String, LargeBinary, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database.base_class import Base

class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    content_bytes = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    comment = relationship("Comment", back_populates="attachments") 