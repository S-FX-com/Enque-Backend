import requests
import urllib.parse
import secrets
import hashlib

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig
from app.schemas.microsoft import EmailData, EmailAddress, EmailAttachment, MicrosoftTokenCreate
from app.models.ticket import Ticket
from app.models.agent import Agent
from app.models.comment import Comment
from app.models.activity import Activity
from app.models.workspace import Workspace
from app.services.user import get_or_create_user
from app.utils.logger import logger, log_important
from fastapi import HTTPException, status


class MicrosoftGraphService:
    """Service for interacting with Microsoft Graph API"""
    
    def __init__(self, db: Session):
        """Initialize the service with database session"""
        self.db = db
        self.integration = self._get_active_integration()
        self.auth_url = settings.MICROSOFT_AUTH_URL
        self.token_url = settings.MICROSOFT_TOKEN_URL
        self.graph_url = settings.MICROSOFT_GRAPH_URL
        # Inicializar token de aplicación
        self._app_token = None
        self._app_token_expires_at = datetime.utcnow()
        
    def _get_active_integration(self) -> Optional[MicrosoftIntegration]:
        """Get the active Microsoft integration"""
        return self.db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()
    
    def get_application_token(self) -> str:
        """Get an application token using client credentials flow"""
        # If we already have a valid token, return it
        if self._app_token and self._app_token_expires_at > datetime.utcnow():
            return self._app_token
            
        if not self.integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active Microsoft integration found"
            )
            
        tenant_id = self.integration.tenant_id
        token_endpoint = self.token_url.replace("{tenant}", tenant_id)
        
        # Solicitud de token con credenciales de cliente
        data = {
            "client_id": self.integration.client_id,
            "client_secret": self.integration.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        
        try:
            logger.info("Requesting application token using client credentials")
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            
            # Guardar el token y su tiempo de expiración
            self._app_token = token_data["access_token"]
            self._app_token_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            
            logger.info(f"Obtained application token valid until {self._app_token_expires_at}")
            
            return self._app_token
            
        except requests.RequestException as e:
            logger.error(f"Error getting application token: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                detail = e.response.json() if e.response.content else str(e)
            else:
                detail = str(e)
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to get application token: {detail}"
            )
    
    def get_token_for_agent(self, agent_id: int) -> Optional[MicrosoftToken]:
        """Get a valid token for the given agent"""
        if not self.integration:
            return None
            
        token = self.db.query(MicrosoftToken).filter(
            MicrosoftToken.integration_id == self.integration.id,
            MicrosoftToken.agent_id == agent_id
        ).first()
        
        if token and token.expires_at < datetime.utcnow():
            token = self.refresh_token(token)
            
        return token
    
    def get_auth_url(self, redirect_uri: Optional[str] = None) -> str:
        """Generate Microsoft OAuth authorization URL"""
        # We use the existing integration or create a temporary one for authorization
        if not self.integration:
            # If there is no active integration, we need minimum parameters to generate the URL
            logger.info("No active integration found, using default values for auth URL")
            
            # Minimum values required for authorization
            tenant_id = getattr(settings, "MICROSOFT_TENANT_ID")
            client_id = getattr(settings, "MICROSOFT_CLIENT_ID")
            scope = getattr(settings, "MICROSOFT_SCOPE")
            
            # If there is no client_id in the configuration, we cannot continue
            if not client_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No Microsoft Client ID configured in application settings"
                )
        else:
            # We use the values of the existing integration
            tenant_id = self.integration.tenant_id
            client_id = self.integration.client_id
            scope = self.integration.scope
            
        # Use provided redirect URI or default one
        redirect = redirect_uri or getattr(settings, "MICROSOFT_REDIRECT_URI")
        if not redirect:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No redirect URI provided"
            )
            
        # URL encode parameters properly
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": scope,
            "response_mode": "query"
        }
        
        # Construct authorization URL
        auth_base_url = self.auth_url.replace("{tenant}", tenant_id)
        
        return f"{auth_base_url}?{urllib.parse.urlencode(params)}"
    
    def exchange_code_for_token(self, code: str, redirect_uri: str) -> MicrosoftToken:
        """Exchange authorization code for access token"""
        # If there is no active integration, we will create one after successful token exchange
        needs_integration = not self.integration
        
        # Default values if we need to create an integration
        tenant_id = getattr(settings, "MICROSOFT_TENANT_ID")
        client_id = getattr(settings, "MICROSOFT_CLIENT_ID")
        client_secret = getattr(settings, "MICROSOFT_CLIENT_SECRET")
        scope = getattr(settings, "MICROSOFT_SCOPE")
        
        if needs_integration:
            logger.info("No active integration found, will create one after successful token exchange")
            if not client_id or not client_secret:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Microsoft client credentials not configured in application settings"
                )
        else:
            # Use values from the existing integration
            tenant_id = self.integration.tenant_id
            client_id = self.integration.client_id
            client_secret = self.integration.client_secret
            scope = self.integration.scope
            
        # Make sure to include offline_access to get refresh_token
        if "offline_access" not in scope:
            scope = f"offline_access {scope}"
            
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        
        token_endpoint = self.token_url.replace("{tenant}", tenant_id)
        
        try:
            logger.info(f"Exchanging code for token with redirect URI: {redirect_uri}")
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            
            # Verify that we have refresh_token
            if "refresh_token" not in token_data:
                logger.warning("No refresh_token in response, authentication will not persist")
                # Add an empty refresh_token to avoid errors
                token_data["refresh_token"] = ""
            else:
                logger.info("Received refresh_token for persistent authentication")
                
            # Get user information to determine agent
            user_info = self._get_user_info(token_data["access_token"])
            logger.info(f"Got user info: {user_info}")
            
            # If we need to create an integration, we do it here
            if needs_integration:
                logger.info("Creating new Microsoft integration")
                # Use the tenant ID specific to the organization
                tenant_id = getattr(settings, "MICROSOFT_TENANT_ID")
                
                # Create new integration
                self.integration = MicrosoftIntegration(
                    tenant_id=tenant_id,
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=redirect_uri,
                    scope=scope,
                    is_active=True
                )
                self.db.add(self.integration)
                self.db.commit()
                self.db.refresh(self.integration)
                logger.info(f"Created new integration with ID: {self.integration.id}")
            
            # Find agent by email
            agent = self.db.query(Agent).filter(Agent.email == user_info.get("mail")).first()
            
            if not agent:
                logger.warning(f"No agent found with email {user_info.get('mail')}, creating one")
                # If there is no agent, we create one
                agent = Agent(
                    name=user_info.get("displayName", "Microsoft User"),
                    email=user_info.get("mail", ""),
                    role="agent",
                    # We generate a random password that can be changed later
                    password=hashlib.sha256(secrets.token_bytes(32)).hexdigest()[:20]
                )
                self.db.add(agent)
                self.db.commit()
                self.db.refresh(agent)
            
            # Create token model
            token_create = MicrosoftTokenCreate(
                integration_id=self.integration.id,
                agent_id=agent.id,
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                token_type=token_data["token_type"],
                expires_in=token_data["expires_in"]
            )
            
            # Save to database
            token = MicrosoftToken(
                integration_id=token_create.integration_id,
                agent_id=token_create.agent_id,
                access_token=token_create.access_token,
                refresh_token=token_create.refresh_token,
                token_type=token_create.token_type,
                expires_at=datetime.utcnow() + timedelta(seconds=token_create.expires_in)
            )
            
            self.db.add(token)
            self.db.commit()
            self.db.refresh(token)
            
            return token
            
        except requests.RequestException as e:
            logger.error(f"Error exchanging code for token: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                detail = e.response.json() if e.response.content else str(e)
            else:
                detail = str(e)
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to exchange code for token: {detail}"
            )
    
    def refresh_token(self, token: MicrosoftToken) -> MicrosoftToken:
        """Refresh an expired access token"""
        if not self.integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active Microsoft integration found"
            )
            
        data = {
            "client_id": self.integration.client_id,
            "client_secret": self.integration.client_secret,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token"
        }
        
        tenant_id = self.integration.tenant_id
        token_endpoint = self.token_url.replace("{tenant}", tenant_id)
        
        try:
            logger.info(f"Renewing expired token (ID: {token.id})")
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            
            # Update token
            token.access_token = token_data["access_token"]
            if "refresh_token" in token_data:  # Some providers don't return a new refresh token
                token.refresh_token = token_data["refresh_token"]
            token.expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            
            self.db.commit()
            self.db.refresh(token)
            
            logger.info(f"Token successfully renewed, valid until {token.expires_at}")
            return token
            
        except requests.RequestException as e:
            logger.error(f"Error refreshing token: {str(e)}")
            
            # Don't mark the token as expired to allow retries
            # If it's a temporary problem, it will be retried
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                if status_code in [400, 401]:
                    # If it's an authentication error (invalid_grant, etc.)
                    # Mark the token as expired but keep it
                    token.expires_at = datetime.utcnow() - timedelta(hours=1)
                    self.db.commit()
                    logger.warning(f"Token marked as expired due to authentication error")
                
                detail = e.response.json() if e.response.content else str(e)
                logger.error(f"Microsoft response: {detail}")
            else:
                detail = str(e)
                
            # Throw exception but don't delete the token
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to refresh token: {detail}"
            )
    
    def _get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user information from Microsoft Graph API"""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(f"{self.graph_url}/me", headers=headers)
            response.raise_for_status()
            
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"Error getting user info: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                detail = e.response.json() if e.response.content else str(e)
            else:
                detail = str(e)
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to get user info: {detail}"
            )
    
    def get_email_content(self, token: MicrosoftToken, message_id: str) -> Dict[str, Any]:
        """Get full email content including body"""
        try:
            headers = {
                "Authorization": f"Bearer {token.access_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{self.graph_url}/me/messages/{message_id}", 
                headers=headers,
                params={"$expand": "attachments"}
            )
            response.raise_for_status()
            
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"Error fetching email content: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                detail = e.response.json() if e.response.content else str(e)
            else:
                detail = str(e)
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch email content: {detail}"
            )
    
    def sync_emails(self, sync_config: EmailSyncConfig):
        """Synchronize emails from the specified folder and create tickets for new emails"""
        try:
            log_important(f"Syncing emails for config #{sync_config.id} from folder '{sync_config.folder_name}'")
            
            # Get the application token
            app_token = self.get_application_token()

            print("Ok")
            
            # Determine user email to use
            user_email = self._get_user_email_for_sync()
            
            # Get emails from the specified folder
            emails_data = self.get_mailbox_emails(
                app_token=app_token, 
                user_email=user_email,
                folder_name=sync_config.folder_name,
                filter_unread=True
            )
            
            if not emails_data:
                logger.info(f"No new emails found for config #{sync_config.id}")
                return []
                
            log_important(f"Found {len(emails_data)} emails for sync configuration #{sync_config.id}")
            
            created_tasks = []
            
            # Process each email
            for email_data in emails_data:
                try:
                    email_id = email_data.get("id")
                    
                    # Check if this email has already been processed
                    existing_mapping = self.db.query(EmailTicketMapping).filter_by(email_id=email_id).first()
                    if existing_mapping:
                        logger.debug(f"Email {email_id} has already been processed as ticket #{existing_mapping.ticket_id}")
                        continue
                    
                    # Get full email content
                    email_content = self._get_full_email(app_token, user_email, email_id)
                    
                    # Parse sender
                    sender = None
                    if "from" in email_content and "emailAddress" in email_content["from"]:
                        sender_data = email_content["from"]["emailAddress"]
                        sender = EmailAddress(
                            name=sender_data.get("name", ""),
                            address=sender_data.get("address", "")
                        )
                    else:
                        logger.warning(f"No sender found for email {email_id}")
                        continue  # Skip this email if no sender
                    
                    # Parse recipients
                    recipients = []
                    if "toRecipients" in email_content:
                        for recipient in email_content["toRecipients"]:
                            if "emailAddress" in recipient:
                                recipients.append(EmailAddress(
                                    name=recipient["emailAddress"].get("name", ""),
                                    address=recipient["emailAddress"].get("address", "")
                                ))
                    
                    if not recipients:
                        # Use the authenticated user's email as a fallback recipient
                        recipients = [EmailAddress(name="", address=user_email)]
                    
                    # Parse body content
                    body_content = ""
                    if "body" in email_content and "content" in email_content["body"]:
                        body_content = email_content["body"]["content"]
                        if len(body_content) > 200:
                            logger.debug(f"Email {email_id} has body of type {email_content['body'].get('contentType', 'unknown')} with {len(body_content)} characters")
                        else:
                            logger.debug(f"Email {email_id} has short body: {body_content}")
                    else:
                        logger.warning(f"No body content found for email {email_id}")
                    
                    # Parse received time
                    received_time = None
                    if "receivedDateTime" in email_content:
                        try:
                            received_time = datetime.fromisoformat(email_content["receivedDateTime"].replace('Z', '+00:00'))
                            logger.debug(f"Email {email_id} received at {received_time}")
                        except (ValueError, TypeError) as e:
                            logger.error(f"Error parsing receivedDateTime: {str(e)}")
                            received_time = datetime.utcnow()
                    else:
                        logger.warning(f"No receivedDateTime found for email {email_id}, using current time")
                        received_time = datetime.utcnow()
                    
                    # Create email data
                    logger.debug(f"Creating EmailData object for email {email_id}")
                    email = EmailData(
                        id=email_content["id"],
                        conversation_id=email_content.get("conversationId", ""),
                        subject=email_content.get("subject", "No Subject"),
                        sender=sender,
                        to_recipients=recipients,
                        body_content=body_content,
                        body_type=email_content.get("body", {}).get("contentType", "html"),
                        received_at=received_time,
                        attachments=[
                            EmailAttachment(
                                id=att["id"],
                                name=att["name"],
                                content_type=att["contentType"],
                                size=att.get("size", 0),
                                is_inline=att.get("isInline", False)
                            ) for att in email_content.get("attachments", [])
                        ],
                        importance=email_content.get("importance", "normal")
                    )
                    
                    # Create task from email
                    task = self._create_task_from_email(email, sync_config)
                    
                    if task:
                        # Mover el email a la carpeta "ObieDesk Processed" y obtener el nuevo ID
                        move_success, new_email_id = self._move_email_to_processed_folder(app_token, user_email, email_id)
                        
                        # Create email to ticket mapping with the updated ID
                        mapping = EmailTicketMapping(
                            email_id=new_email_id if move_success else email.id,  # Usar el nuevo ID si se movió exitosamente
                            email_conversation_id=email.conversation_id,
                            ticket_id=task.id,
                            email_subject=email.subject,
                            email_sender=email.sender.address if email.sender else "",
                            email_received_at=email.received_at,
                            is_processed=True
                        )
                        
                        self.db.add(mapping)
                        created_tasks.append(task)
                        
                        log_important(f"Created ticket #{task.id} from email {email_id}")
                    
                except Exception as e:
                    logger.error(f"Error processing email {email_data.get('id', 'unknown')}: {str(e)}")
                    # Continue with next email
                    continue
            
            self.db.commit()
            log_important(f"Created {len(created_tasks)} new tickets from emails")
            
            # Update last sync time
            sync_config.last_sync_time = datetime.utcnow()
            self.db.commit()
            log_important(f"Sync completed for config #{sync_config.id}")
            
            return created_tasks
            
        except Exception as e:
            logger.error(f"Error in email sync job: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch emails for {user_email}: {str(e)}"
            )
    
    def _create_task_from_email(self, email: EmailData, config: EmailSyncConfig) -> Ticket:
        """Create a task from email data"""
        # Determine priority based on config and email importance
        priority = config.default_priority
        if email.importance == "high":
            priority = "High"
        elif email.importance == "low":
            priority = "Low"
            
        # Use the email sender to find or create a user
        user_email = email.sender.address if email.sender else None
        if not user_email:
            raise ValueError("Email must have a sender")
        
        # Obtener un workspace predeterminado o el primero disponible
        workspace = self.db.query(Workspace).first()
        if not workspace:
            logger.error("No workspace found for creating ticket")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No workspace found for creating ticket"
            )
            
        # Find or create the user from the email sender
        user = get_or_create_user(self.db, user_email, email.sender.name if email.sender else "Unknown", workspace.id)
        logger.info(f"Got or created user #{user.id} ({user_email}) for email sender")
        
        # Find the company for the user based on email domain
        company_id = user.company_id
        
        # Determine who to assign this ticket to
        assigned_agent = None
        if config.auto_assign and config.default_assignee_id:
            assigned_agent = self.db.query(Agent).filter(Agent.id == config.default_assignee_id).first()
            
        # Who sent this task from the system side
        sent_from_agent = assigned_agent
        
        # If there is no agent assigned, use any agent
        if not sent_from_agent:
            # Buscar cualquier agente (sin filtrar por is_active que no existe)
            sent_from_agent = self.db.query(Agent).first()
                
            if not sent_from_agent:
                logger.error("No agent found to use as sent_from_id")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No agent found to use as sent_from_id"
                )
            
        # Create a due date 3 days in the future
        due_date = datetime.utcnow() + timedelta(days=3)
        
        # Create the task with details from the email
        task = Ticket(
            title=email.subject or "No Subject",
            description=email.body_content or "No Content",
            status="Unread",
            priority=priority,
            assignee_id=assigned_agent.id if assigned_agent else None,
            due_date=due_date,
            sent_from_id=sent_from_agent.id,
            user_id=user.id,
            company_id=company_id,
            workspace_id=workspace.id
        )
        
        self.db.add(task)
        self.db.flush()  # Get the ID without committing
        
        # Add a comment with the email content if it has substantial content
        if len(email.body_content or "") > 10:  # Only add if there's substantial content
            comment = Comment(
                ticket_id=task.id,
                agent_id=sent_from_agent.id,
                workspace_id=workspace.id,
                content=f"Original email from {email.sender.name} ({email.sender.address}):\n\n{email.body_content}"
            )
            self.db.add(comment)
        
        # Create an activity log for this action
        activity = Activity(
            agent_id=sent_from_agent.id,
            source_type='Ticket',
            source_id=task.id,
            workspace_id=workspace.id,
            action=f"Created ticket from email from {email.sender.name}"
        )
        self.db.add(activity)
        
        # If there are attachments, note them in a comment
        if email.attachments and len(email.attachments) > 0:
            attachment_list = "\n".join([f"- {att.name} ({att.content_type}, {att.size} bytes)" for att in email.attachments])
            attachment_comment = Comment(
                ticket_id=task.id,
                agent_id=sent_from_agent.id,
                workspace_id=workspace.id,
                content=f"Email contained {len(email.attachments)} attachment(s):\n\n{attachment_list}\n\nTo view attachments, check the original email."
            )
            self.db.add(attachment_comment)
        
        return task

    def get_emails(self, token: MicrosoftToken, folder_name: str = "Inbox", top: int = 10) -> List[Dict[str, Any]]:
        """Get emails from the specified folder"""
        try:
            headers = {
                "Authorization": f"Bearer {token.access_token}",
                "Content-Type": "application/json"
            }
            
            # First, find the folder ID by name
            logger.info(f"Fetching mail folders for user...")
            response = requests.get(
                f"{self.graph_url}/me/mailFolders", 
                headers=headers
            )
            response.raise_for_status()
            
            folders = response.json().get("value", [])
            logger.info(f"Found {len(folders)} mail folders: {[f.get('displayName') for f in folders]}")
            
            folder_id = None
            
            for folder in folders:
                if folder.get("displayName").lower() == folder_name.lower():
                    folder_id = folder.get("id")
                    logger.info(f"Found folder '{folder_name}' with ID: {folder_id}")
                    break
            
            if not folder_id:
                logger.error(f"Folder '{folder_name}' not found")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Folder '{folder_name}' not found"
                )
            
            # Now get emails from that folder
            params = {
                "$top": top,
                "$orderby": "receivedDateTime DESC",
                "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,bodyPreview,importance,hasAttachments",
                "$expand": "attachments"
            }
            
            logger.info(f"Fetching emails from folder '{folder_name}'...")
            response = requests.get(
                f"{self.graph_url}/me/mailFolders/{folder_id}/messages", 
                headers=headers,
                params=params
            )
            response.raise_for_status()
            
            emails = response.json().get("value", [])
            logger.info(f"Found {len(emails)} emails in folder '{folder_name}'")
            
            return emails
            
        except requests.RequestException as e:
            logger.error(f"Error fetching emails: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                detail = e.response.json() if e.response.content else str(e)
                logger.error(f"Response from Microsoft Graph: {detail}")
            else:
                detail = str(e)
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch emails: {detail}"
            )

    def get_mailbox_emails(self, app_token: str, user_email: str, folder_name: str = "Inbox", top: int = 10, filter_unread: bool = False) -> List[Dict[str, Any]]:
        """Get emails from a specific user's mailbox folder using application permissions"""
        try:
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json"
            }
            
            # Encontrar el ID de la carpeta por nombre - menos verboso
            response = requests.get(
                f"{self.graph_url}/users/{user_email}/mailFolders", 
                headers=headers
            )
            response.raise_for_status()
            
            folders = response.json().get("value", [])
            
            folder_id = None
            for folder in folders:
                if folder.get("displayName").lower() == folder_name.lower():
                    folder_id = folder.get("id")
                    break
            
            if not folder_id:
                logger.error(f"Folder '{folder_name}' not found for {user_email}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Folder '{folder_name}' not found for {user_email}"
                )
            
            # Configurar parámetros de la consulta
            params = {
                "$top": top,
                "$orderby": "receivedDateTime DESC",
                "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,bodyPreview,importance,hasAttachments,body,isRead,inferenceClassification",
                "$expand": "attachments"
            }
            
            # Add filter for unread messages if requested
            if filter_unread:
                params["$filter"] = "isRead eq false"
            
            response = requests.get(
                f"{self.graph_url}/users/{user_email}/mailFolders/{folder_id}/messages", 
                headers=headers,
                params=params
            )
            response.raise_for_status()
            
            emails = response.json().get("value", [])
            
            # Simplificación del log - solo si hay emails no leídos
            if filter_unread and emails:
                logger.info(f"Found {len(emails)} unread emails")
            
            return emails
            
        except requests.RequestException as e:
            logger.error(f"Error fetching emails for {user_email}: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                detail = e.response.json() if e.response.content else str(e)
                logger.error(f"Response from Microsoft Graph: {detail}")
            else:
                detail = str(e)
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch emails for {user_email}: {detail}"
            )
            
    def get_mailbox_email_content(self, app_token: str, user_email: str, message_id: str) -> Dict[str, Any]:
        """Get full email content from a specific user's mailbox using application permissions"""
        try:
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{self.graph_url}/users/{user_email}/messages/{message_id}", 
                headers=headers,
                params={"$expand": "attachments"}
            )
            response.raise_for_status()
            
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"Error fetching email content for {user_email}: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                detail = e.response.json() if e.response.content else str(e)
            else:
                detail = str(e)
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch email content for {user_email}: {detail}"
            )

    def _mark_email_as_read(self, app_token: str, user_email: str, message_id: str) -> bool:
        """Mark an email as read using application permissions"""
        try:
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}"
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json"
            }
            data = {
                "isRead": True
            }
            
            logger.debug(f"Attempting to mark email {message_id} as read for {user_email}")
            response = requests.patch(endpoint, headers=headers, json=data)
            
            if response.status_code >= 400:
                logger.error(f"Error marking email as read. Code: {response.status_code}, Response: {response.text}")
                return False
                
            response.raise_for_status()
            logger.debug(f"Email {message_id} marked as read successfully")
            
            # Verify the email was actually marked as read
            check_response = requests.get(endpoint, headers=headers)
            if check_response.status_code == 200:
                email_data = check_response.json()
                if email_data.get("isRead", False):
                    logger.debug(f"Verified: email {message_id} is now marked as read")
                else:
                    logger.warning(f"Alert! Email {message_id} still appears as unread despite successful PATCH")
            
            return True
        except Exception as e:
            logger.error(f"Error marking email as read: {str(e)}")
            return False
    
    def _get_or_create_processed_folder(self, app_token: str, user_email: str) -> str:
        """Get or create the 'ObieDesk Processed' folder for processed emails"""
        try:
            folder_name = "ObieDesk Processed"
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json"
            }
            
            # First, check if the folder already exists
            response = requests.get(
                f"{self.graph_url}/users/{user_email}/mailFolders", 
                headers=headers
            )
            response.raise_for_status()
            
            folders = response.json().get("value", [])
            
            for folder in folders:
                if folder.get("displayName") == folder_name:
                    logger.info(f"Found existing folder '{folder_name}' with ID: {folder.get('id')}")
                    return folder.get("id")
            
            # Folder doesn't exist, create it
            logger.info(f"Creating new folder '{folder_name}'")
            data = {
                "displayName": folder_name
            }
            
            response = requests.post(
                f"{self.graph_url}/users/{user_email}/mailFolders", 
                headers=headers,
                json=data
            )
            response.raise_for_status()
            
            folder_id = response.json().get("id")
            logger.info(f"Created new folder '{folder_name}' with ID: {folder_id}")
            return folder_id
            
        except Exception as e:
            logger.error(f"Error getting or creating processed folder: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to get or create processed folder: {str(e)}"
            )

    def _move_email_to_processed_folder(self, app_token: str, user_email: str, message_id: str) -> Tuple[bool, str]:
        """
        Move an email to the 'ObieDesk Processed' folder.
        Returns a tuple of (success, new_message_id).
        The new_message_id may be different from the original message_id if the move was successful.
        """
        try:
            # Get or create the processed folder
            processed_folder_id = self._get_or_create_processed_folder(app_token, user_email)
            
            # Move the email to the processed folder
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}/move"
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json"
            }
            data = {
                "destinationId": processed_folder_id
            }
            
            response = requests.post(endpoint, headers=headers, json=data)
            response.raise_for_status()
            
            # The response contains the message in its new location, with possibly a new ID
            response_data = response.json()
            new_message_id = response_data.get("id", message_id)
            
            logger.info(f"Successfully moved email {message_id} to ObieDesk Processed folder. New ID: {new_message_id}")
            return True, new_message_id
        except Exception as e:
            logger.error(f"Error moving email to processed folder: {str(e)}")
            return False, message_id
    
    def _get_user_email_for_sync(self):
        """Gets the authenticated user's email for synchronization"""
        # First, try to renew all tokens
        self.check_and_refresh_all_tokens()
        
        # Get the most recent token for any agent
        recent_token = self.get_most_recent_valid_token()
         
        if recent_token:
            # Try to get user info from the token
            try:
                user_info = self._get_user_info(recent_token.access_token)
                if user_info and user_info.get('mail'):
                    user_email = user_info.get('mail')
                    logger.info(f"Using authenticated user's email: {user_email}")
                    return user_email
            except Exception as e:
                logger.warning(f"Could not get user info from token: {str(e)}")
        
        # Look for an agent with a valid Microsoft email
        agent = self.db.query(Agent).filter(
            Agent.email.like("%@%")  # Basically valid email
        ).filter(
            ~Agent.email.like("%example.com")  # Don't use example emails
        ).first()
        
        if agent and agent.email:
            logger.info(f"Using agent's email: {agent.email}")
            return agent.email
            
        # If everything fails, throw an exception instead of continuing with an invalid email
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid email found for synchronization. Please authenticate with Microsoft first."
        )
    
    def get_most_recent_valid_token(self) -> Optional[MicrosoftToken]:
        """Gets the most recent token that is valid or can be renewed"""
        # Get only the most recent token
        token = self.db.query(MicrosoftToken).order_by(MicrosoftToken.updated_at.desc()).first()
        
        if not token:
            logger.warning("No Microsoft tokens found for renewal")
            return None
            
        # If the token is already valid, we use it
        if token.expires_at > datetime.utcnow():
            logger.debug(f"Using valid token (ID: {token.id})")
            return token
            
        # If it's expired, we try to renew it
        try:
            logger.debug(f"Attempting to renew expired token (ID: {token.id})")
            renewed_token = self.refresh_token(token)
            return renewed_token
        except Exception as e:
            logger.warning(f"Could not renew the most recent token (ID: {token.id}): {str(e)}")
            return None
    
    def check_and_refresh_all_tokens(self) -> None:
        """Verifies and renews only the most recent Microsoft token"""
        # Get only the most recent token
        token = self.db.query(MicrosoftToken).order_by(MicrosoftToken.updated_at.desc()).first()
        
        if not token:
            logger.warning("No Microsoft tokens found for renewal")
            return
            
        # Verify if the token is about to expire (less than 1 hour of validity)
        if token.expires_at < datetime.utcnow() + timedelta(hours=1):
            try:
                self.refresh_token(token)
                logger.info(f"Most recent token renewed (ID: {token.id})")
            except Exception as e:
                logger.warning(f"Could not renew the most recent token (ID: {token.id}): {str(e)}")
        else:
            logger.debug(f"The most recent token (ID: {token.id}) is still valid until {token.expires_at}")
        
        # Clean up old tokens - optional
        # Keep only the 5 most recent tokens
        if settings.CLEANUP_OLD_TOKENS:
            try:
                # Get all tokens except the 5 most recent ones
                old_tokens = self.db.query(MicrosoftToken).order_by(
                    MicrosoftToken.updated_at.desc()
                ).offset(5).all()
                
                for old_token in old_tokens:
                    self.db.delete(old_token)
                
                if old_tokens:
                    self.db.commit()
                    logger.info(f"Deleted {len(old_tokens)} old tokens")
            except Exception as e:
                logger.warning(f"Error cleaning old tokens: {str(e)}")

    def _get_full_email(self, app_token: str, user_email: str, email_id: str) -> Dict[str, Any]:
        """Gets the full content of an email using the application token"""
        try:
            headers = {
                "Authorization": f"Bearer {app_token}",
                "Content-Type": "application/json"
            }
            
            # Request full email content with expanded attachments
            params = {
                "$expand": "attachments",
                "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,bccRecipients,receivedDateTime,body,importance,hasAttachments"
            }
            
            response = requests.get(
                f"{self.graph_url}/users/{user_email}/messages/{email_id}", 
                headers=headers,
                params=params
            )
            response.raise_for_status()
            
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"Error fetching email content: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                detail = e.response.json() if e.response.content else str(e)
                logger.error(f"Response from Microsoft Graph: {detail}")
            else:
                detail = str(e)
                
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch email content: {detail}"
            )


