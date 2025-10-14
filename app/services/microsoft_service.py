import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent import Agent
from app.models.microsoft import (EmailSyncConfig, MailboxConnection,
                                  MicrosoftIntegration, MicrosoftToken)
from app.services.microsoft_auth_service import MicrosoftAuthService
from app.services.microsoft_email_service import MicrosoftEmailService
from app.services.microsoft_graph_client import MicrosoftGraphClient
from app.services.microsoft_user_service import MicrosoftUserService
from app.utils.logger import logger


class MicrosoftGraphService:
    def __init__(self, db: Session):
        self.db = db
        self.integration = self._get_active_integration()
        
        self.user_service = MicrosoftUserService(db)
        self.auth_service = MicrosoftAuthService(db, self.integration, self.user_service)
        self.graph_client = MicrosoftGraphClient()
        self.email_service = MicrosoftEmailService(db, self.graph_client)

        if self.integration:
            pass
        elif self.auth_service.has_env_config:
            logger.info("Microsoft service initialized with environment variables (no DB integration)")
        else:
            logger.warning("Microsoft service initialized without integration or environment variables")

    def _get_active_integration(self) -> Optional[MicrosoftIntegration]:
        return self.db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()

    def get_application_token(self) -> str:
        return self.auth_service.get_application_token()

    def get_auth_url(
        self,
        redirect_uri: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        state: Optional[str] = None,
        prompt: Optional[str] = "consent"
    ) -> str:
        return self.auth_service.get_auth_url(redirect_uri, scopes, state, prompt)

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: Optional[str] = None) -> MicrosoftToken:
        return self.auth_service.exchange_code_for_token(code, redirect_uri, state)

    def sync_emails(self, sync_config: EmailSyncConfig):
        return self.email_service.sync_emails(sync_config, self._get_user_email_for_sync)

    def send_reply_email(self, task_id: int, reply_content: str, agent: Agent, attachment_ids: List[int] = None, to_recipients: List[str] = None, cc_recipients: List[str] = None, bcc_recipients: List[str] = None) -> bool:
        return self.email_service.send_reply_email(task_id, reply_content, agent, attachment_ids, to_recipients, cc_recipients, bcc_recipients)

    def send_new_email(self, mailbox_email: str, recipient_email: str, subject: str, html_body: str, attachment_ids: List[int] = None, task_id: Optional[int] = None, cc_recipients: List[str] = None, bcc_recipients: List[str] = None) -> bool:
        return self.email_service.send_new_email(mailbox_email, recipient_email, subject, html_body, attachment_ids, task_id, cc_recipients, bcc_recipients)

    async def send_email_with_user_token(
        self, user_access_token: str, sender_mailbox_email: str, recipient_email: str,
        subject: str, html_body: str, task_id: Optional[int] = None
    ) -> bool:
        return await self.email_service.send_email_with_user_token(user_access_token, sender_mailbox_email, recipient_email, subject, html_body, task_id)

    async def send_teams_activity_notification(self, agent_id: int, title: str, message: str, link_to_ticket: str, subdomain: str):
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent or not agent.microsoft_id:
            logger.warning(f"Cannot send Teams notification: Agent {agent_id} not found or not linked to a Microsoft account.")
            return

        if not agent.teams_notifications_enabled:
            logger.info(f"Skipping Teams notification for agent {agent_id} because they have it disabled.")
            return

        try:
            access_token = self.get_application_token()
            if not access_token:
                logger.error(f"Could not obtain a valid application token to send Teams notification.")
                return

            await self.graph_client.send_teams_activity_notification(access_token, agent.microsoft_id, title, message, link_to_ticket, subdomain)
        except HTTPException as http_exc:
            if http_exc.status_code == 401:
                logger.error(f"Authorization error sending Teams notification to agent {agent_id}. The token may be invalid and requires re-authentication.")
            else:
                logger.error(f"HTTP error sending Teams notification to agent {agent_id}: {http_exc.status_code} - {http_exc.detail}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending Teams notification to agent {agent_id}: {str(e)}", exc_info=True)

    def _get_user_email_for_sync(self, config: EmailSyncConfig = None) -> Tuple[Optional[str], Optional[MicrosoftToken]]:
        token: Optional[MicrosoftToken] = None
        mailbox_email: Optional[str] = None
        if config:
            mailbox = self.db.query(MailboxConnection).filter(MailboxConnection.id == config.mailbox_connection_id).first()
            if not mailbox:
                logger.warning(f"MailboxConnection not found for sync config ID: {config.id}")
                return None, None
            mailbox_email = mailbox.email
            token = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox.id,
                MicrosoftToken.expires_at > datetime.utcnow()
            ).order_by(MicrosoftToken.created_at.desc()).first()

            if not token:
                logger.info(f"No active token for MailboxConnection ID: {mailbox.id}. Looking for refreshable token.")
                expired_refreshable_token = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox.id,
                    MicrosoftToken.refresh_token.isnot(None),
                    MicrosoftToken.refresh_token != ""
                ).order_by(MicrosoftToken.expires_at.desc()).first()

                if expired_refreshable_token:
                    logger.info(f"Found refreshable token ID: {expired_refreshable_token.id} for MailboxConnection ID: {mailbox.id}. Attempting synchronous refresh.")
                    try:
                        token = self.auth_service.refresh_token(expired_refreshable_token)
                        logger.info(f"Successfully refreshed token ID: {token.id} synchronously for MailboxConnection ID: {mailbox.id}.")
                    except HTTPException as e:
                        logger.error(f"Synchronous refresh failed for token ID {expired_refreshable_token.id} (MailboxConnection ID: {mailbox.id}): {e.detail}")
                        token = None
                    except Exception as e:
                        logger.error(f"Unexpected error during synchronous refresh for token ID {expired_refreshable_token.id} (MailboxConnection ID: {mailbox.id}): {str(e)}", exc_info=True)
                        token = None
                else:
                    logger.warning(f"No refreshable token found for MailboxConnection ID: {mailbox.id} (Email: {mailbox_email})")
            
            if not token:
                logger.warning(f"No valid token could be obtained for MailboxConnection ID: {mailbox.id} (Email: {mailbox_email}) after checking and attempting refresh.")
                return None, None
        else:
            token = self.get_most_recent_valid_token()
            if not token:
                logger.warning("No recent valid token found across all mailboxes (via get_most_recent_valid_token).")
                return None, None
            mailbox = self.db.query(MailboxConnection).filter(MailboxConnection.id == token.mailbox_connection_id).first()
            if not mailbox:
                logger.error(f"MailboxConnection not found for token ID: {token.id}, MailboxConnection ID: {token.mailbox_connection_id}")
                return None, None
            mailbox_email = mailbox.email
        return mailbox_email, token

    def get_most_recent_valid_token(self) -> Optional[MicrosoftToken]:
        token = self.db.query(MicrosoftToken).filter(MicrosoftToken.expires_at > datetime.utcnow()).order_by(MicrosoftToken.created_at.desc()).first()
        if token:
            return token
        
        expired_refreshable_token = self.db.query(MicrosoftToken).filter(
            MicrosoftToken.refresh_token.isnot(None),
            MicrosoftToken.refresh_token != ""
        ).order_by(MicrosoftToken.expires_at.desc()).first()

        if expired_refreshable_token:
            logger.info(f"No active token found by get_most_recent_valid_token. Found refreshable token ID: {expired_refreshable_token.id}. Attempting synchronous refresh.")
            try:
                refreshed_token = self.auth_service.refresh_token(expired_refreshable_token)
                logger.info(f"Successfully refreshed token ID: {refreshed_token.id} synchronously via get_most_recent_valid_token.")
                return refreshed_token
            except HTTPException as e:
                logger.error(f"Synchronous refresh failed in get_most_recent_valid_token for token ID {expired_refreshable_token.id}: {e.detail}")
            except Exception as e:
                logger.error(f"Unexpected error during synchronous refresh in get_most_recent_valid_token for token ID {expired_refreshable_token.id}: {str(e)}", exc_info=True)
        
        logger.warning("No valid or refreshable Microsoft token found by get_most_recent_valid_token."); return None

    async def check_and_refresh_all_tokens_async(self) -> None:
        """Check and refresh all expiring tokens asynchronously. This is the primary refresh mechanism."""
        try:
            expiring_soon = datetime.utcnow() + timedelta(minutes=10)
            tokens_to_check = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.expires_at < expiring_soon,
                MicrosoftToken.refresh_token.isnot(None),
                MicrosoftToken.refresh_token != ""
            ).all()
            refreshed_count = 0
            failed_count = 0
            for token_to_refresh in tokens_to_check:
                try:
                    logger.info(f"Token ID {token_to_refresh.id} for mailbox_connection {token_to_refresh.mailbox_connection_id} needs refresh. Attempting.")
                    await self.auth_service.refresh_token_async(token_to_refresh)
                    refreshed_count += 1
                except Exception as e:
                    logger.warning(f"Failed to refresh token ID {token_to_refresh.id} for mailbox_connection {token_to_refresh.mailbox_connection_id}: {e}")
                    failed_count += 1
            if refreshed_count > 0 or failed_count > 0:
                logger.info(f"Token refresh check complete. Refreshed: {refreshed_count}, Failed: {failed_count}")
        except Exception as e:
            logger.error(f"Error during periodic token refresh check: {str(e)}", exc_info=True)


