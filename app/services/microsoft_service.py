import requests
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from sqlalchemy.orm import Session, joinedload
from app.core.config import settings
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig, MailboxConnection
from app.schemas.microsoft import EmailData, EmailAddress, EmailAttachment, MicrosoftTokenCreate, EmailTicketMappingCreate
from app.schemas.task import TaskStatus # Import TaskStatus Enum
from app.models.task import Task
from app.models.agent import Agent
from app.models.user import User
from app.models.comment import Comment
from app.models.activity import Activity
from app.models.workspace import Workspace
from app.models.task import Task, TicketBody
from app.services.utils import get_or_create_user
from app.utils.logger import logger, log_important
import base64
import json # Ensure json is imported
from bs4 import BeautifulSoup
from fastapi import HTTPException, status
import httpx # Moved import to top level
# Removed unused import: get_current_active_user
from urllib.parse import urlencode


class MicrosoftGraphService:
    """Service for interacting with Microsoft Graph API"""

    def __init__(self, db: Session):
        """Initialize the service with database session"""
        self.db = db
        self.integration = self._get_active_integration()
        self.has_env_config = bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET and settings.MICROSOFT_TENANT_ID)
        self.auth_url = settings.MICROSOFT_AUTH_URL
        self.token_url = settings.MICROSOFT_TOKEN_URL
        self.graph_url = settings.MICROSOFT_GRAPH_URL
        self._app_token = None
        self._app_token_expires_at = datetime.utcnow()

        if self.integration:
            logger.info("Microsoft service initialized with database integration")
        elif self.has_env_config:
            logger.info("Microsoft service initialized with environment variables (no DB integration)")
        else:
            logger.warning("Microsoft service initialized without integration or environment variables")

    def _get_active_integration(self) -> Optional[MicrosoftIntegration]:
        """Get the active Microsoft integration"""
        return self.db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()

    def get_application_token(self) -> str:
        """Get an application token using client credentials flow"""
        if self._app_token and self._app_token_expires_at > datetime.utcnow():
            return self._app_token

        if not self.integration and not self.has_env_config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active Microsoft integration found")

        tenant_id = self.integration.tenant_id if self.integration else settings.MICROSOFT_TENANT_ID
        client_id = self.integration.client_id if self.integration else settings.MICROSOFT_CLIENT_ID
        client_secret = self.integration.client_secret if self.integration else settings.MICROSOFT_CLIENT_SECRET

        token_endpoint = self.token_url.replace("{tenant}", tenant_id)
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }

        try:
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status()
            token_data = response.json()
            self._app_token = token_data["access_token"]
            self._app_token_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            return self._app_token
        except Exception as e:
            logger.error(f"Failed to get application token: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to get application token: {str(e)}")

    def get_auth_url(
        self,
        redirect_uri: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        state: Optional[str] = None,
        prompt: Optional[str] = "consent" # Default prompt
    ) -> str:
        """Get the URL for Microsoft OAuth authentication flow, allowing custom redirect URI, scopes, state and prompt."""
        if not self.integration and not self.has_env_config:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Microsoft integration not configured")

        tenant_id = self.integration.tenant_id if self.integration else settings.MICROSOFT_TENANT_ID
        client_id = self.integration.client_id if self.integration else settings.MICROSOFT_CLIENT_ID

        final_redirect_uri = redirect_uri or (self.integration.redirect_uri if self.integration else settings.MICROSOFT_REDIRECT_URI)
        if not final_redirect_uri:
             final_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
             logger.warning(f"No redirect_uri provided or configured, falling back to default: {final_redirect_uri}")

        default_scopes = ["offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared", "User.Read"]
        final_scopes = scopes if scopes else default_scopes
        scope_string = " ".join(final_scopes)
        auth_endpoint = self.auth_url.replace("{tenant}", tenant_id)
        params = {
            "client_id": client_id, "response_type": "code", "redirect_uri": final_redirect_uri,
            "scope": scope_string, "response_mode": "query",
        }
        if prompt: params["prompt"] = prompt
        if state: params["state"] = state
        logger.info(f"Generated Microsoft Auth URL with redirect_uri: {final_redirect_uri}, scopes: '{scope_string}', prompt: {prompt}, state: {state}")
        return f"{auth_endpoint}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: Optional[str] = None) -> MicrosoftToken:
        needs_integration = not self.integration
        tenant_id = settings.MICROSOFT_TENANT_ID
        client_id = settings.MICROSOFT_CLIENT_ID
        client_secret = settings.MICROSOFT_CLIENT_SECRET
        scope = settings.MICROSOFT_SCOPE
        if self.integration:
            tenant_id = self.integration.tenant_id
            client_id = self.integration.client_id
            client_secret = self.integration.client_secret
            scope = self.integration.scope
        if not client_id or not client_secret:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Microsoft credentials not configured")
        if "offline_access" not in scope: scope = f"offline_access {scope}"
        correct_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
        data = {
            "client_id": client_id, "client_secret": client_secret, "code": code,
            "redirect_uri": correct_redirect_uri, "grant_type": "authorization_code"
        }
        token_endpoint = self.token_url.replace("{tenant}", tenant_id)
        try:
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status()
            token_data = response.json()
            refresh_token_val = token_data.get("refresh_token", "")
            user_info = self._get_user_info(token_data["access_token"])
            mailbox_email = user_info.get("mail")
            if not mailbox_email:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not get email address from Microsoft user info")
            workspace_id: Optional[int] = None; agent_id: Optional[int] = None
            if state:
                try:
                    missing_padding = len(state) % 4
                    if missing_padding: state += '=' * (4 - missing_padding)
                    decoded_state_json = base64.urlsafe_b64decode(state).decode('utf-8')
                    state_data = json.loads(decoded_state_json)
                    ws_id_str = state_data.get('workspace_id'); ag_id_str = state_data.get('agent_id')
                    if ws_id_str: workspace_id = int(ws_id_str)
                    if ag_id_str: agent_id = int(ag_id_str)
                    logger.info(f"Extracted from Base64 state: workspace_id={workspace_id}, agent_id={agent_id}")
                except Exception as decode_err:
                    logger.error(f"Failed to decode/parse Base64 state parameter '{state}': {decode_err}")
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter format.")
            else:
                 logger.error("State parameter is missing in exchange_code_for_token.")
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State parameter is required.")
            if not workspace_id: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace ID missing or invalid in state parameter.")
            if not agent_id: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent ID missing in state parameter.")
            current_agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
            if not current_agent: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent with ID {agent_id} not found.")
            workspace = self.db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if not workspace: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workspace with ID {workspace_id} not found.")
            if current_agent.workspace_id != workspace.id: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent does not belong to the specified workspace.")
            if needs_integration:
                self.integration = MicrosoftIntegration(
                    tenant_id=tenant_id, client_id=client_id, client_secret=client_secret,
                    redirect_uri=settings.MICROSOFT_REDIRECT_URI, scope=scope, is_active=True)
                self.db.add(self.integration); self.db.commit(); self.db.refresh(self.integration)
            mailbox_connection = self.db.query(MailboxConnection).filter(MailboxConnection.email == mailbox_email, MailboxConnection.workspace_id == workspace.id).first()
            if not mailbox_connection:
                mailbox_connection = MailboxConnection(
                    email=mailbox_email, display_name=user_info.get("displayName", "Microsoft User"),
                    workspace_id=workspace.id, created_by_agent_id=current_agent.id, is_active=True)
                self.db.add(mailbox_connection); self.db.commit(); self.db.refresh(mailbox_connection)
            token = MicrosoftToken(
                integration_id=self.integration.id, agent_id=current_agent.id, mailbox_connection_id=mailbox_connection.id,
                access_token=token_data["access_token"], refresh_token=refresh_token_val, token_type=token_data["token_type"],
                expires_at=datetime.utcnow() + timedelta(seconds=token_data["expires_in"]))
            self.db.add(token); self.db.commit(); self.db.refresh(token)
            existing_config = self.db.query(EmailSyncConfig).filter(EmailSyncConfig.mailbox_connection_id == mailbox_connection.id, EmailSyncConfig.workspace_id == workspace.id).first()
            if not existing_config:
                new_config = EmailSyncConfig(
                    integration_id=self.integration.id, mailbox_connection_id=mailbox_connection.id, folder_name="Inbox",
                    sync_interval=1, default_priority="Medium", auto_assign=False, workspace_id=workspace.id, is_active=True)
                self.db.add(new_config); self.db.commit()
            return token
        except Exception as e:
            logger.error(f"Error exchanging code for token: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to exchange code: {str(e)}")

    def refresh_token(self, token: MicrosoftToken) -> MicrosoftToken: # Original synchronous version
        """Refresh an expired access token"""
        if not self.integration and not self.has_env_config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active Microsoft integration or env config found")
        if not token.refresh_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No refresh token available to refresh.")

        client_id = self.integration.client_id if self.integration else settings.MICROSOFT_CLIENT_ID
        client_secret = self.integration.client_secret if self.integration else settings.MICROSOFT_CLIENT_SECRET
        tenant_id = self.integration.tenant_id if self.integration else settings.MICROSOFT_TENANT_ID
        
        data = {
            "client_id": client_id, 
            "client_secret": client_secret,
            "refresh_token": token.refresh_token, 
            "grant_type": "refresh_token",
            "scope": "offline_access Mail.Read Mail.ReadWrite Mail.Send User.Read" 
        }
        token_endpoint = self.token_url.replace("{tenant}", tenant_id)

        try:
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status() 
            token_data = response.json()

            token.access_token = token_data["access_token"]
            if "refresh_token" in token_data: 
                token.refresh_token = token_data["refresh_token"]
            token.expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            
            self.db.add(token) 
            self.db.commit()
            self.db.refresh(token)
            logger.info(f"Successfully refreshed token ID: {token.id} for mailbox_connection_id: {token.mailbox_connection_id}")
            return token
        except requests.exceptions.HTTPError as e: # More specific exception for HTTP errors
            logger.error(f"HTTP error refreshing token ID {token.id}: {e.response.status_code} - {e.response.text}", exc_info=True)
            if e.response.status_code in [400, 401]:
                error_json = {}; 
                try: error_json = e.response.json()
                except: pass
                if error_json.get("error") == "invalid_grant":
                    logger.warning(f"Refresh token for token ID {token.id} is invalid or expired. Marking as unusable.")
                    token.refresh_token = None; token.access_token = None
                    token.expires_at = datetime.utcnow() - timedelta(days=1)
                    self.db.add(token); self.db.commit()
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid. Re-authentication required.")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to refresh token: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error refreshing token ID {token.id}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected error refreshing token: {str(e)}")

    async def refresh_token_async(self, token: MicrosoftToken) -> MicrosoftToken: # Async version
        """Refresh an expired access token asynchronously"""
        if not self.integration and not self.has_env_config: 
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active Microsoft integration or env config found")
        if not token.refresh_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No refresh token available to refresh.")

        client_id = self.integration.client_id if self.integration else settings.MICROSOFT_CLIENT_ID
        client_secret = self.integration.client_secret if self.integration else settings.MICROSOFT_CLIENT_SECRET
        tenant_id = self.integration.tenant_id if self.integration else settings.MICROSOFT_TENANT_ID
        
        data = {
            "client_id": client_id, 
            "client_secret": client_secret,
            "refresh_token": token.refresh_token, 
            "grant_type": "refresh_token",
            "scope": "offline_access Mail.Read Mail.ReadWrite Mail.Send User.Read"
        }
        token_endpoint = self.token_url.replace("{tenant}", tenant_id)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(token_endpoint, data=data)
            
            response.raise_for_status() 
            token_data = response.json()

            token.access_token = token_data["access_token"]
            if "refresh_token" in token_data: 
                token.refresh_token = token_data["refresh_token"]
            token.expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            
            self.db.add(token) 
            self.db.commit()
            self.db.refresh(token)
            logger.info(f"Successfully refreshed token ID: {token.id} for mailbox_connection_id: {token.mailbox_connection_id}")
            return token
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error refreshing token ID {token.id}: {e.response.status_code} - {e.response.text}", exc_info=True)
            if e.response.status_code in [400, 401]:
                error_json = {}; 
                try: error_json = e.response.json()
                except: pass
                if error_json.get("error") == "invalid_grant":
                    logger.warning(f"Refresh token for token ID {token.id} is invalid or expired. Marking as unusable.")
                    token.refresh_token = None; token.access_token = None
                    token.expires_at = datetime.utcnow() - timedelta(days=1)
                    self.db.add(token); self.db.commit()
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid. Re-authentication required.")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to refresh token: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error refreshing token ID {token.id}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected error refreshing token: {str(e)}")

    def _get_user_info(self, access_token: str) -> Dict[str, Any]:
        try:
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            response = requests.get(f"{self.graph_url}/me", headers=headers)
            response.raise_for_status(); return response.json()
        except Exception as e:
            logger.error(f"Failed to get user info: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to get user info: {str(e)}")

    def _process_html_body(self, html_content: str, attachments: List[EmailAttachment], context: str = "email") -> str:
        if not html_content or not attachments: return html_content
        processed_html = html_content
        try:
            soup = BeautifulSoup(processed_html, 'html.parser')
            cid_map = {str(att.contentId): att for att in attachments if att.is_inline and att.contentId and att.contentBytes}
            if cid_map:
                image_tags_updated = 0
                for img_tag in soup.find_all('img'):
                    src = img_tag.get('src')
                    if src and src.startswith('cid:'):
                        cid_value = str(src[4:].strip('<>'))
                        matching_attachment = cid_map.get(cid_value)
                        if matching_attachment:
                            content_type = matching_attachment.content_type; base64_data = matching_attachment.contentBytes
                            if content_type and base64_data:
                                img_tag['src'] = f"data:{content_type};base64,{base64_data}"; image_tags_updated += 1
                if image_tags_updated > 0: processed_html = str(soup); logger.info(f"Processed HTML for {context}, updated {image_tags_updated} image tags.")
        except Exception as e: logger.error(f"Error processing HTML for CIDs ({context}): {e}", exc_info=True); processed_html = html_content
        return processed_html

    def sync_emails(self, sync_config: EmailSyncConfig):
        log_important(f"[MAIL SYNC] Starting sync for config ID: {sync_config.id}, Mailbox ID: {sync_config.mailbox_connection_id}")
        user_email, token = self._get_user_email_for_sync(sync_config) # This calls the sync check_and_refresh_all_tokens
        if not user_email or not token:
            logger.warning(f"[MAIL SYNC] No valid email or token found for sync config ID: {sync_config.id}. Skipping sync.")
            return []
        try:
            app_token = self.get_application_token()
            emails = self.get_mailbox_emails(app_token, user_email, sync_config.folder_name, filter_unread=True)
            if not emails:
                logger.info(f"[MAIL SYNC] No unread emails found for {user_email} in folder '{sync_config.folder_name}'.")
                sync_config.last_sync_time = datetime.utcnow(); self.db.commit(); return []
            logger.info(f"[MAIL SYNC] Found {len(emails)} unread emails for {user_email}.")
            created_tasks_count = 0; added_comments_count = 0
            processed_folder_id = self._get_or_create_processed_folder(app_token, user_email, "Enque Processed")
            if not processed_folder_id: logger.error(f"[MAIL SYNC] Could not get or create 'Enque Processed' folder for {user_email}. Emails will not be moved.")
            system_agent = self.db.query(Agent).filter(Agent.email == "system@enque.cc").first() or self.db.query(Agent).order_by(Agent.id.asc()).first()
            if not system_agent: logger.error("No system agent found. Cannot process emails."); return []
            for email_data in emails:
                email_id = email_data.get("id")
                if not email_id: logger.warning("[MAIL SYNC] Skipping email with missing ID."); continue
                try:
                    if self.db.query(EmailTicketMapping).filter(EmailTicketMapping.email_id == email_id).first():
                        logger.info(f"[MAIL SYNC] Email ID {email_id} already processed. Skipping."); continue
                    email_content = self._get_full_email(app_token, user_email, email_id)
                    if not email_content: logger.warning(f"[MAIL SYNC] Could not retrieve full content for email ID {email_id}. Skipping."); continue
                    conversation_id = email_content.get("conversationId")
                    existing_mapping_by_conv = None
                    if conversation_id:
                        existing_mapping_by_conv = self.db.query(EmailTicketMapping).filter(EmailTicketMapping.email_conversation_id == conversation_id).order_by(EmailTicketMapping.created_at.asc()).first()
                    if existing_mapping_by_conv:
                        logger.info(f"[MAIL SYNC] Email ID {email_id} is part of existing conversation {conversation_id} (Ticket ID: {existing_mapping_by_conv.ticket_id}). Adding as comment.")
                        email = self._parse_email_data(email_content, user_email)
                        if not email: logger.warning(f"[MAIL SYNC] Could not parse reply email data for email ID {email_id}. Skipping comment creation."); continue
                        reply_user = get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown")
                        if not reply_user: logger.error(f"Could not get or create user for reply email sender: {email.sender.address}"); continue
                        workspace = self.db.query(Workspace).filter(Workspace.id == sync_config.workspace_id).first()
                        if not workspace: logger.error(f"Workspace ID {sync_config.workspace_id} not found for reply. Skipping comment creation."); continue
                        processed_reply_html = self._process_html_body(email.body_content, email.attachments, f"reply email {email.id}")
                        sender_info_html = f"<p><strong>From:</strong> {reply_user.name} <{reply_user.email}></p><hr>"
                        final_comment_html = sender_info_html + processed_reply_html
                        new_comment = Comment(ticket_id=existing_mapping_by_conv.ticket_id, agent_id=system_agent.id, workspace_id=workspace.id, content=final_comment_html)
                        self.db.add(new_comment)
                        reply_email_mapping = EmailTicketMapping(
                            email_id=email.id, email_conversation_id=email.conversation_id, ticket_id=existing_mapping_by_conv.ticket_id,
                            email_subject=email.subject, email_sender=f"{email.sender.name} <{email.sender.address}>",
                            email_received_at=email.received_at, is_processed=True)
                        self.db.add(reply_email_mapping)
                        ticket_to_update = self.db.query(Task).filter(Task.id == existing_mapping_by_conv.ticket_id).first()
                        if ticket_to_update and ticket_to_update.status == TaskStatus.WITH_USER:
                             logger.info(f"[MAIL SYNC] User replied to Ticket ID {ticket_to_update.id} (status: {ticket_to_update.status}). Updating status to '{TaskStatus.IN_PROGRESS}'.")
                             ticket_to_update.status = TaskStatus.IN_PROGRESS; self.db.add(ticket_to_update)
                        elif ticket_to_update: logger.info(f"[MAIL SYNC] User replied to Ticket ID {ticket_to_update.id}. Status is '{ticket_to_update.status}', no automatic update needed.")
                        else: logger.warning(f"[MAIL SYNC] Could not find Ticket ID {existing_mapping_by_conv.ticket_id} to potentially update status after user reply.")
                        self.db.commit(); added_comments_count += 1
                        logger.info(f"[MAIL SYNC] Added comment to Ticket ID {existing_mapping_by_conv.ticket_id} from reply email ID {email.id}.")
                        if processed_folder_id: self._move_email_to_folder(app_token, user_email, email_id, processed_folder_id)
                        continue
                    else:
                        logger.info(f"[MAIL SYNC] Email ID {email_id} is a new conversation. Creating new ticket.")
                        email = self._parse_email_data(email_content, user_email)
                        if not email: logger.warning(f"[MAIL SYNC] Could not parse new email data for email ID {email_id}. Skipping ticket creation."); continue
                        task = self._create_task_from_email(email, sync_config, system_agent)
                        if task:
                            created_tasks_count += 1; logger.info(f"[MAIL SYNC] Created Task ID {task.id} from Email ID {email.id}.")
                            email_mapping = EmailTicketMapping(
                                email_id=email.id, email_conversation_id=email.conversation_id, ticket_id=task.id,
                                email_subject=email.subject, email_sender=f"{email.sender.name} <{email.sender.address}>",
                                email_received_at=email.received_at, is_processed=True)
                            self.db.add(email_mapping); self.db.commit()
                            if processed_folder_id:
                                new_id = self._move_email_to_folder(app_token, user_email, email_id, processed_folder_id)
                                if new_id and new_id != email_id: logger.info(f"[MAIL SYNC] Email ID changed from {email_id} to {new_id} after move. Updating mapping."); email_mapping.email_id = new_id; self.db.commit()
                                elif new_id: logger.info(f"[MAIL SYNC] Successfully moved email ID {email_id} to 'Enque Processed' folder.")
                                else: logger.warning(f"[MAIL SYNC] Failed to move email ID {email_id} to 'Enque Processed' folder.")
                        else: logger.warning(f"[MAIL SYNC] Failed to create task from email ID {email.id}.")
                except Exception as e: logger.error(f"[MAIL SYNC] Error processing email ID {email_data.get('id', 'N/A')}: {str(e)}", exc_info=True); self.db.rollback(); continue
            sync_config.last_sync_time = datetime.utcnow(); self.db.commit()
            log_important(f"[MAIL SYNC] Finished sync for config ID: {sync_config.id}. Created {created_tasks_count} tasks, Added {added_comments_count} comments.")
            return []
        except Exception as e: logger.error(f"[MAIL SYNC] Error during email synchronization for config ID {sync_config.id}: {str(e)}", exc_info=True); return []

    def _parse_email_data(self, email_content: Dict, user_email: str) -> Optional[EmailData]:
        try:
            sender_data = email_content.get("from", {}).get("emailAddress", {})
            sender = EmailAddress(name=sender_data.get("name", ""), address=sender_data.get("address", ""))
            if not sender.address: logger.warning(f"Could not parse sender from email content: {email_content.get('id')}"); return None
            recipients = [EmailAddress(name=r.get("emailAddress", {}).get("name", ""), address=r.get("emailAddress", {}).get("address", "")) for r in email_content.get("toRecipients", []) if r.get("emailAddress")]
            if not recipients: recipients = [EmailAddress(name="", address=user_email)]
            body_data = email_content.get("body", {}); body_content = body_data.get("content", ""); body_type = body_data.get("contentType", "html")
            received_time = datetime.utcnow(); received_dt_str = email_content.get("receivedDateTime")
            if received_dt_str:
                try: received_time = datetime.fromisoformat(received_dt_str.replace('Z', '+00:00'))
                except Exception as date_parse_error: logger.warning(f"Could not parse receivedDateTime '{received_dt_str}': {date_parse_error}")
            attachments = []
            for i, att_data in enumerate(email_content.get("attachments", [])):
                try:
                    attachments.append(EmailAttachment(
                        id=att_data["id"], name=att_data["name"], content_type=att_data["contentType"],
                        size=att_data.get("size", 0), is_inline=att_data.get("isInline", False),
                        contentId=att_data.get("contentId"), contentBytes=att_data.get("contentBytes")))
                except KeyError as ke: logger.error(f"Missing key while parsing attachment {i+1} for email {email_content.get('id')}: {ke}"); continue
                except Exception as att_err: logger.error(f"Error parsing attachment {i+1} for email {email_content.get('id')}: {att_err}"); continue
            return EmailData(
                id=email_content["id"], conversation_id=email_content.get("conversationId", ""), subject=email_content.get("subject", "No Subject"),
                sender=sender, to_recipients=recipients, body_content=body_content, body_type=body_type, received_at=received_time,
                attachments=attachments, importance=email_content.get("importance", "normal"))
        except Exception as e: logger.error(f"Error parsing email data for email ID {email_content.get('id', 'N/A')}: {str(e)}", exc_info=True); return None

    def _create_task_from_email(self, email: EmailData, config: EmailSyncConfig, system_agent: Agent) -> Optional[Task]:
        if not system_agent: logger.error("System agent is required for _create_task_from_email but was not provided."); return None
        try:
            priority = config.default_priority
            if email.importance == "high": priority = "High"
            elif email.importance == "low": priority = "Low"
            workspace_id = config.workspace_id
            if not workspace_id: logger.error(f"Missing workspace_id in sync config {config.id}. Cannot create user/task."); return None
            user = get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown", workspace_id=workspace_id)
            if not user: logger.error(f"Could not get or create user for email: {email.sender.address} in workspace {workspace_id}"); return None
            company_id = user.company_id; assigned_agent = None
            if config.auto_assign and config.default_assignee_id:
                assigned_agent = self.db.query(Agent).filter(Agent.id == config.default_assignee_id).first()
            workspace = self.db.query(Workspace).filter(Workspace.id == config.workspace_id).first()
            if not workspace: logger.error(f"Workspace ID {config.workspace_id} not found. Skipping ticket creation."); return None
            due_date = datetime.utcnow() + timedelta(days=3)
            task = Task(
                title=email.subject or "No Subject", description=None, status="Unread", priority=priority,
                assignee_id=assigned_agent.id if assigned_agent else None, due_date=due_date, sent_from_id=system_agent.id,
                user_id=user.id, company_id=company_id, workspace_id=workspace.id, mailbox_connection_id=config.mailbox_connection_id)
            self.db.add(task); self.db.flush()
            processed_html = self._process_html_body(email.body_content, email.attachments, f"new ticket {task.id}")
            if processed_html: self.db.add(TicketBody(ticket_id=task.id, email_body=processed_html))
            activity = Activity(agent_id=system_agent.id, source_type='Ticket', source_id=task.id, workspace_id=workspace.id, action=f"Created ticket from email from {email.sender.name}")
            self.db.add(activity)
            if email.attachments:
                non_inline_attachments = [att for att in email.attachments if not att.is_inline]
                if non_inline_attachments:
                    attachment_list = "\n".join([f"- {att.name} ({att.content_type}, {att.size} bytes)" for att in non_inline_attachments])
                    attachment_comment = Comment(ticket_id=task.id, agent_id=system_agent.id, workspace_id=workspace.id, content=f"Email contained {len(non_inline_attachments)} non-inline attachment(s):\n\n{attachment_list}")
                    self.db.add(attachment_comment)
            return task
        except Exception as e: logger.error(f"Error creating task from email ID {email.id}: {str(e)}", exc_info=True); self.db.rollback(); return None

    def get_mailbox_emails(self, app_token: str, user_email: str, folder_name: str = "Inbox", top: int = 10, filter_unread: bool = False) -> List[Dict[str, Any]]:
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}; folder_id = None
            response_folders = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, params={"$filter": f"displayName eq '{folder_name}'"})
            response_folders.raise_for_status(); folders = response_folders.json().get("value", [])
            if folders: folder_id = folders[0].get("id")
            else:
                common_inbox_names = ["inbox", "bandeja de entrada", "boîte de réception"]
                response_all_folders = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers)
                response_all_folders.raise_for_status(); all_folders = response_all_folders.json().get("value", [])
                for folder in all_folders:
                    if folder.get("displayName", "").lower() in common_inbox_names: folder_id = folder.get("id"); break
                if not folder_id:
                    response_inbox = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders/inbox", headers=headers)
                    if response_inbox.ok: folder_id = response_inbox.json().get("id")
                    else: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Folder '{folder_name}' not found.")
            params = {"$top": top, "$orderby": "receivedDateTime DESC", "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,bodyPreview,importance,hasAttachments,body,isRead"}
            if filter_unread: params["$filter"] = "isRead eq false"
            response_messages = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders/{folder_id}/messages", headers=headers, params=params)
            response_messages.raise_for_status(); return response_messages.json().get("value", [])
        except Exception as e: logger.error(f"Error getting emails for {user_email}: {str(e)}", exc_info=True); return []

    def get_mailbox_email_content(self, app_token: str, user_email: str, message_id: str) -> Dict[str, Any]:
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            params = {"$expand": "attachments"}
            response = requests.get(f"{self.graph_url}/users/{user_email}/messages/{message_id}", headers=headers, params=params)
            response.raise_for_status(); return response.json()
        except Exception as e: logger.error(f"Error getting full email content for message ID {message_id}: {str(e)}", exc_info=True); return {}

    def _mark_email_as_read(self, app_token: str, user_email: str, message_id: str) -> bool:
        try:
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}; data = {"isRead": True}
            response = requests.patch(endpoint, headers=headers, json=data); response.raise_for_status()
            logger.info(f"Marked email {message_id} as read for user {user_email}."); return True
        except Exception as e: logger.error(f"Error marking email {message_id} as read for user {user_email}: {str(e)}"); return False

    def _get_user_email_for_sync(self, config: EmailSyncConfig = None) -> Tuple[Optional[str], Optional[MicrosoftToken]]:
        # This method is synchronous, so it cannot call the async version of check_and_refresh_all_tokens_async directly.
        # The refresh logic should ideally be handled by a background task or an async entry point.
        # For now, it will rely on tokens being refreshed elsewhere or being valid.
        # await self.check_and_refresh_all_tokens_async() # Cannot do this here
        token: Optional[MicrosoftToken] = None; mailbox_email: Optional[str] = None
        if config:
            mailbox = self.db.query(MailboxConnection).filter(MailboxConnection.id == config.mailbox_connection_id).first()
            if not mailbox: 
                logger.warning(f"MailboxConnection not found for sync config ID: {config.id}")
                return None, None
            mailbox_email = mailbox.email
            # First, try to get an active, non-expired token
            token = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox.id, 
                MicrosoftToken.expires_at > datetime.utcnow()
            ).order_by(MicrosoftToken.created_at.desc()).first()

            if not token:
                # If no active token, try to find an expired one with a refresh token
                logger.info(f"No active token for MailboxConnection ID: {mailbox.id}. Looking for refreshable token.")
                expired_refreshable_token = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox.id,
                    MicrosoftToken.refresh_token.isnot(None),
                    MicrosoftToken.refresh_token != ""
                ).order_by(MicrosoftToken.expires_at.desc()).first()

                if expired_refreshable_token:
                    logger.info(f"Found refreshable token ID: {expired_refreshable_token.id} for MailboxConnection ID: {mailbox.id}. Attempting synchronous refresh.")
                    try:
                        token = self.refresh_token(expired_refreshable_token) # Attempt sync refresh
                        logger.info(f"Successfully refreshed token ID: {token.id} synchronously for MailboxConnection ID: {mailbox.id}.")
                    except HTTPException as e: # Catch HTTPException specifically from refresh_token
                        logger.error(f"Synchronous refresh failed for token ID {expired_refreshable_token.id} (MailboxConnection ID: {mailbox.id}): {e.detail}")
                        token = None # Ensure token is None if refresh fails
                    except Exception as e: # Catch any other unexpected errors
                        logger.error(f"Unexpected error during synchronous refresh for token ID {expired_refreshable_token.id} (MailboxConnection ID: {mailbox.id}): {str(e)}", exc_info=True)
                        token = None
                else:
                    logger.warning(f"No refreshable token found for MailboxConnection ID: {mailbox.id} (Email: {mailbox_email})")
            
            if not token: # If still no token after trying to refresh
                logger.warning(f"No valid token could be obtained for MailboxConnection ID: {mailbox.id} (Email: {mailbox_email}) after checking and attempting refresh.")
                return None, None
        else: # This else branch seems less likely to be used if sync_config is always provided
            token = self.get_most_recent_valid_token() 
            if not token: 
                logger.warning("No recent valid token found across all mailboxes (via get_most_recent_valid_token).")
                return None, None
            mailbox = self.db.query(MailboxConnection).filter(MailboxConnection.id == token.mailbox_connection_id).first()
            if not mailbox: logger.error(f"MailboxConnection not found for token ID: {token.id}, MailboxConnection ID: {token.mailbox_connection_id}"); return None, None
            mailbox_email = mailbox.email
        return mailbox_email, token

    def get_most_recent_valid_token(self) -> Optional[MicrosoftToken]: # This is synchronous
        token = self.db.query(MicrosoftToken).filter(MicrosoftToken.expires_at > datetime.utcnow()).order_by(MicrosoftToken.created_at.desc()).first()
        if token: 
            return token
        
        # Attempt to find and refresh an expired token synchronously if one exists with a refresh token
        expired_refreshable_token = self.db.query(MicrosoftToken).filter(
            MicrosoftToken.refresh_token.isnot(None),
            MicrosoftToken.refresh_token != ""
        ).order_by(MicrosoftToken.expires_at.desc()).first()

        if expired_refreshable_token:
            logger.info(f"No active token found by get_most_recent_valid_token. Found refreshable token ID: {expired_refreshable_token.id}. Attempting synchronous refresh.")
            try:
                refreshed_token = self.refresh_token(expired_refreshable_token) # Attempt sync refresh
                logger.info(f"Successfully refreshed token ID: {refreshed_token.id} synchronously via get_most_recent_valid_token.")
                return refreshed_token
            except HTTPException as e:
                logger.error(f"Synchronous refresh failed in get_most_recent_valid_token for token ID {expired_refreshable_token.id}: {e.detail}")
            except Exception as e:
                logger.error(f"Unexpected error during synchronous refresh in get_most_recent_valid_token for token ID {expired_refreshable_token.id}: {str(e)}", exc_info=True)
        
        logger.warning("No valid or refreshable Microsoft token found by get_most_recent_valid_token."); return None

    async def check_and_refresh_all_tokens_async(self) -> None: # Async, called by scheduler
        """Check and refresh all expiring tokens asynchronously. This is the primary refresh mechanism."""
        try:
            expiring_soon = datetime.utcnow() + timedelta(minutes=10)
            tokens_to_check = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.expires_at < expiring_soon, 
                MicrosoftToken.refresh_token.isnot(None), 
                MicrosoftToken.refresh_token != ""      
            ).all()
            refreshed_count = 0; failed_count = 0
            for token_to_refresh in tokens_to_check: 
                try:
                    logger.info(f"Token ID {token_to_refresh.id} for mailbox_connection {token_to_refresh.mailbox_connection_id} needs refresh. Attempting.")
                    await self.refresh_token_async(token_to_refresh) # Correctly calls the async version
                    refreshed_count += 1
                except Exception as e:
                    logger.warning(f"Failed to refresh token ID {token_to_refresh.id} for mailbox_connection {token_to_refresh.mailbox_connection_id}: {e}")
                    failed_count += 1
            if refreshed_count > 0 or failed_count > 0:
                logger.info(f"Token refresh check complete. Refreshed: {refreshed_count}, Failed: {failed_count}")
        except Exception as e:
            logger.error(f"Error during periodic token refresh check: {str(e)}", exc_info=True)

    def _get_full_email(self, app_token: str, user_email: str, email_id: str) -> Dict[str, Any]:
        try: return self.get_mailbox_email_content(app_token, user_email, email_id)
        except Exception: return {}

    def _get_or_create_processed_folder(self, app_token: str, user_email: str, folder_name: str) -> Optional[str]:
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            response = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, params={"$filter": f"displayName eq '{folder_name}'"})
            response.raise_for_status(); folders = response.json().get("value", [])
            if folders: return folders[0].get("id")
            logger.info(f"Folder '{folder_name}' not found for {user_email}. Attempting to create.")
            data = {"displayName": folder_name}
            response = requests.post(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, json=data)
            response.raise_for_status(); folder_id = response.json().get("id")
            logger.info(f"Folder '{folder_name}' created with ID: {folder_id} for user {user_email}")
            return folder_id
        except Exception as e: logger.error(f"Error getting or creating folder '{folder_name}' for {user_email}: {str(e)}", exc_info=True); return None

    def _move_email_to_folder(self, app_token: str, user_email: str, message_id: str, folder_id: str) -> Optional[str]:
        try:
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}/move"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}; data = {"destinationId": folder_id}
            response = requests.post(endpoint, headers=headers, json=data); response.raise_for_status()
            response_data = response.json(); new_message_id = response_data.get("id", message_id)
            if new_message_id != message_id: logger.info(f"Email ID changed from {message_id} to {new_message_id} after move.")
            return new_message_id
        except Exception as e: logger.error(f"Error moving email {message_id} to folder {folder_id} for user {user_email}: {str(e)}"); return message_id

    def send_reply_email(self, task_id: int, reply_content: str, agent: Agent) -> bool:
        logger.info(f"Attempting to send email reply for task_id: {task_id} by agent: {agent.email}")
        task = self.db.query(Task).options(joinedload(Task.mailbox_connection), joinedload(Task.user)).filter(Task.id == task_id).first()
        if not task: logger.error(f"Task not found for task_id: {task_id}"); return False
        if not task.mailbox_connection_id or not task.mailbox_connection:
            logger.warning(f"Task {task_id} did not originate from email or has no mailbox connection. No reply sent."); return True
        mailbox_connection = task.mailbox_connection; original_sender = task.user
        if not original_sender: logger.error(f"Original sender (User) missing for task_id: {task_id}"); return False
        try: app_token = self.get_application_token()
        except Exception as e: logger.error(f"Failed to get application token for sending reply: {e}"); return False
        email_mapping = self.db.query(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task_id).order_by(EmailTicketMapping.created_at.asc()).first()
        if not email_mapping or not email_mapping.email_id:
            logger.error(f"Could not find original email_id in mapping for task_id: {task_id}. Cannot send reply."); return True
        original_message_id = email_mapping.email_id
        logger.info(f"Found original message ID '{original_message_id}' for reply to task {task_id}")
        if not reply_content.strip().lower().startswith('<html'):
             html_body = f"<html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 1em 0; }}</style></head><body>{reply_content}</body></html>"
        else: html_body = reply_content
        reply_payload = {"comment": html_body}
        try:
            reply_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}/reply"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            logger.debug(f"Sending email reply via endpoint: {reply_endpoint}")
            response = requests.post(reply_endpoint, headers=headers, json=reply_payload)
            if response.status_code not in [200, 201, 202]:
                error_details = "No details available"; 
                try: error_details = response.json()
                except ValueError: error_details = response.text
                logger.error(f"Failed to send email reply for task_id: {task_id}. Status Code: {response.status_code}. Details: {error_details}")
                response.raise_for_status()
            logger.info(f"Successfully sent email reply (via /reply endpoint) for task_id: {task_id} to original sender of message {original_message_id}")
            return True
        except requests.exceptions.RequestException as e:
            error_details = "No details available"; status_code = 'N/A'
            if e.response is not None:
                status_code = e.response.status_code
                try: error_details = e.response.json()
                except ValueError: error_details = e.response.text
            logger.error(f"Failed to send email reply for task_id: {task_id}. Status Code: {status_code}. Details: {error_details}. Error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending email reply for task_id: {task_id}. Error: {str(e)}", exc_info=True)
            return False

    def send_new_email(self, mailbox_email: str, recipient_email: str, subject: str, html_body: str) -> bool:
        logger.info(f"Attempting to send new email using app token from: {mailbox_email} to: {recipient_email} with subject: {subject}")
        try: app_token = self.get_application_token()
        except Exception as e: logger.error(f"Failed to get application token for sending new email: {e}"); return False
        email_payload = {
            "message": {"subject": subject, "body": {"contentType": "HTML", "content": html_body},
                        "toRecipients": [{"emailAddress": {"address": recipient_email}}]},
            "saveToSentItems": "true"}
        try:
            send_mail_endpoint = f"{self.graph_url}/users/{mailbox_email}/sendMail"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            logger.debug(f"Sending new email via endpoint: {send_mail_endpoint}")
            response = requests.post(send_mail_endpoint, headers=headers, json=email_payload)
            if response.status_code not in [200, 202]:
                error_details = "No details available"; 
                try: error_details = response.json()
                except ValueError: error_details = response.text
                logger.error(f"Failed to send new email from {mailbox_email} to {recipient_email}. Status Code: {response.status_code}. Details: {error_details}")
                response.raise_for_status()
            logger.info(f"Successfully sent new email from {mailbox_email} to {recipient_email} (via /sendMail endpoint)")
            return True
        except requests.exceptions.RequestException as e:
            error_details = "No details available"; status_code = 'N/A'
            if e.response is not None:
                status_code = e.response.status_code
                try: error_details = e.response.json()
                except ValueError: error_details = e.response.text
            logger.error(f"Failed to send new email from {mailbox_email} to {recipient_email}. Status Code: {status_code}. Details: {error_details}. Error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending new email from {mailbox_email} to {recipient_email}. Error: {str(e)}", exc_info=True)
            return False

    async def send_email_with_user_token(
        self, user_access_token: str, sender_mailbox_email: str, recipient_email: str, 
        subject: str, html_body: str
    ) -> bool:
        logger.info(f"Attempting to send new email using user token from: {sender_mailbox_email} to: {recipient_email} with subject: {subject}")
        email_payload = {
            "message": {"subject": subject, "body": {"contentType": "HTML", "content": html_body},
                        "toRecipients": [{"emailAddress": {"address": recipient_email}}]},
            "saveToSentItems": "true"}
        try:
            send_mail_endpoint = f"{self.graph_url}/users/{sender_mailbox_email}/sendMail"
            headers = {"Authorization": f"Bearer {user_access_token}", "Content-Type": "application/json"}
            async with httpx.AsyncClient() as client:
                response = await client.post(send_mail_endpoint, headers=headers, json=email_payload)
            if response.status_code not in [200, 202]:
                error_details = "No details available"; 
                try: error_details = response.json()
                except Exception: error_details = response.text
                logger.error(f"Failed to send email from {sender_mailbox_email} using user token. Status: {response.status_code}. Details: {error_details}")
                response.raise_for_status() 
            logger.info(f"Successfully sent email from {sender_mailbox_email} to {recipient_email} using user token.")
            return True
        except httpx.HTTPStatusError as e:
            error_details = "No details available"; 
            try: error_details = e.response.json()
            except Exception: error_details = e.response.text
            logger.error(f"HTTP error sending email from {sender_mailbox_email} using user token. Status: {e.response.status_code}. Details: {error_details}. Error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error sending email from {sender_mailbox_email} using user token: {e}", exc_info=True)
            return False

def get_microsoft_service(db: Session) -> MicrosoftGraphService:
    return MicrosoftGraphService(db)

def mark_email_as_read_by_task_id(db: Session, task_id: int) -> bool:
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status != "Open": return False
        mapping = db.query(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task_id).first()
        if not mapping: logger.error(f"No mapping found for ticket #{task_id}"); return False
        logger.info(f"Found mapping for ticket #{task_id}, email_id: {mapping.email_id}")
        service = MicrosoftGraphService(db); app_token = service.get_application_token()
        if not app_token: logger.error(f"Could not get app token to mark email as read for task {task_id}"); return False
        if not task.mailbox_connection_id: logger.error(f"Task {task_id} has no mailbox_connection_id."); return False
        mailbox = db.query(MailboxConnection).filter(MailboxConnection.id == task.mailbox_connection_id).first()
        if not mailbox: logger.error(f"MailboxConnection not found for ID {task.mailbox_connection_id}"); return False
        result = service._mark_email_as_read(app_token, mailbox.email, mapping.email_id)
        if not result: logger.warning(f"Failed to mark email {mapping.email_id} as read directly.")
        return result
    except Exception as e: logger.error(f"Error in mark_email_as_read_by_task_id for task {task_id}: {str(e)}"); return False
