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

        # Use provided redirect_uri or default to the one in settings/integration
        final_redirect_uri = redirect_uri or (self.integration.redirect_uri if self.integration else settings.MICROSOFT_REDIRECT_URI)
        if not final_redirect_uri:
             # Fallback if neither provided nor configured (should ideally not happen)
             final_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
             logger.warning(f"No redirect_uri provided or configured, falling back to default: {final_redirect_uri}")

        # Use provided scopes or default to standard ones + User.Read
        default_scopes = ["offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared", "User.Read"]
        final_scopes = scopes if scopes else default_scopes
        scope_string = " ".join(final_scopes)

        auth_endpoint = self.auth_url.replace("{tenant}", tenant_id)

        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": final_redirect_uri,
            "scope": scope_string,
            "response_mode": "query",
        }
        if prompt:
            params["prompt"] = prompt
        if state:
            params["state"] = state

        logger.info(f"Generated Microsoft Auth URL with redirect_uri: {final_redirect_uri}, scopes: '{scope_string}', prompt: {prompt}, state: {state}")
        return f"{auth_endpoint}?{urlencode(params)}"


    # --- Función exchange_code_for_agent_login_token eliminada ---


    def exchange_code_for_token(self, code: str, redirect_uri: str, state: Optional[str] = None) -> MicrosoftToken:
        """
        Exchange authorization code for access token for Mailbox Sync.
        Uses the 'state' parameter to determine the correct workspace and initiating agent.
        A separate function might be needed for agent login flow if token storage differs.
        """
        needs_integration = not self.integration # Check if integration exists in DB

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
            refresh_token_val = token_data.get("refresh_token", "") # Use .get with default

            user_info = self._get_user_info(token_data["access_token"])
            mailbox_email = user_info.get("mail")
            if not mailbox_email:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not get email address from Microsoft user info")

            # --- Parse Base64 encoded state to get workspace_id and agent_id ---
            workspace_id: Optional[int] = None
            agent_id: Optional[int] = None
            state_data: Optional[dict] = None
            if state:
                try:
                    # Add padding if necessary before decoding Base64 URL-safe string
                    missing_padding = len(state) % 4
                    if missing_padding:
                        state += '=' * (4 - missing_padding)
                    logger.debug(f"Attempting to decode Base64 state in service (with padding added if needed): {state}")
                    decoded_state_bytes = base64.urlsafe_b64decode(state)
                    # Decode bytes to JSON string
                    decoded_state_json = decoded_state_bytes.decode('utf-8')
                    # Parse JSON string into dictionary
                    state_data = json.loads(decoded_state_json)

                    ws_id_str = state_data.get('workspace_id')
                    ag_id_str = state_data.get('agent_id')

                    if ws_id_str: workspace_id = int(ws_id_str)
                    if ag_id_str: agent_id = int(ag_id_str)

                    logger.info(f"Extracted from Base64 state: workspace_id={workspace_id}, agent_id={agent_id}")

                except Exception as decode_err:
                    logger.error(f"Failed to decode/parse Base64 state parameter '{state}' in exchange_code_for_token: {decode_err}")
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter format.")
            else:
                 # Handle missing state if it's absolutely required
                 logger.error("State parameter is missing in exchange_code_for_token.")
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State parameter is required.")


            if not workspace_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace ID missing or invalid in state parameter.")
            if not agent_id:
                 # Fallback: Try to get current agent if not in state? Risky without context.
                 # For now, require agent_id in state.
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent ID missing in state parameter.")

            # Find the specific agent and workspace based on state
            current_agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
            if not current_agent: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent with ID {agent_id} not found.")

            workspace = self.db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if not workspace: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workspace with ID {workspace_id} not found.")
            # Ensure the agent belongs to the workspace (optional but good practice)
            if current_agent.workspace_id != workspace.id:
                 raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent does not belong to the specified workspace.")
            # --- End State Parsing ---


            # Create integration if needed (This part might need review - should integration be global or per workspace?)
            # Assuming global integration for now.
            if needs_integration:
                self.integration = MicrosoftIntegration(
                    tenant_id=tenant_id, client_id=client_id, client_secret=client_secret,
                    redirect_uri=settings.MICROSOFT_REDIRECT_URI, scope=scope, is_active=True
                )
                self.db.add(self.integration)
                self.db.commit()
                self.db.refresh(self.integration)

            # Get or create MailboxConnection - Ensure it uses the correct workspace_id from state
            mailbox_connection = self.db.query(MailboxConnection).filter(
                MailboxConnection.email == mailbox_email,
                MailboxConnection.workspace_id == workspace.id # Check workspace too
            ).first()
            if not mailbox_connection:
                mailbox_connection = MailboxConnection(
                    email=mailbox_email,
                    display_name=user_info.get("displayName", "Microsoft User"),
                    workspace_id=workspace.id, # Use workspace ID from state
                    created_by_agent_id=current_agent.id, # Use agent ID from state
                    is_active=True
                )
                self.db.add(mailbox_connection)
                self.db.commit()
                self.db.refresh(mailbox_connection)

            # Create MicrosoftToken - Use agent_id from state
            token = MicrosoftToken(
                integration_id=self.integration.id,
                agent_id=current_agent.id, # Use agent ID from state
                mailbox_connection_id=mailbox_connection.id,
                access_token=token_data["access_token"],
                refresh_token=refresh_token_val,
                token_type=token_data["token_type"],
                expires_at=datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            )
            self.db.add(token)
            self.db.commit()
            self.db.refresh(token)

            # Create EmailSyncConfig if needed - Ensure it uses the correct workspace_id from state
            existing_config = self.db.query(EmailSyncConfig).filter(
                EmailSyncConfig.mailbox_connection_id == mailbox_connection.id,
                EmailSyncConfig.workspace_id == workspace.id # Check workspace too
                ).first()
            if not existing_config:
                new_config = EmailSyncConfig(
                    integration_id=self.integration.id,
                    mailbox_connection_id=mailbox_connection.id,
                    folder_name="Inbox",
                    sync_interval=1,
                    default_priority="Medium",
                    auto_assign=False,
                    workspace_id=workspace.id, # Use workspace ID from state
                    is_active=True
                )
                self.db.add(new_config)
                self.db.commit()

            return token

        except Exception as e:
            logger.error(f"Error exchanging code for token: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to exchange code: {str(e)}")

    def refresh_token(self, token: MicrosoftToken) -> MicrosoftToken:
        """Refresh an expired access token"""
        if not self.integration: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active Microsoft integration found")
        if not token.refresh_token: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No refresh token available to refresh.")

        data = {
            "client_id": self.integration.client_id, "client_secret": self.integration.client_secret,
            "refresh_token": token.refresh_token, "grant_type": "refresh_token"
        }
        token_endpoint = self.token_url.replace("{tenant}", self.integration.tenant_id)

        try:
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status()
            token_data = response.json()

            token.access_token = token_data["access_token"]
            if "refresh_token" in token_data: token.refresh_token = token_data["refresh_token"]
            token.expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            self.db.commit()
            self.db.refresh(token)
            logger.info(f"Successfully refreshed token ID: {token.id}")
            return token
        except Exception as e:
            logger.error(f"Failed to refresh token ID {token.id}: {str(e)}", exc_info=True)
            if hasattr(e, 'response') and getattr(e.response, 'status_code', 0) in [400, 401]:
                token.expires_at = datetime.utcnow() - timedelta(hours=1) # Mark as expired
                self.db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to refresh token: {str(e)}")

    def _get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user information from Microsoft Graph API"""
        try:
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            response = requests.get(f"{self.graph_url}/me", headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get user info: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to get user info: {str(e)}")

    def _process_html_body(self, html_content: str, attachments: List[EmailAttachment], context: str = "email") -> str:
        """Processes HTML body to embed inline images using data URIs."""
        if not html_content or not attachments:
            return html_content

        processed_html = html_content
        try:
            soup = BeautifulSoup(processed_html, 'html.parser')
            # Ensure contentId is treated as string for lookup
            cid_map = {str(att.contentId): att for att in attachments if att.is_inline and att.contentId and att.contentBytes}

            if cid_map:
                image_tags_updated = 0
                for img_tag in soup.find_all('img'):
                    src = img_tag.get('src')
                    if src and src.startswith('cid:'):
                        # Ensure CID value extracted is treated as string
                        cid_value = str(src[4:].strip('<>'))
                        matching_attachment = cid_map.get(cid_value)
                        if matching_attachment:
                            content_type = matching_attachment.content_type
                            base64_data = matching_attachment.contentBytes
                            if content_type and base64_data:
                                img_tag['src'] = f"data:{content_type};base64,{base64_data}"
                                image_tags_updated += 1
                if image_tags_updated > 0:
                    processed_html = str(soup)
                    logger.info(f"Processed HTML for {context}, updated {image_tags_updated} image tags.")
        except Exception as e:
            logger.error(f"Error processing HTML for CIDs ({context}): {e}", exc_info=True)
            # Fallback to original HTML if processing fails
            processed_html = html_content
        return processed_html

    def sync_emails(self, sync_config: EmailSyncConfig):
        """Synchronize emails and create tickets or comments"""
        log_important(f"[MAIL SYNC] Starting sync for config ID: {sync_config.id}, Mailbox ID: {sync_config.mailbox_connection_id}")
        user_email, token = self._get_user_email_for_sync(sync_config)
        if not user_email or not token:
            logger.warning(f"[MAIL SYNC] No valid email or token found for sync config ID: {sync_config.id}. Skipping sync.")
            return []

        try:
            app_token = self.get_application_token()
            # Use the corrected get_mailbox_emails without the problematic expand
            emails = self.get_mailbox_emails(app_token, user_email, sync_config.folder_name, filter_unread=True)
            if not emails:
                logger.info(f"[MAIL SYNC] No unread emails found for {user_email} in folder '{sync_config.folder_name}'.")
                sync_config.last_sync_time = datetime.utcnow()
                self.db.commit()
                return []

            logger.info(f"[MAIL SYNC] Found {len(emails)} unread emails for {user_email}.")
            created_tasks_count = 0
            added_comments_count = 0
            processed_folder_id = self._get_or_create_processed_folder(app_token, user_email, "Enque Processed")
            if not processed_folder_id: logger.error(f"[MAIL SYNC] Could not get or create 'Enque Processed' folder for {user_email}. Emails will not be moved.")

            # Find the system agent once before the loop
            system_agent = self.db.query(Agent).filter(Agent.email == "system@enque.cc").first() or self.db.query(Agent).order_by(Agent.id.asc()).first()
            if not system_agent:
                logger.error("No system agent found. Cannot process emails.")
                return [] # Cannot proceed without a system agent

            for email_data in emails:
                email_id = email_data.get("id")
                if not email_id: logger.warning("[MAIL SYNC] Skipping email with missing ID."); continue

                try:
                    # 1. Check if this specific email ID has already been processed
                    if self.db.query(EmailTicketMapping).filter(EmailTicketMapping.email_id == email_id).first():
                        logger.info(f"[MAIL SYNC] Email ID {email_id} already processed. Skipping."); continue

                    # 2. Get full email content (needed for parsing and conversation ID check)
                    email_content = self._get_full_email(app_token, user_email, email_id)
                    if not email_content: logger.warning(f"[MAIL SYNC] Could not retrieve full content for email ID {email_id}. Skipping."); continue

                    # 3. Check if it's a reply based on conversationId
                    conversation_id = email_content.get("conversationId")
                    existing_mapping_by_conv = None
                    if conversation_id:
                        existing_mapping_by_conv = self.db.query(EmailTicketMapping).filter(
                            EmailTicketMapping.email_conversation_id == conversation_id
                        ).order_by(EmailTicketMapping.created_at.asc()).first() # Find the original mapping

                    if existing_mapping_by_conv:
                        # --- It's a reply, add as comment ---
                        logger.info(f"[MAIL SYNC] Email ID {email_id} is part of existing conversation {conversation_id} (Ticket ID: {existing_mapping_by_conv.ticket_id}). Adding as comment.")
                        email = self._parse_email_data(email_content, user_email)
                        if not email: logger.warning(f"[MAIL SYNC] Could not parse reply email data for email ID {email_id}. Skipping comment creation."); continue

                        reply_user = get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown")
                        if not reply_user: logger.error(f"Could not get or create user for reply email sender: {email.sender.address}"); continue

                        workspace = self.db.query(Workspace).filter(Workspace.id == sync_config.workspace_id).first()
                        if not workspace: logger.error(f"Workspace ID {sync_config.workspace_id} not found for reply. Skipping comment creation."); continue

                        # Process HTML body for inline images
                        processed_reply_html = self._process_html_body(email.body_content, email.attachments, f"reply email {email.id}")

                        # Prepend sender info as HTML
                        sender_info_html = f"<p><strong>From:</strong> {reply_user.name} <{reply_user.email}></p><hr>"
                        final_comment_html = sender_info_html + processed_reply_html

                        # Create the comment associated with the SYSTEM agent, using processed HTML
                        new_comment = Comment(
                            ticket_id=existing_mapping_by_conv.ticket_id,
                            agent_id=system_agent.id, # Associate with system agent
                            workspace_id=workspace.id,
                            content=final_comment_html # Save processed HTML
                        )
                        self.db.add(new_comment)

                        # Create a *new* mapping for *this specific email reply*
                        reply_email_mapping = EmailTicketMapping(
                            email_id=email.id, email_conversation_id=email.conversation_id,
                            ticket_id=existing_mapping_by_conv.ticket_id, # Link to the existing ticket
                            email_subject=email.subject, email_sender=f"{email.sender.name} <{email.sender.address}>",
                            email_received_at=email.received_at, is_processed=True
                        )
                        self.db.add(reply_email_mapping)

                        # --- Automatic Status Update Logic for User Reply ---
                        # Get the ticket associated with the conversation
                        ticket_to_update = self.db.query(Task).filter(Task.id == existing_mapping_by_conv.ticket_id).first()
                        if ticket_to_update and ticket_to_update.status == TaskStatus.WITH_USER:
                             logger.info(f"[MAIL SYNC] User replied to Ticket ID {ticket_to_update.id} (status: {ticket_to_update.status}). Updating status to '{TaskStatus.IN_PROGRESS}'.")
                             ticket_to_update.status = TaskStatus.IN_PROGRESS
                             self.db.add(ticket_to_update) # Add the updated task to the session
                        elif ticket_to_update:
                             logger.info(f"[MAIL SYNC] User replied to Ticket ID {ticket_to_update.id}. Status is '{ticket_to_update.status}', no automatic update needed.")
                        else:
                             logger.warning(f"[MAIL SYNC] Could not find Ticket ID {existing_mapping_by_conv.ticket_id} to potentially update status after user reply.")
                        # --- End Status Update Logic ---

                        self.db.commit() # Commit comment, new mapping, and potential status update
                        added_comments_count += 1
                        logger.info(f"[MAIL SYNC] Added comment to Ticket ID {existing_mapping_by_conv.ticket_id} from reply email ID {email.id}.")

                        # Move the reply email
                        if processed_folder_id:
                            self._move_email_to_folder(app_token, user_email, email_id, processed_folder_id)

                        continue # Skip to the next email

                    else:
                        # --- It's a new conversation, create a new ticket ---
                        logger.info(f"[MAIL SYNC] Email ID {email_id} is a new conversation. Creating new ticket.")
                        email = self._parse_email_data(email_content, user_email) # Parse if not already done
                        if not email: logger.warning(f"[MAIL SYNC] Could not parse new email data for email ID {email_id}. Skipping ticket creation."); continue

                        task = self._create_task_from_email(email, sync_config, system_agent) # Pass system_agent
                        if task:
                            created_tasks_count += 1
                            logger.info(f"[MAIL SYNC] Created Task ID {task.id} from Email ID {email.id}.")
                            # Create mapping for the *new* ticket and *this* email
                            email_mapping = EmailTicketMapping(
                                email_id=email.id, email_conversation_id=email.conversation_id, ticket_id=task.id,
                                email_subject=email.subject, email_sender=f"{email.sender.name} <{email.sender.address}>",
                                email_received_at=email.received_at, is_processed=True
                            )
                            self.db.add(email_mapping); self.db.commit() # Commit mapping

                            if processed_folder_id:
                                new_id = self._move_email_to_folder(app_token, user_email, email_id, processed_folder_id)
                                if new_id and new_id != email_id:
                                    logger.info(f"[MAIL SYNC] Email ID changed from {email_id} to {new_id} after move. Updating mapping.")
                                    email_mapping.email_id = new_id; self.db.commit()
                                elif new_id: logger.info(f"[MAIL SYNC] Successfully moved email ID {email_id} to 'Enque Processed' folder.")
                                else: logger.warning(f"[MAIL SYNC] Failed to move email ID {email_id} to 'Enque Processed' folder.")
                        else: logger.warning(f"[MAIL SYNC] Failed to create task from email ID {email.id}.")

                except Exception as e: logger.error(f"[MAIL SYNC] Error processing email ID {email_data.get('id', 'N/A')}: {str(e)}", exc_info=True); self.db.rollback(); continue # Rollback and continue

            sync_config.last_sync_time = datetime.utcnow(); self.db.commit()
            log_important(f"[MAIL SYNC] Finished sync for config ID: {sync_config.id}. Created {created_tasks_count} tasks, Added {added_comments_count} comments.")
            # Return value might need adjustment if caller expects tasks
            return [] # Or return created_tasks if needed elsewhere
        except Exception as e: logger.error(f"[MAIL SYNC] Error during email synchronization for config ID {sync_config.id}: {str(e)}", exc_info=True); return []

    def _parse_email_data(self, email_content: Dict, user_email: str) -> Optional[EmailData]:
        """Parse email content into EmailData object"""
        try:
            sender_data = email_content.get("from", {}).get("emailAddress", {})
            sender = EmailAddress(name=sender_data.get("name", ""), address=sender_data.get("address", ""))
            if not sender.address: logger.warning(f"Could not parse sender from email content: {email_content.get('id')}"); return None

            recipients = [EmailAddress(name=r.get("emailAddress", {}).get("name", ""), address=r.get("emailAddress", {}).get("address", ""))
                          for r in email_content.get("toRecipients", []) if r.get("emailAddress")]
            if not recipients: recipients = [EmailAddress(name="", address=user_email)]

            body_data = email_content.get("body", {})
            body_content = body_data.get("content", "")
            body_type = body_data.get("contentType", "html")

            received_time = datetime.utcnow()
            received_dt_str = email_content.get("receivedDateTime")
            if received_dt_str:
                try: received_time = datetime.fromisoformat(received_dt_str.replace('Z', '+00:00'))
                except Exception as date_parse_error: logger.warning(f"Could not parse receivedDateTime '{received_dt_str}': {date_parse_error}")

            attachments = []
            for i, att_data in enumerate(email_content.get("attachments", [])):
                try:
                    attachments.append(EmailAttachment(
                        id=att_data["id"], name=att_data["name"], content_type=att_data["contentType"],
                        size=att_data.get("size", 0), is_inline=att_data.get("isInline", False),
                        contentId=att_data.get("contentId"), contentBytes=att_data.get("contentBytes")
                    ))
                except KeyError as ke: logger.error(f"Missing key while parsing attachment {i+1} for email {email_content.get('id')}: {ke}"); continue
                except Exception as att_err: logger.error(f"Error parsing attachment {i+1} for email {email_content.get('id')}: {att_err}"); continue

            return EmailData(
                id=email_content["id"], conversation_id=email_content.get("conversationId", ""),
                subject=email_content.get("subject", "No Subject"), sender=sender, to_recipients=recipients,
                body_content=body_content, body_type=body_type, received_at=received_time,
                attachments=attachments, importance=email_content.get("importance", "normal")
            )
        except Exception as e: logger.error(f"Error parsing email data for email ID {email_content.get('id', 'N/A')}: {str(e)}", exc_info=True); return None

    def _create_task_from_email(self, email: EmailData, config: EmailSyncConfig, system_agent: Agent) -> Optional[Task]: # Added system_agent parameter
        """Create a task from email data"""
        # Ensure system_agent is passed or handle error
        if not system_agent:
             logger.error("System agent is required for _create_task_from_email but was not provided.")
             return None

        try:
            priority = config.default_priority
            if email.importance == "high": priority = "High"
            elif email.importance == "low": priority = "Low"

            # Get workspace_id from the sync config
            workspace_id = config.workspace_id
            if not workspace_id:
                logger.error(f"Missing workspace_id in sync config {config.id}. Cannot create user/task.")
                return None

            # Pass workspace_id to get_or_create_user
            user = get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown", workspace_id=workspace_id)
            if not user: logger.error(f"Could not get or create user for email: {email.sender.address} in workspace {workspace_id}"); return None
            # company_id is now correctly None if the user was just created
            company_id = user.company_id

            assigned_agent = None
            if config.auto_assign and config.default_assignee_id:
                assigned_agent = self.db.query(Agent).filter(Agent.id == config.default_assignee_id).first()

            # system_agent is now passed as parameter

            workspace = self.db.query(Workspace).filter(Workspace.id == config.workspace_id).first()
            if not workspace: logger.error(f"Workspace ID {config.workspace_id} not found. Skipping ticket creation."); return None

            due_date = datetime.utcnow() + timedelta(days=3)
            task = Task(
                title=email.subject or "No Subject", description=None, status="Unread", priority=priority,
                assignee_id=assigned_agent.id if assigned_agent else None, due_date=due_date,
                sent_from_id=system_agent.id, user_id=user.id, company_id=company_id,
                workspace_id=workspace.id, mailbox_connection_id=config.mailbox_connection_id
            )
            self.db.add(task); self.db.flush()

            # Process HTML body for inline images
            processed_html = self._process_html_body(email.body_content, email.attachments, f"new ticket {task.id}")

            # Save processed HTML to TicketBody
            if processed_html: self.db.add(TicketBody(ticket_id=task.id, email_body=processed_html))

            # Removed the automatic comment creation for "Ticket created from email..."
            # initial_comment = Comment(...)
            # self.db.add(initial_comment)

            # Create activity log
            activity = Activity(
                agent_id=system_agent.id, # Use system agent ID
                source_type='Ticket',
                source_id=task.id,
                workspace_id=workspace.id,
                action=f"Created ticket from email from {email.sender.name}"
            )
            self.db.add(activity)
            # Add comment about attachments if any
            if email.attachments:
                # Filter out inline attachments already processed
                non_inline_attachments = [att for att in email.attachments if not att.is_inline]
                if non_inline_attachments:
                    attachment_list = "\n".join([f"- {att.name} ({att.content_type}, {att.size} bytes)" for att in non_inline_attachments])
                    attachment_comment = Comment(
                        ticket_id=task.id,
                        agent_id=system_agent.id, # Use system agent ID
                        workspace_id=workspace.id,
                        content=f"Email contained {len(non_inline_attachments)} non-inline attachment(s):\n\n{attachment_list}"
                    )
                    self.db.add(attachment_comment)

            # Commit is handled after creating the mapping outside this function now
            return task
        except Exception as e: logger.error(f"Error creating task from email ID {email.id}: {str(e)}", exc_info=True); self.db.rollback(); return None

    def get_mailbox_emails(self, app_token: str, user_email: str, folder_name: str = "Inbox", top: int = 10, filter_unread: bool = False) -> List[Dict[str, Any]]:
        """Get emails from a specific user's mailbox folder using application permissions"""
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            folder_id = None
            response_folders = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, params={"$filter": f"displayName eq '{folder_name}'"})
            response_folders.raise_for_status()
            folders = response_folders.json().get("value", [])
            if folders: folder_id = folders[0].get("id")
            else: # Try common names or well-known name
                common_inbox_names = ["inbox", "bandeja de entrada", "boîte de réception"]
                response_all_folders = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers)
                response_all_folders.raise_for_status()
                all_folders = response_all_folders.json().get("value", [])
                for folder in all_folders:
                    if folder.get("displayName", "").lower() in common_inbox_names: folder_id = folder.get("id"); break
                if not folder_id:
                    response_inbox = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders/inbox", headers=headers)
                    if response_inbox.ok: folder_id = response_inbox.json().get("id")
                    else: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Folder '{folder_name}' not found.")

            # Re-comment $expand as it was causing 400 errors
            params = {
                "$top": top,
                "$orderby": "receivedDateTime DESC",
                "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,bodyPreview,importance,hasAttachments,body,isRead"
                # $expand line completely removed
            }
            if filter_unread: params["$filter"] = "isRead eq false"
            response_messages = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders/{folder_id}/messages", headers=headers, params=params)
            response_messages.raise_for_status()
            return response_messages.json().get("value", [])
        except Exception as e: logger.error(f"Error getting emails for {user_email}: {str(e)}", exc_info=True); return []

    def get_mailbox_email_content(self, app_token: str, user_email: str, message_id: str) -> Dict[str, Any]:
        """Get full email content from a specific user's mailbox, including attachment content"""
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            params = {"$expand": "attachments"} # Ensure attachments are expanded to get contentBytes
            response = requests.get(f"{self.graph_url}/users/{user_email}/messages/{message_id}", headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e: logger.error(f"Error getting full email content for message ID {message_id}: {str(e)}", exc_info=True); return {}

    def _mark_email_as_read(self, app_token: str, user_email: str, message_id: str) -> bool:
        """Mark an email as read"""
        try:
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            data = {"isRead": True}
            response = requests.patch(endpoint, headers=headers, json=data)
            response.raise_for_status()
            logger.info(f"Marked email {message_id} as read for user {user_email}.")
            return True
        except Exception as e: logger.error(f"Error marking email {message_id} as read for user {user_email}: {str(e)}"); return False

    def _get_user_email_for_sync(self, config: EmailSyncConfig = None) -> Tuple[Optional[str], Optional[MicrosoftToken]]:
        """Get email and token for sync"""
        self.check_and_refresh_all_tokens()
        token: Optional[MicrosoftToken] = None; mailbox_email: Optional[str] = None
        if config:
            mailbox = self.db.query(MailboxConnection).filter(MailboxConnection.id == config.mailbox_connection_id).first()
            if not mailbox: logger.warning(f"MailboxConnection not found for sync config ID: {config.id}"); return None, None
            mailbox_email = mailbox.email
            token = self.db.query(MicrosoftToken).filter(MicrosoftToken.mailbox_connection_id == mailbox.id, MicrosoftToken.expires_at > datetime.utcnow()).order_by(MicrosoftToken.created_at.desc()).first()
            if not token: logger.warning(f"No valid token found for MailboxConnection ID: {mailbox.id} (Email: {mailbox_email})"); return None, None
        else:
            token = self.get_most_recent_valid_token()
            if not token: logger.warning("No recent valid token found across all mailboxes."); return None, None
            mailbox = self.db.query(MailboxConnection).filter(MailboxConnection.id == token.mailbox_connection_id).first()
            if not mailbox: logger.error(f"MailboxConnection not found for token ID: {token.id}, MailboxConnection ID: {token.mailbox_connection_id}"); return None, None
            mailbox_email = mailbox.email
        return mailbox_email, token

    def get_most_recent_valid_token(self) -> Optional[MicrosoftToken]:
        """Get the most recent valid token across all integrations/mailboxes"""
        token = self.db.query(MicrosoftToken).filter(MicrosoftToken.expires_at > datetime.utcnow()).order_by(MicrosoftToken.created_at.desc()).first()
        if token: return token
        expired_token = self.db.query(MicrosoftToken).filter(MicrosoftToken.refresh_token != None, MicrosoftToken.refresh_token != "").order_by(MicrosoftToken.expires_at.desc()).first()
        if expired_token:
            try: logger.info(f"Attempting to refresh expired token ID: {expired_token.id}"); return self.refresh_token(expired_token)
            except Exception as e: logger.error(f"Failed to refresh expired token ID {expired_token.id}: {e}"); return None
        logger.warning("No valid or refreshable Microsoft token found."); return None

    def check_and_refresh_all_tokens(self) -> None:
        """Check and refresh all expiring tokens"""
        try:
            expiring_soon = datetime.utcnow() + timedelta(minutes=10)
            tokens_to_check = self.db.query(MicrosoftToken).filter(MicrosoftToken.expires_at < expiring_soon, MicrosoftToken.refresh_token != None, MicrosoftToken.refresh_token != "").all()
            refreshed_count = 0; failed_count = 0
            for token in tokens_to_check:
                try: logger.info(f"Token ID {token.id} needs refresh. Attempting."); self.refresh_token(token); refreshed_count += 1
                except Exception as e: logger.warning(f"Failed to refresh token ID {token.id}: {e}"); failed_count += 1
            if refreshed_count > 0 or failed_count > 0: logger.info(f"Token refresh check complete. Refreshed: {refreshed_count}, Failed: {failed_count}")
        except Exception as e: logger.error(f"Error during periodic token refresh check: {str(e)}")

    def _get_full_email(self, app_token: str, user_email: str, email_id: str) -> Dict[str, Any]:
        """Get the full content of an email, including attachment contentBytes"""
        try: return self.get_mailbox_email_content(app_token, user_email, email_id)
        except Exception as e: return {} # Already logged

    def _get_or_create_processed_folder(self, app_token: str, user_email: str, folder_name: str) -> Optional[str]:
        """Get or create folder for processed emails"""
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            response = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, params={"$filter": f"displayName eq '{folder_name}'"})
            response.raise_for_status()
            folders = response.json().get("value", [])
            if folders: return folders[0].get("id")
            logger.info(f"Folder '{folder_name}' not found for {user_email}. Attempting to create.")
            data = {"displayName": folder_name}
            response = requests.post(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, json=data)
            response.raise_for_status()
            folder_id = response.json().get("id")
            logger.info(f"Folder '{folder_name}' created with ID: {folder_id} for user {user_email}")
            return folder_id
        except Exception as e: logger.error(f"Error getting or creating folder '{folder_name}' for {user_email}: {str(e)}", exc_info=True); return None

    def _move_email_to_folder(self, app_token: str, user_email: str, message_id: str, folder_id: str) -> Optional[str]:
        """Move email to specific folder, returns the new ID if it changed"""
        try:
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}/move"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            data = {"destinationId": folder_id}
            response = requests.post(endpoint, headers=headers, json=data)
            response.raise_for_status()
            response_data = response.json()
            new_message_id = response_data.get("id", message_id)
            if new_message_id != message_id: logger.info(f"Email ID changed from {message_id} to {new_message_id} after move.")
            return new_message_id
        except Exception as e: logger.error(f"Error moving email {message_id} to folder {folder_id} for user {user_email}: {str(e)}"); return message_id # Return original on failure

    def send_reply_email(self, task_id: int, reply_content: str, agent: Agent) -> bool:
        """Send a reply email for a given task using Microsoft Graph API"""
        logger.info(f"Attempting to send email reply for task_id: {task_id} by agent: {agent.email}")

        # 1. Fetch the task and related data
        task = self.db.query(Task).options(joinedload(Task.mailbox_connection), joinedload(Task.user)).filter(Task.id == task_id).first()
        if not task: logger.error(f"Task not found for task_id: {task_id}"); return False
        if not task.mailbox_connection_id or not task.mailbox_connection:
            logger.warning(f"Task {task_id} did not originate from email or has no mailbox connection. No reply sent."); return True
        mailbox_connection = task.mailbox_connection
        original_sender = task.user
        if not original_sender: logger.error(f"Original sender (User) missing for task_id: {task_id}"); return False

        # 2. Get Application Token
        try: app_token = self.get_application_token()
        except Exception as e: logger.error(f"Failed to get application token for sending reply: {e}"); return False

        # 3. Get original email ID
        email_mapping = self.db.query(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task_id).order_by(EmailTicketMapping.created_at.asc()).first()
        if not email_mapping or not email_mapping.email_id:
            logger.error(f"Could not find original email_id in mapping for task_id: {task_id}. Cannot send reply."); return True
        original_message_id = email_mapping.email_id
        logger.info(f"Found original message ID '{original_message_id}' for reply to task {task_id}")

        # 4. Construct Reply Payload
        # Use the reply_content directly, as it should already contain the signature from Tiptap
        # Add basic HTML structure if reply_content doesn't already have it (Tiptap usually provides it)
        if not reply_content.strip().lower().startswith('<html'):
             html_body = f"""
             <html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 1em 0; }}</style></head>
             <body>{reply_content}</body></html>
             """
        else:
             html_body = reply_content # Assume Tiptap provided full HTML

        # Payload for /reply endpoint requires 'comment' field
        reply_payload = {"comment": html_body} # Use the (potentially wrapped) reply_content

        # 5. Send Reply via Graph API
        try:
            reply_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}/reply"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            logger.debug(f"Sending email reply via endpoint: {reply_endpoint}")
            response = requests.post(reply_endpoint, headers=headers, json=reply_payload)

            if response.status_code not in [200, 201, 202]: # Check for success status codes
                error_details = "No details available"
                try: error_details = response.json()
                except ValueError: error_details = response.text
                logger.error(f"Failed to send email reply for task_id: {task_id}. Status Code: {response.status_code}. Details: {error_details}")
                response.raise_for_status() # Raise exception for bad status

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
        """Send a new email message using Microsoft Graph API"""
        logger.info(f"Attempting to send new email from: {mailbox_email} to: {recipient_email} with subject: {subject}")

        # 1. Get Application Token
        try:
            app_token = self.get_application_token()
        except Exception as e:
            logger.error(f"Failed to get application token for sending new email: {e}")
            return False

        # 2. Construct Email Payload for sendMail endpoint
        email_payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": html_body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": recipient_email
                        }
                    }
                ]
                # 'from' and 'sender' are usually set automatically based on the mailbox_email used in the URL
            },
            "saveToSentItems": "true" # Save a copy in the sender's Sent Items folder
        }

        # 3. Send Email via Graph API using /sendMail
        try:
            send_mail_endpoint = f"{self.graph_url}/users/{mailbox_email}/sendMail"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            logger.debug(f"Sending new email via endpoint: {send_mail_endpoint}")
            response = requests.post(send_mail_endpoint, headers=headers, json=email_payload)

            if response.status_code not in [200, 202]: # sendMail returns 202 Accepted
                error_details = "No details available"
                try: error_details = response.json()
                except ValueError: error_details = response.text
                logger.error(f"Failed to send new email from {mailbox_email} to {recipient_email}. Status Code: {response.status_code}. Details: {error_details}")
                response.raise_for_status() # Raise exception for bad status

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