def get_microsoft_service(db: Session) -> MicrosoftGraphService:
    return MicrosoftGraphService(db)

def mark_email_as_read_by_task_id(db: Session, task_id: int) -> bool:
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or task.status != "Open": return False
        mapping = db.query(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == task_id).first()
        if not mapping: logger.error(f"No mapping found for ticket #{task_id}"); return False
        logger.info(f"Found mapping for ticket #{task_id}, email_id: {mapping.email_id}")
        service = MicrosoftGraphService(db)
        app_token = service.get_application_token()
        if not app_token: logger.error(f"Could not get app token to mark email as read for task {task_id}"); return False
        if not task.mailbox_connection_id: logger.error(f"Task {task_id} has no mailbox_connection_id."); return False
        mailbox = db.query(MailboxConnection).filter(MailboxConnection.id == task.mailbox_connection_id).first()
        if not mailbox: logger.error(f"MailboxConnection not found for ID {task.mailbox_connection_id}"); return False
        result = service.graph_client.mark_email_as_read(app_token, mailbox.email, mapping.email_id)
        if not result: logger.warning(f"Failed to mark email {mapping.email_id} as read directly.")
        return result
    except Exception as e:
        logger.error(f"Error in mark_email_as_read_by_task_id for task {task_id}: {str(e)}")
        return False
