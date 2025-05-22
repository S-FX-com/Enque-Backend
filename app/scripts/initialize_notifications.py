"""
Script para inicializar las configuraciones de notificación
para todos los workspaces existentes
"""
import sys
import os
import json
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.models.notification import NotificationTemplate, NotificationSetting
from app.models.workspace import Workspace
from app.database.session import get_db
from app.services.notification_service import format_notification_settings_response

# Templates en inglés (mismos que en update_notification_templates.py)
TICKET_CREATED_TEMPLATE = """
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; color: #333; line-height: 1.6; }
        .container { width: 100%; max-width: 600px; margin: 0 auto; }
        .header { background-color: #4154f1; padding: 20px; text-align: center; color: white; }
        .content { padding: 20px; }
        .footer { background-color: #f4f4f4; padding: 15px; text-align: center; font-size: 12px; color: #666; }
        a { color: #4154f1; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Ticket #{{ticket_id}} has been created</h2>
        </div>
        <div class="content">
            <p>Hello {{user_name}},</p>
            <p>We've received your ticket request <strong>"{{ticket_title}}"</strong> and it has been assigned ticket number <strong>#{{ticket_id}}</strong>.</p>
            <p>Our team will review your request and respond as soon as possible.</p>
            <p>Thank you for contacting us.</p>
            <p>Best regards,<br>The Support Team</p>
        </div>
        <div class="footer">
            This is an automated message. Please do not reply directly to this email.
        </div>
    </div>
</body>
</html>
"""

TICKET_RESOLVED_TEMPLATE = """
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; color: #333; line-height: 1.6; }
        .container { width: 100%; max-width: 600px; margin: 0 auto; }
        .header { background-color: #4caf50; padding: 20px; text-align: center; color: white; }
        .content { padding: 20px; }
        .footer { background-color: #f4f4f4; padding: 15px; text-align: center; font-size: 12px; color: #666; }
        a { color: #4154f1; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Ticket #{{ticket_id}} has been resolved</h2>
        </div>
        <div class="content">
            <p>Hello {{user_name}},</p>
            <p>We're pleased to inform you that your ticket <strong>"{{ticket_title}}"</strong> (ticket number <strong>#{{ticket_id}}</strong>) has been resolved.</p>
            <p>If you have any further questions or if you believe the issue has not been fully resolved, please feel free to contact us again.</p>
            <p>Thank you for your patience.</p>
            <p>Best regards,<br>The Support Team</p>
        </div>
        <div class="footer">
            This is an automated message. Please do not reply directly to this email.
        </div>
    </div>
</body>
</html>
"""

AGENT_RESPONSE_TEMPLATE = """
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; color: #333; line-height: 1.6; }
        .container { width: 100%; max-width: 600px; margin: 0 auto; }
        .header { background-color: #ff9800; padding: 20px; text-align: center; color: white; }
        .content { padding: 20px; }
        .footer { background-color: #f4f4f4; padding: 15px; text-align: center; font-size: 12px; color: #666; }
        a { color: #4154f1; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>New response to Ticket #{{ticket_id}}</h2>
        </div>
        <div class="content">
            <p>Hello {{user_name}},</p>
            <p>An agent has responded to your ticket <strong>"{{ticket_title}}"</strong> (ticket number <strong>#{{ticket_id}}</strong>).</p>
            <p>Please check your ticket for the complete response.</p>
            <p>Thank you for contacting us.</p>
            <p>Best regards,<br>The Support Team</p>
        </div>
        <div class="footer">
            This is an automated message. Please do not reply directly to this email.
        </div>
    </div>
</body>
</html>
"""

AGENT_ASSIGNED_TEMPLATE = """
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; color: #333; line-height: 1.6; }
        .container { width: 100%; max-width: 600px; margin: 0 auto; }
        .header { background-color: #2196f3; padding: 20px; text-align: center; color: white; }
        .content { padding: 20px; }
        .footer { background-color: #f4f4f4; padding: 15px; text-align: center; font-size: 12px; color: #666; }
        a { color: #4154f1; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Ticket #{{ticket_id}} has been assigned to you</h2>
        </div>
        <div class="content">
            <p>Hello {{agent_name}},</p>
            <p>Ticket <strong>"{{ticket_title}}"</strong> (ticket number <strong>#{{ticket_id}}</strong>) has been assigned to you.</p>
            <p>Please review the ticket and respond accordingly.</p>
            <p>Thank you,<br>Enque System</p>
        </div>
        <div class="footer">
            This is an automated message.
        </div>
    </div>
</body>
</html>
"""

