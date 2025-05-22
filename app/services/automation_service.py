from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.automation import Automation
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.automation import AutomationCreate, AutomationUpdate, AutomationRunResponse

def get_automations_by_workspace(db: Session, workspace_id: int) -> List[Automation]:
    """Get all automations for a specific workspace."""
    return db.query(Automation).filter(Automation.workspace_id == workspace_id).all()

def get_automation_by_id(db: Session, workspace_id: int, automation_id: int) -> Optional[Automation]:
    """Get a specific automation by ID."""
    return (
        db.query(Automation)
        .filter(Automation.workspace_id == workspace_id, Automation.id == automation_id)
        .first()
    )

def create_automation(
    db: Session, workspace_id: int, automation_data: AutomationCreate
) -> Automation:
    """Create a new automation."""
    # Verificar que el workspace existe
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Workspace with ID {workspace_id} not found"
        )
    
    # Crear la automatización
    db_automation = Automation(
        workspace_id=workspace_id,
        name=automation_data.name,
        description=automation_data.description,
        type=automation_data.type,
        is_enabled=automation_data.is_enabled,
        schedule=automation_data.schedule.dict(),
        template=automation_data.template.dict(),
        filters=automation_data.filters,
    )
    
    # Guardar en la base de datos
    db.add(db_automation)
    db.commit()
    db.refresh(db_automation)
    
    return db_automation

def update_automation(
    db: Session, automation: Automation, automation_data: AutomationUpdate
) -> Automation:
    """Update an existing automation."""
    # Actualizar los campos proporcionados
    update_data = automation_data.dict(exclude_unset=True)
    
    for field, value in update_data.items():
        if field in ["schedule", "template"] and value is not None:
            # Para campos JSON, convertir el objeto Pydantic a diccionario si es necesario
            if hasattr(value, 'dict'):
                setattr(automation, field, value.dict())
            else:
                # Si ya es un diccionario, usarlo directamente
                setattr(automation, field, value)
        else:
            setattr(automation, field, value)
    
    # Guardar en la base de datos
    db.add(automation)
    db.commit()
    db.refresh(automation)
    
    return automation

def delete_automation(db: Session, automation: Automation) -> None:
    """Delete an automation."""
    db.delete(automation)
    db.commit()

def toggle_automation_status(db: Session, automation: Automation, is_enabled: bool) -> Automation:
    """Toggle the enabled status of an automation."""
    automation.is_enabled = is_enabled
    
    # Guardar en la base de datos
    db.add(automation)
    db.commit()
    db.refresh(automation)
    
    return automation

def run_automation(
    db: Session, automation: Automation, current_user: User
) -> AutomationRunResponse:
    """Run an automation immediately."""
    try:
        # Aquí iría la lógica para ejecutar la automatización según su tipo
        if automation.type == "scheduled":
            # Para automatizaciones programadas, ejecutamos la lógica de envío de correo
            # Esta es una implementación básica que debería ser expandida según los requisitos
            result = _execute_email_automation(db, automation, current_user)
            return AutomationRunResponse(
                success=True,
                message=f"Automation '{automation.name}' executed successfully",
            )
        else:
            # Otros tipos de automatización
            return AutomationRunResponse(
                success=False,
                message=f"Automation type '{automation.type}' not supported for manual execution",
            )
    except Exception as e:
        # Capturar cualquier error durante la ejecución
        return AutomationRunResponse(
            success=False,
            message=f"Error executing automation: {str(e)}",
        )

def _execute_email_automation(db: Session, automation: Automation, current_user: User) -> bool:
    """Execute an email automation (helper function)."""
    # Esta función debería implementar la lógica para enviar correos electrónicos
    # basados en la plantilla y filtros de la automatización
    
    # Obtener los destinatarios según los filtros
    recipients = []
    if automation.filters and "recipients" in automation.filters:
        recipient_ids = automation.filters.get("recipients", [])
        if recipient_ids:
            recipients = db.query(User).filter(User.id.in_(recipient_ids)).all()
    
    # Si no hay destinatarios, la automatización no puede ejecutarse
    if not recipients:
        print(f"No recipients found for automation: {automation.name}")
        return False
    
    # Procesar la plantilla de correo electrónico
    subject = automation.template.get('subject', '')
    content = automation.template.get('content', '')
    
    # Aquí iría el código para procesar plantillas, reemplazar variables, etc.
    
    # Simular envío de correos electrónicos
    print(f"Executing email automation: {automation.name}")
    print(f"Subject: {subject}")
    print(f"Recipients: {[user.email for user in recipients]}")
    print(f"Triggered by user: {current_user.email}")
    
    # En una implementación real, aquí se enviarían los correos
    # Por ejemplo:
    # for recipient in recipients:
    #     send_email(recipient.email, subject, content)
    
    return True

def get_due_automations(db: Session) -> List[Automation]:
    """Get automations that are due to run (for scheduled tasks)."""
    # Esta función sería utilizada por un trabajo programado para obtener
    # las automatizaciones que deben ejecutarse según su programación
    
    # Obtener solo automatizaciones habilitadas
    automations = db.query(Automation).filter(Automation.is_enabled == True).all()
    
    # Filtrar las que corresponden ejecutar ahora según su programación
    now = datetime.now()
    due_automations = []
    
    for automation in automations:
        if _is_automation_due(automation, now):
            due_automations.append(automation)
    
    return due_automations

def _is_automation_due(automation: Automation, current_time: datetime) -> bool:
    """Check if an automation is due to run based on its schedule."""
    # Esta es una implementación básica que debe adaptarse según los requisitos exactos
    schedule = automation.schedule
    
    # Verificar si la automatización está programada para esta hora
    if schedule.get("time") != current_time.strftime("%H:%M"):
        return False
    
    frequency = schedule.get("frequency", "")
    
    if frequency == "daily":
        # Ejecutar diariamente a la hora especificada
        return True
    
    elif frequency == "weekly":
        # Ejecutar en el día de la semana especificado
        day_of_week = schedule.get("day", "").lower()
        current_day = current_time.strftime("%A").lower()
        return day_of_week == current_day
    
    elif frequency == "monthly":
        # Ejecutar en el día del mes especificado
        day_of_month = schedule.get("day")
        try:
            day = int(day_of_month)
            return day == current_time.day
        except (ValueError, TypeError):
            return False
    
    return False 