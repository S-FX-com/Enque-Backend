import re
from app.core.config import settings
from app.services.microsoft_service import MicrosoftGraphService # Assuming this service can send mail
from app.utils.logger import logger
from sqlalchemy.orm import Session # MicrosoftGraphService might need a DB session
from typing import Optional, Tuple, List, Dict, Any
from app.models.agent import Agent
from datetime import datetime

# Placeholder for a more sophisticated HTML email template system
def create_invitation_email_html(agent_name: str, invitation_link: str, logo_url: str, workspace_name: str) -> str:
    """
    Generates an HTML content for the invitation email.
    """
    # Basic inline CSS for styling
    # Ensure colors have good contrast for accessibility.
    # Using a simple table layout for centering and card-like effect.
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Enque Invitation</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
                margin: 0;
                padding: 20px;
                background-color: #f4f4f7;
                color: #333;
            }}
            .container {{
                background-color: #ffffff;
                max-width: 600px;
                margin: 20px auto;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                text-align: left;
            }}
            .logo-container {{
                text-align: center;
                margin-bottom: 25px;
            }}
            .logo-container img {{
                max-width: 150px; /* Adjust as needed */
                height: auto;
            }}
            p {{
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 1em;
            }}
            a.button {{
                display: inline-block;
                background-color: #007bff; /* Enque primary color - adjust if different */
                color: #ffffff;
                padding: 12px 25px;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
                margin-top: 10px;
                margin-bottom: 20px;
            }}
            .footer {{
                font-size: 14px;
                color: #777;
                margin-top: 25px;
            }}
            .link-text {{
                 word-break: break-all; /* Ensure long links don't break layout */
            }}
            .workspace-info {{
                background-color: #f8f9fa;
                border-left: 4px solid #007bff;
                padding: 15px;
                margin: 15px 0;
                border-radius: 4px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo-container">
                <img src="{logo_url}" alt="Enque Logo">
            </div>
            <p>Hello {agent_name},</p>
            <p>You have been invited to join <strong>{workspace_name}</strong> on Enque. Please click the button below to set up your account and create your password:</p>

            <div class="workspace-info">
                <p style="margin: 0;"><strong>Workspace:</strong> {workspace_name}</p>
            </div>

            <p style="text-align: center;">
                <a href="{invitation_link}" class="button">Accept Invitation & Set Password</a>
            </p>
            <p>This link will expire in {settings.AGENT_INVITATION_TOKEN_EXPIRE_HOURS} hours.</p>
            <p>If you did not expect this invitation, you can ignore this email.</p>
            <p class="footer">
                Best regards,<br>
                The Enque Team
            </p>
            <p class="footer link-text" style="font-size: 12px; color: #999;">
                If the button above does not work, copy and paste this link into your browser: <a href="{invitation_link}">{invitation_link}</a>
            </p>
        </div>
    </body>
    </html>
    """
    return html_content

async def send_agent_invitation_email(
    db: Session,
    to_email: str,
    agent_name: str,
    invitation_link: str,
    sender_mailbox_email: str, # Email of the mailbox to send from (e.g., admin's connected mailbox)
    user_access_token: str,    # Valid access token for the sender_mailbox_email
    workspace_name: str        # Name of the workspace the agent is being invited to
) -> bool:
    """
    Sends an invitation email to a new agent using a user's delegated token.
    """
    subject = f"You're invited to join {workspace_name} on Enque!"
    # You need to provide a public URL for your logo.
    # For example, if you host it on your frontend's public folder and it's accessible via app.enque.cc/enque.png
    # Or better, a CDN or dedicated image hosting.
    # Replace "YOUR_PUBLIC_LOGO_URL_HERE" with the actual URL.
    # If your frontend is at app.enque.cc and enque.png is in its public root, then:
    # logo_url = f"{settings.FRONTEND_URL}/enque.png"
    # However, ensure this is truly public and doesn't require auth.
    # For now, using a placeholder. You MUST update this.
    logo_url = "https://app.enque.cc/enque.png" # Example: Replace with your actual public logo URL

    html_content = create_invitation_email_html(agent_name, invitation_link, logo_url, workspace_name)

    try:
        graph_service = MicrosoftGraphService(db=db)

        success = await graph_service.send_email_with_user_token(
            user_access_token=user_access_token,
            sender_mailbox_email=sender_mailbox_email,
            recipient_email=to_email,
            subject=subject,
            html_body=html_content
        )
        if success:
            logger.info(f"Invitation email sent successfully to {to_email} from {sender_mailbox_email}")
            return True
        else:
            logger.error(f"Failed to send invitation email to {to_email} using MicrosoftGraphService.send_email_with_user_token from {sender_mailbox_email}")
            return False
    except Exception as e:
        logger.error(f"Exception in send_agent_invitation_email for {to_email}: {e}", exc_info=True)
        return False

def create_password_reset_email_html(agent_name: str, reset_link: str) -> str:
    """
    Generates an HTML content for the password reset email.
    """
    # Using a similar style to the invitation email
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Enque Password Reset</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
                margin: 0;
                padding: 20px;
                background-color: #f4f4f7;
                color: #333;
            }}
            .container {{
                background-color: #ffffff;
                max-width: 600px;
                margin: 20px auto;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                text-align: left;
            }}
            .logo-container {{
                text-align: center;
                margin-bottom: 25px;
            }}
            .logo-container img {{
                max-width: 150px; /* Adjust as needed */
                height: auto;
            }}
            p {{
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 1em;
            }}
            a.button {{
                display: inline-block;
                background-color: #007bff; /* Enque primary color - adjust if different */
                color: #ffffff;
                padding: 12px 25px;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
                margin-top: 10px;
                margin-bottom: 20px;
            }}
            .footer {{
                font-size: 14px;
                color: #777;
                margin-top: 25px;
            }}
            .link-text {{
                 word-break: break-all; /* Ensure long links don't break layout */
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo-container">
                <img src="{settings.FRONTEND_URL}/enque.png" alt="Enque Logo">
            </div>
            <p>Hello {agent_name},</p>
            <p>We received a request to reset your password for your Enque account. Please click the button below to set a new password:</p>
            <p style="text-align: center;">
                <a href="{reset_link}" class="button">Reset Your Password</a>
            </p>
            <p>This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS} hours.</p>
            <p>If you did not request a password reset, please ignore this email or contact support if you have concerns.</p>
            <p class="footer">
                Best regards,<br>
                The Enque Team
            </p>
            <p class="footer link-text" style="font-size: 12px; color: #999;">
                If the button above does not work, copy and paste this link into your browser: <a href="{reset_link}">{reset_link}</a>
            </p>
        </div>
    </body>
    </html>
    """
    return html_content

async def send_password_reset_email( # Changed to async
    db: Session,
    to_email: str,
    agent_name: str,
    reset_link: str,
    sender_mailbox_email: str, # Email of the admin's mailbox to send from
    user_access_token: str    # Valid access token for the sender_mailbox_email
) -> bool:
    """
    Sends a password reset email to an agent using a delegated user token (admin's).
    """
    subject = "Reset Your Enque Password"
    logo_url = f"{settings.FRONTEND_URL}/enque.png" # Consistent with invitation email
    # The create_password_reset_email_html function was already updated to use settings.FRONTEND_URL directly for the logo.
    # If we wanted to pass logo_url as a parameter to create_password_reset_email_html,
    # its signature would need to change, and then we'd pass logo_url here.
    # For now, it's consistent as create_password_reset_email_html directly uses settings.FRONTEND_URL + /enque.png
    html_content = create_password_reset_email_html(agent_name, reset_link)

    try:
        graph_service = MicrosoftGraphService(db=db)

        success = await graph_service.send_email_with_user_token(
            user_access_token=user_access_token,
            sender_mailbox_email=sender_mailbox_email,
            recipient_email=to_email,
            subject=subject,
            html_body=html_content
        )

        if success:
            logger.info(f"Password reset email sent successfully to {to_email} from {sender_mailbox_email}")
            return True
        else:
            logger.error(f"Failed to send password reset email to {to_email} from {sender_mailbox_email}")
            return False
    except Exception as e:
        logger.error(f"Exception in send_password_reset_email for {to_email} from {sender_mailbox_email}: {e}", exc_info=True)
        return False

def create_ticket_assignment_email_html(agent_name: str, ticket_id: int, ticket_title: str, ticket_link: str, sender_name: Optional[str] = None) -> str:
    """
    Generates an HTML content for the ticket assignment notification email.
    """
    # Determinar el nombre del remitente para la despedida
    if sender_name:
        footer_sender = f"The {sender_name} Team"
    else:
        footer_sender = "The Enque Team"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>New Ticket Assigned</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
                margin: 0;
                padding: 20px;
                background-color: #f4f4f7;
                color: #333;
            }}
            .container {{
                background-color: #ffffff;
                max-width: 600px;
                margin: 20px auto;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                text-align: left;
            }}

            p {{
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 1em;
            }}
            a.button {{
                display: inline-block;
                background-color: #007bff;
                color: #ffffff;
                padding: 12px 25px;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
                margin-top: 10px;
                margin-bottom: 20px;
            }}
            .footer {{
                font-size: 14px;
                color: #777;
                margin-top: 25px;
            }}
            .ticket-info {{
                background-color: #f8f9fa;
                border-left: 4px solid #007bff;
                padding: 15px;
                margin: 15px 0;
                border-radius: 4px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <p>Hello {agent_name},</p>
            <p>You have been assigned a new ticket in Enque:</p>

            <div class="ticket-info">
                <p><strong>Ticket ID:</strong> {ticket_id}</p>
                <p><strong>Subject:</strong> {ticket_title}</p>
            </div>

            <p style="text-align: center;">
                <a href="{ticket_link}" class="button">View Ticket</a>
            </p>

            <p class="footer">
                Best regards,<br>
                {footer_sender}
            </p>
        </div>
    </body>
    </html>
    """
    return html_content

async def send_ticket_assignment_email(
    db: Session,
    to_email: str,
    agent_name: str,
    ticket_id: int,
    ticket_title: str,
    sender_mailbox_email: str,
    user_access_token: str,
    request_origin: Optional[str] = None,
    sender_mailbox_display_name: Optional[str] = None
) -> bool:
    """
    Sends a notification email to an agent when a ticket is assigned to them.
    Uses the sender_mailbox_display_name to personalize the email signature.
    """
    subject = f"[ID:{ticket_id}] New ticket assigned: {ticket_title}"

    # Use the origin URL if provided, otherwise fallback to settings.FRONTEND_URL
    base_url = request_origin if request_origin else settings.FRONTEND_URL
    #ticket_link = f"{base_url}/tickets?openTicket={ticket_id}"
    ticket_link = f"{base_url}/tickets/{ticket_id}"

    html_content = create_ticket_assignment_email_html(
        agent_name,
        ticket_id,
        ticket_title,
        ticket_link,
        sender_mailbox_display_name
    )

    try:
        graph_service = MicrosoftGraphService(db=db)

        success = await graph_service.send_email_with_user_token(
            user_access_token=user_access_token,
            sender_mailbox_email=sender_mailbox_email,
            recipient_email=to_email,
            subject=subject,
            html_body=html_content,
            task_id=ticket_id
        )
        if success:
            logger.info(f"Ticket assignment email sent successfully to {to_email} from {sender_mailbox_email} ({sender_mailbox_display_name or 'No display name'})")
            return True
        else:
            logger.error(f"Failed to send ticket assignment email to {to_email} using MicrosoftGraphService.send_email_with_user_token from {sender_mailbox_email}")
            return False
    except Exception as e:
        logger.error(f"Exception in send_ticket_assignment_email for {to_email}: {e}", exc_info=True)
        return False

def create_team_ticket_notification_email_html(agent_name: str, team_name: str, ticket_id: int, ticket_title: str, ticket_link: str, sender_name: Optional[str] = None) -> str:
    """
    Generates an HTML content for the team ticket notification email.
    """
    # Determinar el nombre del remitente para la despedida
    if sender_name:
        footer_sender = f"The {sender_name} Team"
    else:
        footer_sender = "The Enque Team"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>New Team Ticket</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
                margin: 0;
                padding: 20px;
                background-color: #f4f4f7;
                color: #333;
            }}
            .container {{
                background-color: #ffffff;
                max-width: 600px;
                margin: 20px auto;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                text-align: left;
            }}

            p {{
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 1em;
            }}
            a.button {{
                display: inline-block;
                background-color: #007bff;
                color: #ffffff;
                padding: 12px 25px;
                text-decoration: none;
                border-radius: 5px;
                font-weight: bold;
                margin-top: 10px;
                margin-bottom: 20px;
            }}
            .footer {{
                font-size: 14px;
                color: #777;
                margin-top: 25px;
            }}
            .ticket-info {{
                background-color: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
                border-left: 4px solid #007bff;
            }}
            .team-badge {{
                background-color: #e3f2fd;
                color: #1976d2;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                display: inline-block;
                margin-bottom: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2 style="color: #333; margin-bottom: 20px;">New Ticket for Your Team</h2>
            
            <p>Hi {agent_name},</p>
            
            <p>A new ticket has been created and assigned to your team <strong>{team_name}</strong>. This ticket doesn't have a specific agent assigned yet, so any team member can take it.</p>
            
            <div class="ticket-info">
                <div class="team-badge">Team: {team_name}</div>
                <p style="margin: 0 0 10px 0;"><strong>Ticket ID:</strong> #{ticket_id}</p>
                <p style="margin: 0;"><strong>Title:</strong> {ticket_title}</p>
            </div>
            
            <p>You can view and claim this ticket by clicking the button below:</p>
            
            <a href="{ticket_link}" class="button">View Ticket</a>
            
            <p>If you decide to work on this ticket, you can assign it to yourself from the ticket page.</p>
            
            <div class="footer">
                <p>Best regards,<br>{footer_sender}</p>
                <p style="font-size: 12px; color: #999;">This is an automated notification. Please do not reply to this email.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content


async def send_team_ticket_notification_email(
    db: Session,
    to_email: str,
    agent_name: str,
    team_name: str,
    ticket_id: int,
    ticket_title: str,
    sender_mailbox_email: str,
    user_access_token: str,
    request_origin: Optional[str] = None,
    sender_mailbox_display_name: Optional[str] = None
) -> bool:
    """
    Sends a notification email to a team member when a new ticket is assigned to their team.
    """
    subject = f"[ID:{ticket_id}] New ticket for team {team_name}: {ticket_title}"

    # Use the origin URL if provided, otherwise fallback to settings.FRONTEND_URL
    base_url = request_origin if request_origin else settings.FRONTEND_URL
    ticket_link = f"{base_url}/tickets/{ticket_id}"

    html_content = create_team_ticket_notification_email_html(
        agent_name,
        team_name,
        ticket_id,
        ticket_title,
        ticket_link,
        sender_mailbox_display_name
    )

    try:
        graph_service = MicrosoftGraphService(db=db)

        success = await graph_service.send_email_with_user_token(
            user_access_token=user_access_token,
            sender_mailbox_email=sender_mailbox_email,
            recipient_email=to_email,
            subject=subject,
            html_body=html_content,
            task_id=ticket_id
        )
        if success:
            logger.info(f"Team ticket notification email sent successfully to {to_email} from {sender_mailbox_email} ({sender_mailbox_display_name or 'No display name'})")
            return True
        else:
            logger.error(f"Failed to send team ticket notification email to {to_email} using MicrosoftGraphService.send_email_with_user_token from {sender_mailbox_email}")
            return False
    except Exception as e:
        logger.error(f"Exception in send_team_ticket_notification_email for {to_email}: {e}", exc_info=True)
        return False

def validate_email_addresses(email_string: str) -> Tuple[bool, List[str]]:
    """
    Validate a comma-separated string of email addresses.

    Args:
        email_string: String containing comma-separated email addresses

    Returns:
        Tuple of (is_valid, list_of_emails)
    """
    if not email_string or not email_string.strip():
        return True, []

    # Split by comma and clean up
    emails = [email.strip() for email in email_string.split(',') if email.strip()]

    # Email regex pattern
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    valid_emails = []
    for email in emails:
        if re.match(email_pattern, email):
            valid_emails.append(email)
        else:
            logger.warning(f"Invalid email address found: {email}")
            return False, []

    return True, valid_emails

def parse_other_destinaries(other_destinaries: Optional[str]) -> List[str]:
    """
    Parse and validate the other_destinaries field.

    Args:
        other_destinaries: Comma-separated string of email addresses

    Returns:
        List of valid email addresses
    """
    if not other_destinaries:
        return []

    is_valid, emails = validate_email_addresses(other_destinaries)
    if not is_valid:
        raise ValueError("Invalid email addresses in other_destinaries field")

    return emails


def extract_mentions_from_html(html_content: str) -> List[str]:
    import re
    from html import unescape
    
    if not html_content:
        return []
    
    # Múltiples patrones para diferentes formatos de TipTap
    patterns = [
        # Formato estándar de TipTap con data-type="mention" y data-id
        r'<span[^>]*data-type="mention"[^>]*data-id="([^"]+)"[^>]*>.*?</span>',
        # Formato con class="mention" y data-id
        r'<span[^>]*class="mention"[^>]*data-id="([^"]+)"[^>]*>.*?</span>',
        # Formato con data-mention
        r'<span[^>]*data-mention="([^"]+)"[^>]*>.*?</span>',
        # Formato con data-id sin class específica
        r'<span[^>]*data-id="([^"]+)"[^>]*data-type="mention"[^>]*>.*?</span>',
        # Formato más flexible con mention en cualquier atributo
        r'<span[^>]*mention[^>]*data-id="([^"]+)"[^>]*>.*?</span>',
    ]
    
    all_mentions = []
    
    for pattern in patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
        if matches:
            all_mentions.extend(matches)
    
    # Limpiar y deduplicar menciones
    clean_mentions = []
    for mention in all_mentions:
        clean_mention = unescape(mention.strip())
        if clean_mention and clean_mention not in clean_mentions:
            clean_mentions.append(clean_mention)
    
    if clean_mentions:
        logger.info(f"Menciones extraídas: {clean_mentions}")
    
    return clean_mentions


def create_mention_notification_email_html(
    mentioned_agent_name: str, 
    mentioning_agent_name: str,
    ticket_id: int, 
    ticket_title: str, 
    ticket_link: str,
    note_content: str,
    sender_name: Optional[str] = None
) -> str:
    if sender_name:
        footer_sender = f"The {sender_name} Team"
    else:
        footer_sender = "The Enque Team"
    max_content_length = 200
    if len(note_content) > max_content_length:
        truncated_content = note_content[:max_content_length] + "..."
    else:
        truncated_content = note_content

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>You've been mentioned in a private note</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
                margin: 0;
                padding: 20px;
                background-color: #f4f4f7;
                color: #333;
            }}
            .container {{
                background-color: #ffffff;
                max-width: 600px;
                margin: 20px auto;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                text-align: left;
            }}

            p {{
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 1em;
            }}
            a.button {{
                display: inline-block;
                background-color: #007bff;
                color: #ffffff;
                padding: 12px 25px;
                text-decoration: none;
                border-radius: 5px;
                margin-top: 20px;
                font-weight: 500;
            }}
            a.button:hover {{
                background-color: #0056b3;
            }}
            .mention-badge {{
                background-color: #e3f2fd;
                color: #1976d2;
                padding: 2px 8px;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 500;
                border: 1px solid #bbdefb;
            }}
            .note-preview {{
                background-color: #f8f9fa;
                border-left: 4px solid #007bff;
                padding: 15px;
                margin: 20px 0;
                border-radius: 4px;
                font-style: italic;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <p>Hello {mentioned_agent_name},</p>

            <p>You have been mentioned in a private note by <strong>{mentioning_agent_name}</strong> on the following ticket:</p>

            <p><strong>Ticket ID:</strong> {ticket_id}</p>
            <p><strong>Subject:</strong> {ticket_title}</p>

            <div class="note-preview">
                <strong>Private Note Preview:</strong><br>
                {truncated_content}
            </div>

            <a href="{ticket_link}" class="button">View Ticket</a>

            <p style="margin-top: 30px;">Best regards,<br>{footer_sender}</p>
        </div>
    </body>
    </html>
    """
    
    return html_content


async def send_mention_notification_email(
    db: Session,
    mentioned_agent_email: str,
    mentioned_agent_name: str,
    mentioning_agent_name: str,
    ticket_id: int,
    ticket_title: str,
    note_content: str,
    sender_mailbox_email: str,
    sender_mailbox_display_name: Optional[str],
    user_access_token: str,
    request_origin: Optional[str] = None
) -> bool:
   
    subject = f"[ID:{ticket_id}] You've been mentioned in a private note: {ticket_title}"

    base_url = request_origin if request_origin else settings.FRONTEND_URL
    ticket_link = f"{base_url}/tickets/{ticket_id}"

    html_content = create_mention_notification_email_html(
        mentioned_agent_name=mentioned_agent_name,
        mentioning_agent_name=mentioning_agent_name,
        ticket_id=ticket_id,
        ticket_title=ticket_title,
        ticket_link=ticket_link,
        note_content=note_content,
        sender_name=sender_mailbox_display_name
    )

    try:
        graph_service = MicrosoftGraphService(db=db)

        success = await graph_service.send_email_with_user_token(
            user_access_token=user_access_token,
            sender_mailbox_email=sender_mailbox_email,
            recipient_email=mentioned_agent_email,
            subject=subject,
            html_body=html_content,
            task_id=ticket_id
        )
        
        if success:
            logger.info(f"Mention notification email sent successfully to {mentioned_agent_email} from {sender_mailbox_email} ({sender_mailbox_display_name or 'No display name'})")
            return True
        else:
            logger.error(f"Failed to send mention notification email to {mentioned_agent_email} using MicrosoftGraphService.send_email_with_user_token from {sender_mailbox_email}")
            return False
    except Exception as e:
        logger.error(f"Exception in send_mention_notification_email for {mentioned_agent_email}: {e}", exc_info=True)
        return False


async def process_mention_notifications(
    db: Session,
    comment_content: str,
    workspace_id: int,
    ticket_id: int,
    ticket_title: str,
    mentioning_agent_id: int,
    request_origin: Optional[str] = None
) -> List[str]:
    if not comment_content:
        return []
    
    mentioned_names = extract_mentions_from_html(comment_content)
    
    if not mentioned_names:
        return []
    
    notified_agents = []
    
    from app.models.task import Task
    from app.models.microsoft import MailboxConnection, MicrosoftToken
    
    task = db.query(Task).filter(Task.id == ticket_id).first()
    preferred_mailbox = None
    
    if task and task.mailbox_connection_id:
        logger.info(f"Ticket {ticket_id} tiene mailbox específico ID: {task.mailbox_connection_id}")
        
        mailbox_token_info = db.query(MailboxConnection, MicrosoftToken)\
            .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
            .filter(
                MailboxConnection.id == task.mailbox_connection_id,
                MailboxConnection.is_active == True
            ).first()
        
        if mailbox_token_info:
            preferred_mailbox = {
                'connection': mailbox_token_info[0],
                'token': mailbox_token_info[1]
            }
        else:
            logger.warning(f"No se encontró token válido para el mailbox específico del ticket {ticket_id}")
    
    if not preferred_mailbox:
        logger.info(f"Buscando mailbox activo para workspace {workspace_id}")
        
        mailbox_info = db.query(MailboxConnection, MicrosoftToken)\
            .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
            .filter(
                MailboxConnection.workspace_id == workspace_id,
                MailboxConnection.is_active == True
            ).first()
        
        if mailbox_info:
            preferred_mailbox = {
                'connection': mailbox_info[0],
                'token': mailbox_info[1]
            }
        else:
            logger.error(f"No se encontró ningún mailbox activo para workspace {workspace_id}")
            return []
    
    from datetime import datetime
    
    token = preferred_mailbox['token']
    if token.expires_at <= datetime.utcnow():
        try:
            from app.services.microsoft_service import MicrosoftGraphService
            ms_service = MicrosoftGraphService(db)
            await ms_service.refresh_token_async(token)
            db.refresh(token)
        except Exception as e:
            logger.error(f"Error refreshing token for mention notifications: {str(e)}")
            return []
    
    for mentioned_name in mentioned_names:
        try:
            mentioned_agent = db.query(Agent).filter(
                Agent.name == mentioned_name,
                Agent.workspace_id == workspace_id,
                Agent.is_active == True
            ).first()
            
            if not mentioned_agent:
                logger.warning(f"Agent '{mentioned_name}' no encontrado en workspace {workspace_id}")
                continue
            
            if mentioned_agent.id == mentioning_agent_id:
                logger.info(f"Skipping self-mention for agent {mentioned_name}")
                continue
            
            import re
            clean_content = re.sub(r'<[^>]+>', '', comment_content)
            clean_content = re.sub(r'\s+', ' ', clean_content).strip()
            
            mentioning_agent = db.query(Agent).filter(Agent.id == mentioning_agent_id).first()
            mentioning_agent_name = mentioning_agent.name if mentioning_agent else "Unknown Agent"
            
            success = await send_mention_notification_email(
                db=db,
                mentioned_agent_email=mentioned_agent.email,
                mentioned_agent_name=mentioned_agent.name,
                mentioning_agent_name=mentioning_agent_name,
                ticket_id=ticket_id,
                ticket_title=ticket_title,
                note_content=clean_content,
                sender_mailbox_email=preferred_mailbox['connection'].email,
                sender_mailbox_display_name=preferred_mailbox['connection'].display_name,
                user_access_token=token.access_token,
                request_origin=request_origin
            )
            
            if success:
                notified_agents.append(mentioned_agent.name)
                logger.info(f"✅ Mention notification sent to {mentioned_agent.email}")
            else:
                logger.error(f"❌ Failed to send mention notification to {mentioned_agent.email}")
                
        except Exception as e:
            logger.error(f"Error processing mention for '{mentioned_name}': {str(e)}")
            continue
    
    return notified_agents


def get_agent_closed_tickets_last_week(db: Session, agent_id: int) -> List[Dict[str, Any]]:

    from datetime import datetime, timedelta
    from app.models.task import Task
    today = datetime.now().date()
    days_since_monday = today.weekday()  # 0 = Monday, 6 = Sunday
    
    last_sunday = today - timedelta(days=days_since_monday + 7 - 6)
    last_monday = last_sunday - timedelta(days=6)
    
    start_date = datetime.combine(last_monday, datetime.min.time())
    end_date = datetime.combine(last_sunday, datetime.max.time())
    
    tickets = db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.status == 'Closed',
        Task.updated_at >= start_date,
        Task.updated_at <= end_date,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).all()
    
    result = []
    for ticket in tickets:
        result.append({
            'id': ticket.id,
            'title': ticket.title,
            'created_at': ticket.created_at,
            'updated_at': ticket.updated_at,
            'status': ticket.status
        })
    
    return result


def create_weekly_summary_email_html(
    agent_name: str,
    tickets: List[Dict[str, Any]],
    week_start: datetime,
    week_end: datetime,
    sender_name: Optional[str] = None
) -> str:
    """
    Genera HTML para el email de resumen semanal de agente.
    """
    if sender_name:
        footer_sender = f"The {sender_name} Team"
    else:
        footer_sender = "The Enque Team"
    
    week_range = f"{week_start.strftime('%B %d')} - {week_end.strftime('%B %d, %Y')}"
    
    tickets_html = ""
    if tickets:
        for ticket in tickets:
            created_date = ticket['created_at'].strftime('%m/%d/%Y')
            closed_date = ticket['updated_at'].strftime('%m/%d/%Y')
            
            tickets_html += f"""
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 12px 8px; text-align: left; font-size: 14px; color: #374151;">
                    {created_date}
                </td>
                <td style="padding: 12px 8px; text-align: left; font-size: 14px; color: #374151;">
                    {closed_date}
                </td>
                <td style="padding: 12px 8px; text-align: left; font-size: 14px; color: #1f2937;">
                    <strong>#{ticket['id']}</strong> - {ticket['title']}
                </td>
            </tr>
            """
    else:
        tickets_html = """
        <tr>
            <td colspan="3" style="padding: 20px; text-align: center; font-size: 14px; color: #6b7280; font-style: italic;">
                No tickets were closed this week.
            </td>
        </tr>
        """
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Weekly Summary</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background-color: #f8fafc;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white !important; padding: 30px; text-align: center;">
                <h1 style="margin: 0; font-size: 28px; font-weight: 600; color: white !important;">🎟️ Weekly Summary</h1>
                <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9; color: white !important;">
                    {agent_name} • {week_range}
                </p>
            </div>
            
            <!-- Content -->
            <div style="padding: 30px;">
                <p style="font-size: 16px; color: #374151; margin-bottom: 25px;">
                    Hello {agent_name},
                </p>
                
                <p style="font-size: 16px; color: #374151; margin-bottom: 25px;">
                    The following tickets that were assigned to you have been marked as closed or resolved over the last 7 days.
                </p>
                
                <!-- Tickets Table -->
                <table style="width: 100%; border-collapse: collapse; margin: 25px 0; background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden;">
                    <thead>
                        <tr style="background-color: #f9fafb;">
                            <th style="padding: 15px 8px; text-align: left; font-weight: 600; font-size: 14px; color: #374151; border-bottom: 2px solid #e5e7eb;">
                                Ticket Created
                            </th>
                            <th style="padding: 15px 8px; text-align: left; font-weight: 600; font-size: 14px; color: #374151; border-bottom: 2px solid #e5e7eb;">
                                Marked Closed
                            </th>
                            <th style="padding: 15px 8px; text-align: left; font-weight: 600; font-size: 14px; color: #374151; border-bottom: 2px solid #e5e7eb;">
                                Ticket Name
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {tickets_html}
                    </tbody>
                </table>
                
                <div style="margin-top: 30px; padding: 20px; background-color: #f8fafc; border-radius: 8px; border-left: 4px solid #667eea;">
                    <p style="margin: 0; font-size: 14px; color: #6b7280;">
                        <strong>Summary:</strong> You closed {len(tickets)} ticket{'s' if len(tickets) != 1 else ''} this week.
                    </p>
                </div>
            </div>
            
            <!-- Footer -->
            <div style="background-color: #f8fafc; padding: 25px; text-align: center; border-top: 1px solid #e5e7eb;">
                <p style="margin: 0; font-size: 14px; color: #6b7280;">
                    Best regards,<br>
                    {footer_sender}
                </p>
                <p style="margin: 15px 0 0 0; font-size: 12px; color: #9ca3af;">
                    This is an automated weekly summary from Enque.
                </p>
            </div>
            
        </div>
    </body>
    </html>
    """
    
    return html_content


async def send_weekly_summary_email(
    db: Session,
    agent_email: str,
    agent_name: str,
    tickets: List[Dict[str, Any]],
    week_start: datetime,
    week_end: datetime,
    access_token: str,
    sender_email: str
) -> bool:
    """
    Envía email de resumen semanal a un agente.
    """
    
    week_date = week_end.strftime("%B %d, %Y")
    subject = f"Enque 🎟️ Weekly Summary for {agent_name} for {week_date}"
    
    html_body = create_weekly_summary_email_html(
        agent_name=agent_name,
        tickets=tickets,
        week_start=week_start,
        week_end=week_end,
        sender_name=None
    )
    
    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": html_body
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": agent_email,
                        "name": agent_name
                    }
                }
            ]
        }
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail",
                json=message,
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code == 202:
                logger.info(f"✅ Weekly summary email sent successfully to {agent_email}")
                return True
            else:
                logger.error(f"❌ Failed to send weekly summary email to {agent_email}. Status: {response.status_code}, Response: {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Error sending weekly summary email to {agent_email}: {str(e)}")
        return False


async def process_weekly_agent_summaries(db: Session) -> Dict[str, Any]:

    from datetime import datetime, timedelta
    from app.models.agent import Agent
    from app.models.microsoft import MailboxConnection, MicrosoftToken
    from app.models.notification import NotificationSetting
    import json
    
    setting = db.query(NotificationSetting).filter(
        NotificationSetting.category == "agents",
        NotificationSetting.type == "weekly_agent_summary",
        NotificationSetting.is_enabled == True
    ).first()
    
    if not setting:
        logger.info("Weekly agent summary feature is disabled or not configured")
        return {"success": False, "message": "Feature disabled"}
    
    # Calculate last week's date range (Monday to Sunday)
    import pytz
    et_timezone = pytz.timezone("America/New_York")
    today = datetime.now(et_timezone).date()
    
    # Find last Monday (start of last week)
    days_since_monday = today.weekday()  # Monday = 0, Sunday = 6
    days_to_last_monday = days_since_monday + 7  # Go back to last Monday
    last_monday = today - timedelta(days=days_to_last_monday)
    
    # Find last Sunday (end of last week) 
    last_sunday = last_monday + timedelta(days=6)
    
    week_start = datetime.combine(last_monday, datetime.min.time())
    week_end = datetime.combine(last_sunday, datetime.max.time())
    
    workspace_settings = db.query(NotificationSetting).filter(
        NotificationSetting.category == "agents",
        NotificationSetting.type == "weekly_agent_summary",
        NotificationSetting.is_enabled == True
    ).all()
    
    results = {
        "success": True,
        "total_agents": 0,
        "summaries_sent": 0,
        "errors": []
    }
    
    for workspace_setting in workspace_settings:
        workspace_id = workspace_setting.workspace_id
        
        try:
            mailbox_info = db.query(MailboxConnection, MicrosoftToken)\
                .join(MicrosoftToken, MicrosoftToken.mailbox_connection_id == MailboxConnection.id)\
                .filter(
                    MailboxConnection.workspace_id == workspace_id,
                    MailboxConnection.is_active == True
                ).first()
            
            if not mailbox_info:
                logger.warning(f"No active mailbox found for workspace {workspace_id}")
                continue
            
            connection, token = mailbox_info
            
            if token.expires_at <= datetime.utcnow():
                try:
                    from app.services.microsoft_service import MicrosoftGraphService
                    ms_service = MicrosoftGraphService(db)
                    await ms_service.refresh_token_async(token)
                    db.refresh(token)
                except Exception as e:
                    logger.error(f"Error refreshing token for workspace {workspace_id}: {str(e)}")
                    continue
            
            agents = db.query(Agent).filter(
                Agent.workspace_id == workspace_id,
                Agent.is_active == True,
                Agent.email.isnot(None)
            ).all()
            
            results["total_agents"] += len(agents)
            
            for agent in agents:
                try:
                    tickets = get_agent_closed_tickets_last_week(db, agent.id)

                    success = await send_weekly_summary_email(
                        db=db,
                        agent_email=agent.email,
                        agent_name=agent.name,
                        tickets=tickets,
                        week_start=week_start,
                        week_end=week_end,
                        access_token=token.access_token,
                        sender_email=connection.email
                    )
                    
                    if success:
                        results["summaries_sent"] += 1
                        logger.info(f"✅ Weekly summary sent to {agent.name} ({agent.email})")
                    else:
                        results["errors"].append(f"Failed to send to {agent.name} ({agent.email})")
                        
                except Exception as e:
                    error_msg = f"Error processing agent {agent.name}: {str(e)}"
                    results["errors"].append(error_msg)
                    logger.error(error_msg)
                    continue
                    
        except Exception as e:
            error_msg = f"Error processing workspace {workspace_id}: {str(e)}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
            continue
    
    logger.info(f"Weekly agent summaries processed: {results['summaries_sent']}/{results['total_agents']} sent")
    return results