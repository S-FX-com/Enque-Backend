from pydantic import BaseModel, computed_field
from datetime import datetime
# from typing import Optional # No se usa Optional aquí por ahora

class TicketAttachmentSchema(BaseModel):
    id: int
    file_name: str
    content_type: str
    file_size: int
    # download_url: str # Se define como computed_field abajo
    created_at: datetime

    @computed_field
    @property
    def download_url(self) -> str:
        # Si tenemos S3 URL, usarla directamente (nuevo sistema)
        if hasattr(self, '_s3_url') and self._s3_url:
            return self._s3_url
        
        # Fallback a API endpoint (sistema legacy)
        return f"/attachments/{self.id}" 
    
    # Método para establecer s3_url cuando se carga desde ORM
    def __init__(self, **data):
        # Extraer s3_url si existe en los datos
        s3_url = data.pop('s3_url', None)
        super().__init__(**data)
        self._s3_url = s3_url 

    model_config = {
        "from_attributes": True  # Permite la creación desde atributos de modelos ORM
    } 