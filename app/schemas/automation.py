from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field, validator

# Esquema para la programación de automatización
class AutomationScheduleBase(BaseModel):
    frequency: str = Field(..., description="Frequency of the automation (daily, weekly, monthly)")
    day: Optional[str] = Field(None, description="Day of the week for weekly automations or day of the month for monthly")
    time: str = Field(..., description="Time of day to run the automation (HH:MM)")

# Esquema para la plantilla de correo electrónico
class AutomationTemplateBase(BaseModel):
    subject: str = Field(..., description="Email subject template")
    content: str = Field(..., description="Email content template (HTML)")

# Esquema base para automatización
class AutomationBase(BaseModel):
    name: str = Field(..., description="Name of the automation")
    description: Optional[str] = Field(None, description="Description of the automation")
    type: str = Field(..., description="Type of automation (scheduled, event-based)")
    is_enabled: bool = Field(False, description="Whether the automation is enabled")
    schedule: AutomationScheduleBase
    template: AutomationTemplateBase
    filters: Dict[str, Any] = Field({}, description="Filters for the automation")

    class Config:
        from_attributes = True

# Esquema para crear una automatización
class AutomationCreate(AutomationBase):
    pass

# Esquema para actualizar una automatización
class AutomationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    is_enabled: Optional[bool] = None
    schedule: Optional[AutomationScheduleBase] = None
    template: Optional[AutomationTemplateBase] = None
    filters: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

# Esquema para conmutar el estado de habilitado de una automatización
class AutomationToggleEnable(BaseModel):
    is_enabled: bool = Field(..., description="Whether the automation should be enabled or disabled")

# Esquema completo de automatización que incluye ID y timestamps
class AutomationInDB(AutomationBase):
    id: int
    workspace_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Esquema para la respuesta de ejecución de una automatización
class AutomationRunResponse(BaseModel):
    success: bool = Field(..., description="Whether the automation run was successful")
    message: str = Field(..., description="Status message for the automation run") 