def get_microsoft_service(db: Session) -> MicrosoftGraphService:
    """Get Microsoft Graph service instance"""
    return MicrosoftGraphService(db)

def mark_email_as_read_by_task_id(db: Session, task_id: int) -> bool:
    """
    Mark the email associated with a task as read in Microsoft.
    This should be called when a task status changes to "Open".
    """
    try:
        # Get the email mapping for this task
        email_mapping = db.query(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task_id).first()
        if not email_mapping:
            logger.warning(f"No email mapping found for task #{task_id}")
            return False
            
        # Get the service
        service = get_microsoft_service(db)
        
        # Get application token
        app_token = service.get_application_token()
        
        # Get authenticated user email
        user_email = service._get_user_email_for_sync()
        
        log_important(f"Processing email {email_mapping.email_id} for ticket #{task_id}")
        
        # Get the ID of the 'ObieDesk Processed' folder
        processed_folder_id = service._get_or_create_processed_folder(app_token, user_email)
        
        # Try to mark the email as read directly in the processed folder
        endpoint = f"{service.graph_url}/users/{user_email}/mailFolders/{processed_folder_id}/messages/{email_mapping.email_id}"
        headers = {
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json"
        }
        data = {
            "isRead": True
        }
        
        log_important(f"Attempting to mark email {email_mapping.email_id} as read in 'ObieDesk Processed' folder")
        
        try:
            response = requests.patch(endpoint, headers=headers, json=data)
            
            if response.status_code >= 400:
                logger.warning(f"Error marking email as read in processed folder. Code: {response.status_code}, Response: {response.text}")
                
                # If failed in the processed folder, try in the main location
                main_endpoint = f"{service.graph_url}/users/{user_email}/messages/{email_mapping.email_id}"
                main_response = requests.patch(main_endpoint, headers=headers, json=data)
                
                if main_response.status_code >= 400:
                    logger.error(f"Also failed to mark as read in main location. Code: {main_response.status_code}, Response: {main_response.text}")
                    return False
                
                log_important(f"Email {email_mapping.email_id} successfully marked as read in main location")
                return True
            
            log_important(f"Email {email_mapping.email_id} successfully marked as read in 'ObieDesk Processed' folder")
            return True
            
        except Exception as e:
            logger.error(f"Error marking email as read: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"Error processing email for ticket #{task_id}: {str(e)}")
        return False 