from typing import Optional, List, ForwardRef
from pydantic import BaseModel, Field
from datetime import datetime
from app.schemas.agent import Agent as AgentSchema
from app.schemas.ticket_attachment import TicketAttachmentSchema

class CommentBase(BaseModel):
    content: str
    is_private: bool = False

class CommentCreate(CommentBase):
    ticket_id: int
    agent_id: Optional[int] = None  # Hacerlo opcional
    user_id: Optional[int] = None   # Campo agregado para user_id
    workspace_id: int
    attachment_ids: Optional[List[int]] = None  # IDs de adjuntos existentes para asociar
    # Campos adicionales para gestión de asignación y archivos adjuntos
    preserve_assignee: bool = False  # Flag para no cambiar el asignado actual
    assignee_id: Optional[int] = None  # ID de agente a asignar (si se quiere cambiar)
    other_destinaries: Optional[str] = None  # CC recipients
    bcc_recipients: Optional[str] = None       # BCC recipients
    is_attachment_upload: bool = False  # Flag para indicar si es una carga de adjunto
    # Schedule send field
    scheduled_send_at: Optional[datetime] = None  # If provided, comment will be scheduled instead of sent immediately

class CommentUpdate(BaseModel):
    content: Optional[str] = None
    is_private: Optional[bool] = None

class CommentInDBBase(CommentBase):
    id: int
    ticket_id: int
    agent_id: Optional[int] = None
    user_id: Optional[int] = None   # Campo agregado para user_id
    workspace_id: int
    other_destinaries: Optional[str] = None  # CC recipients
    bcc_recipients: Optional[str] = None     # BCC recipients
    s3_html_url: Optional[str] = None  # URL del contenido en S3
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }

class Comment(CommentInDBBase):
    agent: Optional[AgentSchema] = None
    attachments: Optional[List[TicketAttachmentSchema]] = []

    model_config = {
        "from_attributes": True
    }
