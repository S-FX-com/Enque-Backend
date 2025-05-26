from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import pytz
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.automation import Automation
from app.models.user import User
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.models.microsoft import MailboxConnection, MicrosoftToken
from app.services.microsoft_service import MicrosoftGraphService
from app.schemas.automation import AutomationCreate, AutomationUpdate, AutomationRunResponse
from app.utils.logger import logger

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

async def run_automation(
    db: Session, automation: Automation, current_agent: Agent
) -> AutomationRunResponse:
    """Run an automation immediately."""
    try:
        # Aquí iría la lógica para ejecutar la automatización según su tipo
        if automation.type == "scheduled":
            # Para automatizaciones programadas, ejecutamos la lógica de envío de correo
            # Esta es una implementación básica que debería ser expandida según los requisitos
            result = await _execute_email_automation(db, automation, current_agent)
            if result:
                return AutomationRunResponse(
                    success=True,
                    message=f"Automation '{automation.name}' executed successfully",
                )
            else:
                return AutomationRunResponse(
                    success=False,
                    message=f"Automation '{automation.name}' failed to execute. Check server logs for details.",
                )
        else:
            # Otros tipos de automatización
            return AutomationRunResponse(
                success=False,
                message=f"Automation type '{automation.type}' not supported for manual execution",
            )
    except Exception as e:
        # Capturar cualquier error durante la ejecución
        logger.error(f"Error executing automation {automation.id}: {str(e)}", exc_info=True)
        return AutomationRunResponse(
            success=False,
            message=f"Error executing automation: {str(e)}",
        )

