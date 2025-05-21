"""
Script para actualizar las plantillas de notificación a inglés
"""
import sys
import os
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.notification import NotificationTemplate
from app.database.session import get_db

# Templates en inglés
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

def update_notification_templates():
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
        
        # Obtener todas las plantillas
        templates = db.query(NotificationTemplate).all()
        print(f"Found {len(templates)} notification templates")
        
        # Actualizar cada plantilla según su tipo
        for template in templates:
            if template.type == "new_ticket_created":
                template.name = "New Ticket Created"
                template.subject = "New ticket #{{ticket_id}} created"
                template.template = TICKET_CREATED_TEMPLATE
                print(f"Updated template ID {template.id} - {template.name}")
            
            elif template.type == "ticket_resolved":
                template.name = "Ticket Resolved"
                template.subject = "Ticket #{{ticket_id}} has been resolved"
                template.template = TICKET_RESOLVED_TEMPLATE
                print(f"Updated template ID {template.id} - {template.name}")
            
            elif template.type == "new_agent_response":
                template.name = "New Agent Response"
                template.subject = "New response to your ticket #{{ticket_id}}"
                template.template = AGENT_RESPONSE_TEMPLATE
                print(f"Updated template ID {template.id} - {template.name}")
            
            elif template.type == "ticket_assigned":
                template.name = "Ticket Assigned"
                template.subject = "Ticket #{{ticket_id}} has been assigned to you"
                template.template = AGENT_ASSIGNED_TEMPLATE
                print(f"Updated template ID {template.id} - {template.name}")
        
        # Guardar cambios
        db.commit()
        print("All templates updated successfully!")
        
    except Exception as e:
        print(f"Error updating templates: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if db:
            db.close()

if __name__ == "__main__":
    update_notification_templates() 