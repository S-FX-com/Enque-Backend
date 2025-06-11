from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.sql.sqltypes import TIMESTAMP
from app.database.base_class import Base

class GlobalSignature(Base):
    """Global signature model for the database."""
    __tablename__ = "global_signatures"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True)
    content = Column(Text, nullable=False, default="")
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    workspace = relationship("Workspace", back_populates="global_signature")

    def __repr__(self):
        return f"<GlobalSignature id={self.id} workspace_id={self.workspace_id}>" 