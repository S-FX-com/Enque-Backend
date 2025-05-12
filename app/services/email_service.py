from app.core.config import settings
from app.services.microsoft_service import MicrosoftGraphService # Assuming this service can send mail
from app.utils.logger import logger
from sqlalchemy.orm import Session # MicrosoftGraphService might need a DB session

# Placeholder for a more sophisticated HTML email template system
def create_invitation_email_html(agent_name: str, invitation_link: str, logo_url: str) -> str:
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
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo-container">
                <img src="{logo_url}" alt="Enque Logo">
            </div>
            <p>Hello {agent_name},</p>
            <p>You have been invited to join Enque. Please click the button below to set up your account and create your password:</p>
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
    user_access_token: str    # Valid access token for the sender_mailbox_email
) -> bool:
    """
    Sends an invitation email to a new agent using a user's delegated token.
    """
    subject = "You're invited to join Enque!" # Changed to English
    # You need to provide a public URL for your logo.
    # For example, if you host it on your frontend's public folder and it's accessible via app.enque.cc/enque.png
    # Or better, a CDN or dedicated image hosting.
    # Replace "YOUR_PUBLIC_LOGO_URL_HERE" with the actual URL.
    # If your frontend is at app.enque.cc and enque.png is in its public root, then:
    # logo_url = f"{settings.FRONTEND_URL}/enque.png" 
    # However, ensure this is truly public and doesn't require auth.
    # For now, using a placeholder. You MUST update this.
    logo_url = "https://app.enque.cc/enque.png" # Example: Replace with your actual public logo URL

    html_content = create_invitation_email_html(agent_name, invitation_link, logo_url)

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
