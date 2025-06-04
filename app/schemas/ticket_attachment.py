from pydantic import BaseModel, computed_field
from datetime import datetime
from typing import Optional

class TicketAttachmentSchema(BaseModel):
    id: int
    file_name: str
    content_type: str
    file_size: int
    s3_url: Optional[str] = None  # New field for S3 URL
    # download_url: str # Se define como computed_field abajo
    created_at: datetime

    @computed_field
    @property
    def download_url(self) -> str:
        # If we have S3 URL, return it directly for faster access
        if self.s3_url:
            return self.s3_url
        
        # Otherwise use the API endpoint (for legacy attachments)
        # Esta URL es relativa a la raíz de la API. 
        # El frontend necesitará componer la URL base completa si es necesario.
        # Asumiendo que el router de attachments está montado en la raíz de la API (o /api/v1)
        # y el endpoint es /attachments/{id}
        return f"/attachments/{self.id}" 

    model_config = {
        "from_attributes": True  # Permite la creación desde atributos de modelos ORM
    } 