async def _execute_email_automation(db: Session, automation: Automation, current_agent: Agent) -> bool:
    """Execute an email automation using Microsoft Graph API."""
    try:
        logger.info(f"Starting execution of automation ID: {automation.id}, Name: {automation.name}")
        
        # Obtener los destinatarios según los filtros
        recipients = []
        if automation.filters and "recipients" in automation.filters:
            recipient_ids = automation.filters.get("recipients", [])
            logger.info(f"Found recipient IDs in automation filters: {recipient_ids}")
            
            if recipient_ids:
                # Convertir a enteros si vienen como strings
                parsed_ids = []
                for id_str in recipient_ids:
                    try:
                        parsed_ids.append(int(id_str))
                    except ValueError:
                        logger.error(f"Invalid recipient ID format: {id_str}")
                
                if parsed_ids:
                    logger.info(f"Querying for AGENTS with IDs: {parsed_ids}")
                    recipients = db.query(Agent).filter(Agent.id.in_(parsed_ids)).all()
                    logger.info(f"Found {len(recipients)} agent recipients: {[f'ID:{r.id}, Email:{r.email}' for r in recipients]}")
                else:
                    logger.error("No valid recipient IDs found after parsing")
        else:
            logger.error(f"No recipients field found in automation filters: {automation.filters}")
        
        # Si no hay destinatarios, la automatización no puede ejecutarse
        if not recipients:
            logger.error(f"No recipients found for automation: {automation.name}")
            return False
        
        # Obtener información de la plantilla de correo
        subject = automation.template.get('subject', '')
        content = automation.template.get('content', '')
        logger.info(f"Email template - Subject: '{subject}', Content length: {len(content)} chars")
        
        if not subject or not content:
            logger.error(f"Missing subject or content for automation: {automation.name}")
            return False
        
        # Buscar una conexión de mailbox válida para enviar el correo
        # Primero intentamos usar la conexión del usuario que ejecuta la automatización
        logger.info(f"Looking for mailbox connection for user ID: {current_agent.id}")
        
        # Corregido: Usamos created_by_agent_id en lugar de user_id
        logger.info(f"Querying for mailbox with created_by_agent_id = {current_agent.id}")
        mailbox_connection = db.query(MailboxConnection).filter(
            MailboxConnection.created_by_agent_id == current_agent.id,
            MailboxConnection.is_active == True
        ).first()
        
        # Si no tiene mailbox, buscar algún otro mailbox activo en el workspace
        if not mailbox_connection:
            logger.info(f"No mailbox found for current user. Looking for any mailbox in workspace: {automation.workspace_id}")
            mailbox_connection = db.query(MailboxConnection).filter(
                MailboxConnection.workspace_id == automation.workspace_id,
                MailboxConnection.is_active == True
            ).first()
        
        if not mailbox_connection:
            logger.error(f"No valid mailbox connection found for automation: {automation.name}")
            return False
        
        logger.info(f"Found mailbox connection: ID:{mailbox_connection.id}, Email:{mailbox_connection.email}")
        
        # Obtener token válido para la conexión
        logger.info(f"Getting token for mailbox: {mailbox_connection.email}")
        graph_service = MicrosoftGraphService(db=db)
        
        # Debug: inspeccionar la conexión del buzón
        mailbox = db.query(MailboxConnection).filter(
            MailboxConnection.id == mailbox_connection.id
        ).first()
        
        if not mailbox:
            logger.error(f"Could not retrieve mailbox with ID: {mailbox_connection.id}")
            return False
            
        # Obtener el token más reciente para este mailbox
        token_record = db.query(MicrosoftToken).filter(
            MicrosoftToken.mailbox_connection_id == mailbox.id
        ).order_by(MicrosoftToken.expires_at.desc()).first()
        
        if not token_record:
            logger.error(f"No token record found for mailbox: {mailbox.email}")
            return False
            
        token = token_record.access_token
        logger.info(f"Token retrieved for mailbox: {mailbox.email} - Token valid: {bool(token)}")
        
        if not token:
            logger.error(f"No valid token found for mailbox: {mailbox_connection.email}")
            return False
        
        # Enviar correo a cada destinatario
        success_count = 0
        for recipient in recipients:
            try:
                logger.info(f"Preparing to send email to: {recipient.email} (ID: {recipient.id})")
                # Añadir personalización simple si se desea
                personalized_content = content.replace("[User Name]", recipient.name)
                
                # Usar MicrosoftGraphService para enviar el correo
                logger.info(f"Calling Microsoft Graph API to send email from {mailbox.email} to {recipient.email}")
                success = await graph_service.send_email_with_user_token(
                    user_access_token=token,
                    sender_mailbox_email=mailbox.email,
                    recipient_email=recipient.email,
                    subject=subject,
                    html_body=personalized_content
                )
                
                if success:
                    success_count += 1
                    logger.info(f"✅ Email successfully sent to {recipient.email} for automation: {automation.name}")
                else:
                    logger.error(f"❌ Failed to send email to {recipient.email} for automation: {automation.name}")
            except Exception as e:
                logger.error(f"Error sending email to {recipient.email}: {str(e)}", exc_info=True)
        
        # Considerar exitosa la automatización si al menos un correo se envió
        logger.info(f"Automation {automation.id} finished. Successfully sent {success_count}/{len(recipients)} emails")
        return success_count > 0
    except Exception as e:
        logger.error(f"Error in _execute_email_automation for automation {automation.id}: {str(e)}", exc_info=True)
        return False

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
    automation_id = getattr(automation, 'id', 'unknown')
    
    # Usar pytz para manejar correctamente la zona horaria de Nueva Jersey (Eastern Time)
    eastern_tz = pytz.timezone('America/New_York')
    
    # Si current_time no tiene zona horaria, asumimos que es UTC
    if current_time.tzinfo is None:
        current_time = pytz.utc.localize(current_time)
    
    # Convertir a hora de Nueva Jersey
    adjusted_time = current_time.astimezone(eastern_tz)
    adjusted_time_str = adjusted_time.strftime("%H:%M")
    
    # Convertir la hora actual a formato HH:MM para comparar
    current_time_str = current_time.strftime("%H:%M")
    scheduled_time = schedule.get("time", "")
    
    logger.info(f"Checking if automation {automation_id} is due. UTC time: {current_time_str}, ET time: {adjusted_time_str}, Scheduled time: {scheduled_time}")
    
    # Verificar si la automatización está programada para esta hora
    if scheduled_time != adjusted_time_str:
        logger.info(f"Automation {automation_id} is not due yet. Expected time: {scheduled_time}, Current ET time: {adjusted_time_str}")
        return False
    
    frequency = schedule.get("frequency", "")
    logger.info(f"Automation {automation_id} frequency: {frequency}")
    
    # Para las comparaciones de día, usamos la fecha ajustada a la zona horaria de Nueva Jersey
    if frequency == "daily":
        # Ejecutar diariamente a la hora especificada
        logger.info(f"Automation {automation_id} is due (daily schedule matches current ET time)")
        return True
    
    elif frequency == "weekly":
        # Ejecutar en el día de la semana especificado
        day_of_week = schedule.get("day", "").lower()
        current_day = adjusted_time.strftime("%A").lower()
        
        logger.info(f"Automation {automation_id} weekly check: Scheduled day: {day_of_week}, Current ET day: {current_day}")
        
        if day_of_week == current_day:
            logger.info(f"Automation {automation_id} is due (weekly schedule matches current ET day and time)")
            return True
        else:
            logger.info(f"Automation {automation_id} is not due today (expecting day: {day_of_week}, current ET day: {current_day})")
            return False
    
    elif frequency == "monthly":
        # Ejecutar en el día del mes especificado
        day_of_month = schedule.get("day")
        logger.info(f"Automation {automation_id} monthly check: Scheduled day: {day_of_month}, Current ET day: {adjusted_time.day}")
        
        try:
            day = int(day_of_month)
            if day == adjusted_time.day:
                logger.info(f"Automation {automation_id} is due (monthly schedule matches current ET day and time)")
                return True
            else:
                logger.info(f"Automation {automation_id} is not due today (expecting day of month: {day}, current ET day: {adjusted_time.day})")
                return False
        except (ValueError, TypeError):
            logger.error(f"Automation {automation_id} has invalid day value for monthly frequency: {day_of_month}")
            return False
    
    logger.warning(f"Automation {automation_id} has unknown frequency: {frequency}")
    return False 