def initialize_notifications():
    db = None
    try:
        # Crear conexión a la base de datos
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "database.db")
        if os.path.exists(db_path):
            print(f"Using SQLite database at {db_path}")
            engine = create_engine(f"sqlite:///{db_path}")
        else:
            print("SQLite database not found. Looking for database in environment.")
            from app.core.config import settings
            database_url = os.environ.get("DATABASE_URL") or settings.DATABASE_URI
            if not database_url:
                raise ValueError("No database URL found in environment or settings")
            print(f"Using database URL from environment")
            engine = create_engine(database_url)
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionLocal()
        
        # Obtener todos los workspaces
        workspaces = db.query(Workspace).all()
        print(f"Found {len(workspaces)} workspaces")
        
        for workspace in workspaces:
            print(f"Initializing notifications for workspace ID {workspace.id} - {workspace.name}")
            
            # 1. Crear plantillas de notificación si no existen
            templates = {}
            
            # Template: New Ticket Created (user)
            user_ticket_created = db.query(NotificationTemplate).filter(
                NotificationTemplate.workspace_id == workspace.id,
                NotificationTemplate.type == "new_ticket_created"
            ).first()
            
            if not user_ticket_created:
                user_ticket_created = NotificationTemplate(
                    workspace_id=workspace.id,
                    type="new_ticket_created",
                    name="New Ticket Created",
                    subject="New ticket #{{ticket_id}} created",
                    template=TICKET_CREATED_TEMPLATE,
                    is_enabled=True
                )
                db.add(user_ticket_created)
                db.flush()  # Para obtener el ID generado
                print(f"  - Created template: New Ticket Created")
            
            templates["user_ticket_created"] = user_ticket_created
            
            # Template: Ticket Resolved (user)
            user_ticket_resolved = db.query(NotificationTemplate).filter(
                NotificationTemplate.workspace_id == workspace.id,
                NotificationTemplate.type == "ticket_resolved"
            ).first()
            
            if not user_ticket_resolved:
                user_ticket_resolved = NotificationTemplate(
                    workspace_id=workspace.id,
                    type="ticket_resolved",
                    name="Ticket Resolved",
                    subject="Ticket #{{ticket_id}} has been resolved",
                    template=TICKET_RESOLVED_TEMPLATE,
                    is_enabled=True
                )
                db.add(user_ticket_resolved)
                db.flush()
                print(f"  - Created template: Ticket Resolved")
            
            templates["user_ticket_resolved"] = user_ticket_resolved
            
            # Template: New Agent Response (user)
            user_agent_response = db.query(NotificationTemplate).filter(
                NotificationTemplate.workspace_id == workspace.id,
                NotificationTemplate.type == "new_agent_response"
            ).first()
            
            if not user_agent_response:
                user_agent_response = NotificationTemplate(
                    workspace_id=workspace.id,
                    type="new_agent_response",
                    name="New Agent Response",
                    subject="New response to your ticket #{{ticket_id}}",
                    template=AGENT_RESPONSE_TEMPLATE,
                    is_enabled=True
                )
                db.add(user_agent_response)
                db.flush()
                print(f"  - Created template: New Agent Response")
            
            templates["user_agent_response"] = user_agent_response
            
            # Template: New Ticket Created (agent)
            agent_ticket_created = db.query(NotificationTemplate).filter(
                NotificationTemplate.workspace_id == workspace.id,
                NotificationTemplate.type == "agent_new_ticket"
            ).first()
            
            if not agent_ticket_created:
                agent_ticket_created = NotificationTemplate(
                    workspace_id=workspace.id,
                    type="agent_new_ticket",
                    name="New Ticket Created (Agent)",
                    subject="New ticket #{{ticket_id}} has been created",
                    template=TICKET_CREATED_TEMPLATE,
                    is_enabled=True
                )
                db.add(agent_ticket_created)
                db.flush()
                print(f"  - Created template: New Ticket Created (Agent)")
            
            templates["agent_ticket_created"] = agent_ticket_created
            
            # Template: Ticket Assigned (agent)
            agent_ticket_assigned = db.query(NotificationTemplate).filter(
                NotificationTemplate.workspace_id == workspace.id,
                NotificationTemplate.type == "ticket_assigned"
            ).first()
            
            if not agent_ticket_assigned:
                agent_ticket_assigned = NotificationTemplate(
                    workspace_id=workspace.id,
                    type="ticket_assigned",
                    name="Ticket Assigned",
                    subject="Ticket #{{ticket_id}} has been assigned to you",
                    template=AGENT_ASSIGNED_TEMPLATE,
                    is_enabled=True
                )
                db.add(agent_ticket_assigned)
                db.flush()
                print(f"  - Created template: Ticket Assigned")
            
            templates["agent_ticket_assigned"] = agent_ticket_assigned
            
            # Template: New Response (agent)
            agent_new_response = db.query(NotificationTemplate).filter(
                NotificationTemplate.workspace_id == workspace.id,
                NotificationTemplate.type == "agent_new_response"
            ).first()
            
            if not agent_new_response:
                agent_new_response = NotificationTemplate(
                    workspace_id=workspace.id,
                    type="agent_new_response",
                    name="New Response (Agent)",
                    subject="New response to ticket #{{ticket_id}}",
                    template=AGENT_RESPONSE_TEMPLATE,
                    is_enabled=True
                )
                db.add(agent_new_response)
                db.flush()
                print(f"  - Created template: New Response (Agent)")
            
            templates["agent_new_response"] = agent_new_response
            
            # 2. Crear configuraciones de notificación
            # Para usuarios
            user_settings = [
                # Nuevo ticket creado
                {
                    "category": "users",
                    "type": "new_ticket_created",
                    "is_enabled": True,
                    "channels": json.dumps({"email": {"enabled": True}}),
                    "template_id": templates["user_ticket_created"].id
                },
                # Ticket resuelto
                {
                    "category": "users",
                    "type": "ticket_resolved",
                    "is_enabled": True,
                    "channels": json.dumps({"email": {"enabled": True}}),
                    "template_id": templates["user_ticket_resolved"].id
                },
                # Nueva respuesta de agente
                {
                    "category": "users",
                    "type": "new_agent_response",
                    "is_enabled": True,
                    "channels": json.dumps({"email": {"enabled": True}}),
                    "template_id": templates["user_agent_response"].id
                }
            ]
            
            # Para agentes
            agent_settings = [
                # Nuevo ticket creado (email)
                {
                    "category": "agents",
                    "type": "new_ticket_created",
                    "is_enabled": True,
                    "channels": json.dumps({"email": {"enabled": True}}),
                    "template_id": templates["agent_ticket_created"].id
                },
                # Ticket asignado (email)
                {
                    "category": "agents",
                    "type": "ticket_assigned",
                    "is_enabled": True,
                    "channels": json.dumps({"email": {"enabled": True}}),
                    "template_id": templates["agent_ticket_assigned"].id
                },
                # Nueva respuesta (email)
                {
                    "category": "agents",
                    "type": "new_response",
                    "is_enabled": True,
                    "channels": json.dumps({"email": {"enabled": True}}),
                    "template_id": templates["agent_new_response"].id
                },
                # Nuevo ticket creado (popup)
                {
                    "category": "agents",
                    "type": "new_ticket_created",
                    "is_enabled": True,
                    "channels": json.dumps({"enque_popup": {"enabled": True}}),
                    "template_id": None
                },
                # Ticket asignado (popup)
                {
                    "category": "agents",
                    "type": "ticket_assigned",
                    "is_enabled": True,
                    "channels": json.dumps({"enque_popup": {"enabled": True}}),
                    "template_id": None
                },
                # Nueva respuesta (popup)
                {
                    "category": "agents",
                    "type": "new_response",
                    "is_enabled": True,
                    "channels": json.dumps({"enque_popup": {"enabled": True}}),
                    "template_id": None
                },
                # Teams (no conectado por defecto)
                {
                    "category": "agents",
                    "type": "teams",
                    "is_enabled": False,
                    "channels": json.dumps({"teams": {"enabled": False}}),
                    "template_id": None
                }
            ]
            
            # Crear settings para usuarios
            for setting_data in user_settings:
                # Verificar si ya existe
                existing = db.query(NotificationSetting).filter(
                    NotificationSetting.workspace_id == workspace.id,
                    NotificationSetting.category == setting_data["category"],
                    NotificationSetting.type == setting_data["type"]
                ).first()
                
                if not existing:
                    setting = NotificationSetting(
                        workspace_id=workspace.id,
                        category=setting_data["category"],
                        type=setting_data["type"],
                        is_enabled=setting_data["is_enabled"],
                        channels=setting_data["channels"],
                        template_id=setting_data["template_id"]
                    )
                    db.add(setting)
                    print(f"  - Created user setting: {setting_data['type']}")
            
            # Crear settings para agentes
            for setting_data in agent_settings:
                # Verificar si ya existe
                existing = db.query(NotificationSetting).filter(
                    NotificationSetting.workspace_id == workspace.id,
                    NotificationSetting.category == setting_data["category"],
                    NotificationSetting.type == setting_data["type"],
                    NotificationSetting.channels.contains(setting_data["channels"])
                ).first()
                
                if not existing:
                    setting = NotificationSetting(
                        workspace_id=workspace.id,
                        category=setting_data["category"],
                        type=setting_data["type"],
                        is_enabled=setting_data["is_enabled"],
                        channels=setting_data["channels"],
                        template_id=setting_data["template_id"]
                    )
                    db.add(setting)
                    print(f"  - Created agent setting: {setting_data['type']} with channels {setting_data['channels']}")
            
        # Guardar cambios
        db.commit()
        print("All notification settings initialized successfully!")
        
        # Verificar configuraciones
        for workspace in workspaces:
            settings_response = format_notification_settings_response(db, workspace.id)
            print(f"Verification for workspace {workspace.id}:")
            print(f"  - Found {len(db.query(NotificationSetting).filter(NotificationSetting.workspace_id == workspace.id).all())} notification settings")
            print(f"  - Found {len(db.query(NotificationTemplate).filter(NotificationTemplate.workspace_id == workspace.id).all())} notification templates")
        
    except Exception as e:
        print(f"Error initializing notification settings: {str(e)}")
        import traceback
        traceback.print_exc()
        if db:
            db.rollback()
    finally:
        if db:
            db.close()

if __name__ == "__main__":
    initialize_notifications() 