def get_microsoft_service(db: Session) -> MicrosoftGraphService:
    """Utility function to get a new Microsoft service instance"""
    return MicrosoftGraphService(db)

def mark_email_as_read_by_task_id(db: Session, task_id: int) -> bool:
    """Mark an email as read based on the task ID, only when status is 'Open'"""
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status != "Open": return False # Only mark if Open

        mapping = db.query(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task_id).first()
        if not mapping: logger.error(f"No mapping found for ticket #{task_id}"); return False
        logger.info(f"Found mapping for ticket #{task_id}, email_id: {mapping.email_id}")

        service = MicrosoftGraphService(db)
        app_token = service.get_application_token()
        if not app_token: logger.error(f"Could not get app token to mark email as read for task {task_id}"); return False

        if not task.mailbox_connection_id: logger.error(f"Task {task_id} has no mailbox_connection_id."); return False
        mailbox = db.query(MailboxConnection).filter(MailboxConnection.id == task.mailbox_connection_id).first()
        if not mailbox: logger.error(f"MailboxConnection not found for ID {task.mailbox_connection_id}"); return False

        result = service._mark_email_as_read(app_token, mailbox.email, mapping.email_id)
        # Optional: Fallback to check 'Enque Processed' folder removed for simplicity,
        # assuming move logic is reliable or marking before move is sufficient.
        if not result: logger.warning(f"Failed to mark email {mapping.email_id} as read directly.")

        return result
    except Exception as e: logger.error(f"Error in mark_email_as_read_by_task_id for task {task_id}: {str(e)}"); return False
