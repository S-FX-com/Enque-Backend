# ⚡ Optimized imports for performance
import orjson  
import asyncio
import requests
import urllib.parse
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from sqlalchemy.orm import Session, joinedload
from app.core.config import settings

try:
    from app.services.cache_service import cache_service, cached_microsoft_graph
    from app.services.rate_limiter import rate_limiter, rate_limited
    PERFORMANCE_SERVICES_AVAILABLE = True
except ImportError:
    PERFORMANCE_SERVICES_AVAILABLE = False
    def cached_microsoft_graph(ttl=300, key_prefix="msg"):
        def decorator(func):
            return func
        return decorator
    def rate_limited(tenant_id_arg="tenant_id", resource="graph"):
        def decorator(func):
            return func
        return decorator
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig, MailboxConnection
from app.schemas.microsoft import EmailData, EmailAddress, EmailAttachment, MicrosoftTokenCreate, EmailTicketMappingCreate
from app.schemas.task import TaskStatus 
from app.models.task import Task, TicketBody
from app.models.agent import Agent
from app.models.user import User
from app.models.comment import Comment
from app.models.activity import Activity
from app.models.workspace import Workspace
from app.models.ticket_attachment import TicketAttachment
from app.services.utils import get_or_create_user
from app.utils.logger import logger, log_important
from app.core.socketio import emit_comment_update_sync 
import base64
import json 
from bs4 import BeautifulSoup
from fastapi import HTTPException, status
import httpx 
from urllib.parse import urlencode
import uuid
import time
from sqlalchemy import or_, and_, desc
import re
from app.utils.image_processor import extract_base64_images  
from app.services.token_service import TokenService 
import boto3  

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

        self.token_service = TokenService(db, self.integration)

        self._app_token = None
        self._app_token_expires_at = datetime.utcnow()
        
        # ⚡ Initialize performance services
        self.tenant_id = self.integration.tenant_id if self.integration else settings.MICROSOFT_TENANT_ID

        if self.integration:
            pass  
        elif self.has_env_config:
            logger.info("Microsoft service initialized with environment variables (no DB integration)")
        else:
            logger.warning("Microsoft service initialized without integration or environment variables")

    def _init_cache_if_needed(self):
        """Initialize cache service if needed"""
        if PERFORMANCE_SERVICES_AVAILABLE:
            try:
                # Try to initialize cache in sync context
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if not loop.is_running():
                        loop.run_until_complete(cache_service.connect())
                        logger.info("🚀 Cache service connected for Microsoft Graph")
                except RuntimeError:
                    # No event loop, will use memory cache only
                    pass
            except Exception as e:
                logger.warning(f"Cache initialization failed: {e}")

    def _get_active_integration(self) -> Optional[MicrosoftIntegration]:
        """Get the active Microsoft integration"""
        return self.db.query(MicrosoftIntegration).filter(MicrosoftIntegration.is_active == True).first()

    def _download_file_from_s3(self, s3_url: str) -> Optional[bytes]:
        """Download file content from S3 URL"""
        try:
            # Initialize S3 client (using hardcoded credentials for now)
            s3_client = boto3.client(
                's3',
                aws_access_key_id="AKIAQ3EGRIILJHGBQJOZ",
                aws_secret_access_key="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",
                region_name="us-east-2"
            )
            
            # Extract bucket and key from S3 URL
            # Format: https://enque.s3.us-east-2.amazonaws.com/path/to/file
            parts = s3_url.replace("https://", "").split("/", 1)
            if len(parts) < 2:
                logger.error(f"Invalid S3 URL format: {s3_url}")
                return None
                
            bucket_name = parts[0].split(".")[0]  # Extract bucket name from hostname
            s3_key = parts[1]  # Everything after first slash is the key
            
            # Download file from S3
            response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
            file_content = response['Body'].read()
            
            return file_content
            
        except Exception as e:
            logger.error(f"❌ Error downloading file from S3: {str(e)}")
            return None

    def get_application_token(self) -> str:
        """Get an application token using client credentials flow"""
        if self._app_token and self._app_token_expires_at > datetime.utcnow():
            return self._app_token

        if not self.integration and not self.has_env_config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active Microsoft integration found")

        tenant_id = self.integration.tenant_id if self.integration else settings.MICROSOFT_TENANT_ID
        client_id = self.integration.client_id if self.integration else settings.MICROSOFT_CLIENT_ID
        client_secret = self.integration.client_secret if self.integration else settings.MICROSOFT_CLIENT_SECRET

        # For application tokens, we still need to use the specific tenant endpoint
        token_endpoint = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
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

        client_id = self.integration.client_id if self.integration else settings.MICROSOFT_CLIENT_ID

        final_redirect_uri = redirect_uri or (self.integration.redirect_uri if self.integration else settings.MICROSOFT_REDIRECT_URI)
        if not final_redirect_uri:
             final_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
             logger.warning(f"No redirect_uri provided or configured, falling back to default: {final_redirect_uri}")

        default_scopes = ["offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared", "User.Read"]
        final_scopes = scopes if scopes else default_scopes
        scope_string = " ".join(final_scopes)
        
        # Use the common endpoint directly for multitenant support
        auth_endpoint = self.auth_url  # This is now already set to /common in config
        
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
        
        # Use the common endpoint directly for multitenant support
        token_endpoint = self.token_url  # This is now already set to /common in config
        try:
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status()
            token_data = response.json()
            refresh_token_val = token_data.get("refresh_token", "")
            user_info = self._get_user_info(token_data["access_token"])
            mailbox_email = user_info.get("mail")
            if not mailbox_email:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not get email address from Microsoft user info")
            workspace_id: Optional[int] = None
            agent_id: Optional[int] = None
            connection_id: Optional[int] = None  # Added for reconnection flow
            is_reconnect: bool = False  # Flag to indicate reconnection
            
            if state:
                try:
                    missing_padding = len(state) % 4
                    if missing_padding: state += '=' * (4 - missing_padding)
                    decoded_state_json = base64.urlsafe_b64decode(state).decode('utf-8')
                    state_data = json.loads(decoded_state_json)
                    ws_id_str = state_data.get('workspace_id')
                    ag_id_str = state_data.get('agent_id')
                    conn_id_str = state_data.get('connection_id')  # Extract connection_id from state
                    is_reconnect_str = state_data.get('is_reconnect')  # Extract reconnect flag
                    
                    if ws_id_str: workspace_id = int(ws_id_str)
                    if ag_id_str: agent_id = int(ag_id_str)
                    if conn_id_str: connection_id = int(conn_id_str)
                    if is_reconnect_str and is_reconnect_str.lower() == 'true': is_reconnect = True
                    
                    logger.info(f"Extracted from Base64 state: workspace_id={workspace_id}, agent_id={agent_id}, connection_id={connection_id}, is_reconnect={is_reconnect}")
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
            
            # For reconnections, find the existing mailbox connection by ID
            mailbox_connection = None
            if is_reconnect and connection_id:
                # Find the existing mailbox connection
                mailbox_connection = self.db.query(MailboxConnection).filter(
                    MailboxConnection.id == connection_id,
                    MailboxConnection.workspace_id == workspace_id
                ).first()
                
                if not mailbox_connection:
                    logger.error(f"Could not find mailbox connection with ID {connection_id} for workspace {workspace_id}")
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Mailbox connection with ID {connection_id} not found")
                
                # Update the connection with new email address if it changed
                if mailbox_connection.email != mailbox_email:
                    logger.info(f"Updating email address for connection {connection_id} from {mailbox_connection.email} to {mailbox_email}")
                    mailbox_connection.email = mailbox_email
                    mailbox_connection.display_name = user_info.get("displayName", "Microsoft User")
                
                # Delete old token(s) associated with this connection
                old_tokens = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox_connection.id
                ).all()
                
                if old_tokens:
                    for old_token in old_tokens:
                        self.db.delete(old_token)
                    logger.info(f"Deleted {len(old_tokens)} old token(s) for mailbox connection {connection_id}")
                
                self.db.commit()
            else:
                # Normal flow - look for existing connection by email or create new one
                mailbox_connection = self.db.query(MailboxConnection).filter(
                    MailboxConnection.email == mailbox_email, 
                    MailboxConnection.workspace_id == workspace.id
                ).first()
                
            if not mailbox_connection:
                mailbox_connection = MailboxConnection(
                    email=mailbox_email, display_name=user_info.get("displayName", "Microsoft User"),
                    workspace_id=workspace.id, created_by_agent_id=current_agent.id, is_active=True)
                self.db.add(mailbox_connection); self.db.commit(); self.db.refresh(mailbox_connection)
            
            # Create new token for the connection
            token = MicrosoftToken(
                integration_id=self.integration.id, agent_id=current_agent.id, mailbox_connection_id=mailbox_connection.id,
                access_token=token_data["access_token"], refresh_token=refresh_token_val, token_type=token_data["token_type"],
                expires_at=datetime.utcnow() + timedelta(seconds=token_data["expires_in"]))
            self.db.add(token); self.db.commit(); self.db.refresh(token)
            
            # Ensure there's a sync config for the connection
            existing_config = self.db.query(EmailSyncConfig).filter(
                EmailSyncConfig.mailbox_connection_id == mailbox_connection.id, 
                EmailSyncConfig.workspace_id == workspace.id
            ).first()
            
            if not existing_config:
                new_config = EmailSyncConfig(
                    integration_id=self.integration.id, mailbox_connection_id=mailbox_connection.id, folder_name="Inbox",
                    sync_interval=1, default_priority="Medium", auto_assign=False, workspace_id=workspace.id, is_active=True)
                self.db.add(new_config); self.db.commit()
            elif not existing_config.is_active:
                # If reconnecting a connection with an inactive config, reactivate it
                existing_config.is_active = True
                self.db.add(existing_config); self.db.commit()
                
            logger.info(f"Successfully {'reconnected' if is_reconnect else 'connected'} mailbox {mailbox_email} for workspace {workspace_id}")
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
        
        # Use the common endpoint directly for multitenant support
        token_endpoint = self.token_url  # This is now already set to /common in config
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
        
        # Use the common endpoint directly for multitenant support
        token_endpoint = self.token_url  # This is now already set to /common in config
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

    @cached_microsoft_graph(ttl=3600, key_prefix="user_info")  # Cache for 1 hour
    @rate_limited(resource="user_info")
    async def _get_user_info_cached(self, access_token: str) -> Dict[str, Any]:
        """Get user info with caching and rate limiting"""
        try:
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            
            # Use httpx for async requests
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.graph_url}/me", headers=headers)
                response.raise_for_status()
                
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get user info: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to get user info: {str(e)}")

    def _get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Legacy sync version - tries cache first, then calls API"""
        try:
            # Try to use cached version in sync context
            if PERFORMANCE_SERVICES_AVAILABLE:
                try:
                    # Run async method in sync context
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Create new task if loop is already running
                        task = asyncio.create_task(self._get_user_info_cached(access_token))
                        return asyncio.run_coroutine_threadsafe(task, loop).result(timeout=10)
                    else:
                        return loop.run_until_complete(self._get_user_info_cached(access_token))
                except Exception as cache_error:
                    logger.warning(f"Cache failed, falling back to direct API: {cache_error}")
            
            # Fallback to direct API call
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            response = requests.get(f"{self.graph_url}/me", headers=headers)
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"Failed to get user info: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to get user info: {str(e)}")

    def _process_html_body(self, html_content: str, attachments: List[EmailAttachment], context: str = "email") -> str:
        """Process HTML content to handle things like CID-referenced images."""
        if not html_content:
            return html_content
            
        processed_html = html_content
        
        try:
            # 1. Primero, manejamos las imágenes CID (inline attachments)
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
                            content_type = matching_attachment.content_type
                            base64_data = matching_attachment.contentBytes
                            if content_type and base64_data:
                                img_tag['src'] = f"data:{content_type};base64,{base64_data}"
                                image_tags_updated += 1
                
                if image_tags_updated > 0:
                    processed_html = str(soup)
                    logger.info(f"Processed HTML for {context}, updated {image_tags_updated} CID image tags.")
        
            # 2. Extraer el ID del ticket del contexto
            ticket_id = None
            if 'ticket' in context:
                match = re.search(r'ticket\s+(\d+)', context)
                if match:
                    ticket_id = int(match.group(1))
            
            # Si tenemos un ticket_id, procesamos las imágenes base64
            if ticket_id:
                # Procesar y extraer todas las imágenes base64 incrustadas
                processed_html, extracted_images = extract_base64_images(processed_html, ticket_id)
                if extracted_images:
                    logger.info(f"Extracted {len(extracted_images)} base64 images from {context} for ticket {ticket_id}")
            
            return processed_html
            
        except Exception as e:
            logger.error(f"Error processing HTML for {context}: {e}", exc_info=True)
            return html_content

    def sync_emails(self, sync_config: EmailSyncConfig):
        user_email, token = self._get_user_email_for_sync(sync_config) # This calls the sync check_and_refresh_all_tokens
        if not user_email or not token:
            logger.warning(f"[MAIL SYNC] No valid email or token found for sync config ID: {sync_config.id}. Skipping sync.")
            return []
        try:
            # Use user token instead of application token for multitenant support
            user_access_token = token.access_token
            # Using user access token
            
            emails = self.get_mailbox_emails(user_access_token, user_email, sync_config.folder_name, top=50, filter_unread=True)
            
            if not emails:
                # No unread emails
                sync_config.last_sync_time = datetime.utcnow(); self.db.commit(); return []
            # Found unread emails
            created_tasks_count = 0; added_comments_count = 0
            
            # 🔧 REACTIVADO: Movimiento de emails con búsqueda mejorada para manejar cambios de Message ID
            processed_folder_id = self._get_or_create_processed_folder(user_access_token, user_email, "Enque Processed")
            if not processed_folder_id: 
                logger.error(f"[MAIL SYNC] Could not get or create 'Enque Processed' folder for {user_email}. Emails will not be moved.")
            else:
                pass  # Folder ready for email processing
            system_agent = self.db.query(Agent).filter(Agent.email == "system@enque.cc").first() or self.db.query(Agent).order_by(Agent.id.asc()).first()
            if not system_agent: logger.error("No system agent found. Cannot process emails."); return []
            
            notification_subject_patterns = [
                "New ticket #", 
                "Ticket #",
                "New response to your ticket #",
                "Enque 🎟️",  
                "[ID:",      
                "has been assigned"
            ]
            
            system_domains = self._get_system_domains_for_workspace(sync_config.workspace_id)
            
            for email_data in emails:
                email_id = email_data.get("id")
                email_subject = email_data.get("subject", "")
                sender_email = email_data.get("from", {}).get("emailAddress", {}).get("address", "")
                
                if not email_id: logger.warning("[MAIL SYNC] Skipping email with missing ID."); continue
                try:
                    existing_mapping = self.db.query(EmailTicketMapping).filter(EmailTicketMapping.email_id == email_id).first()
                    if existing_mapping:
                        ticket_exists = self.db.query(Task).filter(Task.id == existing_mapping.ticket_id).first()
                        if not ticket_exists:
                            logger.warning(f"🚨 ORPHANED MAPPING: Email {email_id} maps to non-existent ticket #{existing_mapping.ticket_id}. Cleaning up...")
                            self.db.delete(existing_mapping)
                            self.db.commit()
                            logger.info(f"✅ Cleaned orphaned mapping for email {email_id}")
                        else:
                            mapping_subject = existing_mapping.email_subject or ""
                            current_subject = email_subject or ""
                            
                            if mapping_subject and current_subject and mapping_subject.lower() != current_subject.lower():
                                logger.warning(f"🚨 INCONSISTENT MAPPING: Email {email_id} mapped to ticket #{existing_mapping.ticket_id}")
                                logger.warning(f"   Removing inconsistent mapping...")
                                self.db.delete(existing_mapping)
                                self.db.commit()
                                logger.info(f"✅ Cleaned inconsistent mapping for email {email_id}")
                                # Continue processing as if it's a new email
                            else:
                                continue
                    
                    email_content = self._get_full_email(user_access_token, user_email, email_id)
                    if not email_content: logger.warning(f"[MAIL SYNC] Could not retrieve full content for email ID {email_id}. Skipping."); continue
                    conversation_id = email_content.get("conversationId")
                    
                    existing_mapping_by_conv = None
                    if conversation_id:
                        existing_mapping_by_conv = self.db.query(EmailTicketMapping).filter(EmailTicketMapping.email_conversation_id == conversation_id).order_by(EmailTicketMapping.created_at.asc()).first()
                    
                    if not existing_mapping_by_conv and email_subject:
                        id_match = re.search(r'\[ID:(\d+)\]', email_subject, re.IGNORECASE)
                        if id_match:
                            ticket_id_from_subject = int(id_match.group(1))
                            existing_mapping_by_conv = self.db.query(EmailTicketMapping).filter(EmailTicketMapping.ticket_id == ticket_id_from_subject).order_by(EmailTicketMapping.created_at.asc()).first()
                            if existing_mapping_by_conv:
                                logger.info(f"[MAIL SYNC] Found existing ticket {ticket_id_from_subject} by subject ID for email {email_id}")
                        
                    if existing_mapping_by_conv:
                        email = self._parse_email_data(email_content, user_email, sync_config.workspace_id)
                        if not email: logger.warning(f"[MAIL SYNC] Could not parse reply email data for email ID {email_id}. Skipping comment creation."); continue
                        reply_user = get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown", workspace_id=sync_config.workspace_id)
                        if not reply_user: logger.error(f"Could not get or create user for reply email sender: {email.sender.address}"); continue
                        workspace = self.db.query(Workspace).filter(Workspace.id == sync_config.workspace_id).first()
                        if not workspace: logger.error(f"Workspace ID {sync_config.workspace_id} not found for reply. Skipping comment creation."); continue
                        processed_reply_html = self._process_html_body(email.body_content, email.attachments, f"reply email {email.id}")
                        
                        processed_reply_html = re.sub(r'^<p><strong>From:</strong>.*?</p>', '', processed_reply_html, flags=re.DOTALL | re.IGNORECASE)
                        
                        special_metadata = f'<original-sender>{reply_user.name}|{reply_user.email}</original-sender>'
                        
                        content_to_store = special_metadata + processed_reply_html
                        s3_html_url = None
                        
                        try:
                            if content_to_store and content_to_store.strip():
                                from app.services.s3_service import get_s3_service
                                s3_service = get_s3_service()
                                
                                content_length = len(content_to_store)
                                should_migrate_to_s3 = (
                                    content_length > 65000 or  # Más de 65KB (límite aproximado de TEXT)
                                    s3_service.should_store_html_in_s3(content_to_store)
                                )
                                
                                if should_migrate_to_s3:
                                    import uuid
                                    temp_id = str(uuid.uuid4())
                                    
                                    s3_url = s3_service.upload_html_content(
                                        html_content=content_to_store,
                                        filename=f"temp-comment-{temp_id}.html",
                                        folder="comments"
                                    )
                                    
                                    s3_html_url = s3_url
                                    content_to_store = f"[MIGRATED_TO_S3] Content moved to S3: {s3_url}"
                        except Exception as e:
                            logger.error(f"❌ [MAIL SYNC] Error pre-migrating content to S3: {str(e)}")
                            content_to_store = special_metadata + processed_reply_html
                            s3_html_url = None

                        new_comment = Comment(
                            ticket_id=existing_mapping_by_conv.ticket_id,
                            agent_id=system_agent.id,
                            workspace_id=workspace.id,
                            content=content_to_store,  
                            s3_html_url=s3_html_url,  
                            is_private=False
                        )

                        if email.attachments:
                            non_inline_attachments = [att for att in email.attachments if not att.is_inline and att.contentBytes]
                            if non_inline_attachments:
                                for att in non_inline_attachments:
                                    try:
                                        decoded_bytes = base64.b64decode(att.contentBytes)
                                        
                                        s3_url = None
                                        try:
                                            from app.services.s3_service import get_s3_service
                                            s3_service = get_s3_service()
                                            
                                            folder = "images" if att.content_type.startswith("image/") else "documents"
                                            
                                            s3_url = s3_service.upload_file(
                                                file_content=decoded_bytes,
                                                filename=att.name,
                                                content_type=att.content_type,
                                                folder=folder
                                            )
                                            
                                            logger.info(f"📎 Adjunto '{att.name}' subido a S3: {s3_url}")
                                            
                                        except Exception as s3_error:
                                            logger.error(f"❌ Error subiendo adjunto '{att.name}' a S3: {str(s3_error)}")
                                            pass
                                        
                                        db_attachment = TicketAttachment(
                                            file_name=att.name,
                                            content_type=att.content_type,
                                            file_size=att.size,
                                            s3_url=s3_url,  
                                            content_bytes=decoded_bytes if not s3_url else None  # Solo bytes si S3 falló
                                        )
                                        new_comment.attachments.append(db_attachment) # SQLAlchemy manejará el comment_id
                                        
                                    except Exception as e:
                                        logger.error(f"Error al procesar/decodificar adjunto '{att.name}' para comentario en ticket {existing_mapping_by_conv.ticket_id}: {e}", exc_info=True)
                        
                        self.db.add(new_comment)

                        if s3_html_url and not s3_html_url.endswith(f"comment-{new_comment.id}.html"):
                            try:
                                self.db.flush()
                                
                                from app.services.s3_service import get_s3_service
                                s3_service = get_s3_service()
                                
                                original_content = special_metadata + processed_reply_html
                                
                                final_s3_url = s3_service.store_comment_html(new_comment.id, original_content)
                                
                                new_comment.s3_html_url = final_s3_url
                                new_comment.content = f"[MIGRATED_TO_S3] Content moved to S3: {final_s3_url}"
                            except Exception as e:
                                logger.warning(f"⚠️ [MAIL SYNC] Could not rename S3 file for comment {new_comment.id}: {str(e)}")

                        ticket_to_update = self.db.query(Task).filter(Task.id == existing_mapping_by_conv.ticket_id).first()
                        
                        try:
                            from app.services.workflow_service import WorkflowService
                            
                            if email.body_content and email.body_content.strip():
                                workflow_service = WorkflowService(self.db)
                                
                                workflow_context = {
                                    'task_id': existing_mapping_by_conv.ticket_id,
                                    'comment_id': None,  
                                    'agent_id': system_agent.id,  
                                    'workspace_id': workspace.id,
                                    'task_status': ticket_to_update.status if ticket_to_update else 'unknown',
                                    'task_priority': getattr(ticket_to_update, 'priority', 'normal') if ticket_to_update else 'normal',
                                    'is_private': False,
                                    'is_from_email': True,
                                    'email_sender': reply_user.email,
                                    'email_sender_name': reply_user.name
                                }
                                
                                workflow_results = workflow_service.process_message_for_workflows(
                                    email.body_content,
                                    workspace.id,
                                    workflow_context
                                )
                                
                                if workflow_results:
                                    logger.info(f"[MAIL SYNC] Executed {len(workflow_results)} workflows for email reply on ticket {existing_mapping_by_conv.ticket_id}")
                                    for result in workflow_results:
                                        logger.info(f"[MAIL SYNC] Workflow executed: {result.get('workflow_name')} - {result.get('trigger')}")
                                
                        except Exception as workflow_error:
                            logger.error(f"[MAIL SYNC] Error processing workflows for email reply: {str(workflow_error)}")
                        
                        user_activity = Activity(
                            agent_id=None,  
                            action=f"{reply_user.name} replied via email",  
                            source_type="Comment",
                            source_id=existing_mapping_by_conv.ticket_id,  
                            workspace_id=workspace.id
                        )
                        self.db.add(user_activity)
                        
                        reply_email_mapping = EmailTicketMapping(
                            email_id=email.id, email_conversation_id=email.conversation_id, ticket_id=existing_mapping_by_conv.ticket_id,
                            email_subject=email.subject, email_sender=f"{email.sender.name} <{email.sender.address}>",
                            email_received_at=email.received_at, is_processed=True)
                        self.db.add(reply_email_mapping)
                        
                        if ticket_to_update and ticket_to_update.status == TaskStatus.WITH_USER:
                             ticket_to_update.status = TaskStatus.IN_PROGRESS; self.db.add(ticket_to_update)
                             logger.info(f"[MAIL SYNC] Ticket {existing_mapping_by_conv.ticket_id} status changed from WITH_USER to IN_PROGRESS after user reply")
                        elif ticket_to_update and ticket_to_update.status == TaskStatus.CLOSED:
                             ticket_to_update.status = TaskStatus.IN_PROGRESS; self.db.add(ticket_to_update)
                             logger.info(f"[MAIL SYNC] Ticket {existing_mapping_by_conv.ticket_id} status changed from CLOSED to IN_PROGRESS after user reply")
                        elif ticket_to_update: pass  
                        else: logger.warning(f"[MAIL SYNC] Could not find Ticket ID {existing_mapping_by_conv.ticket_id} to potentially update status after user reply.")
                        
                        # Update last_update when user replies via email
                        if ticket_to_update:
                            ticket_to_update.last_update = datetime.utcnow()
                            self.db.add(ticket_to_update)
                            logger.info(f"[MAIL SYNC] Updated last_update for ticket {existing_mapping_by_conv.ticket_id} after user reply")
                        
                        self.db.commit(); added_comments_count += 1
                        
                        try:
                            self.db.flush()
                            
                            full_content = ""
                            if new_comment.s3_html_url:
                                full_content = special_metadata + processed_reply_html
                            else:
                                full_content = new_comment.content or ""
                            attachments_data = []
                            for attachment in new_comment.attachments:
                                attachments_data.append({
                                    'id': attachment.id,
                                    'file_name': attachment.file_name,
                                    'content_type': attachment.content_type,
                                    'file_size': attachment.file_size,
                                    'download_url': attachment.s3_url  
                                })
                            
                            comment_data = {
                                'id': new_comment.id,
                                'ticket_id': existing_mapping_by_conv.ticket_id,
                                'agent_id': None,  
                                'user_id': reply_user.id,  
                                'user_name': reply_user.name,
                                'content': full_content, 
                                'is_private': False,
                                'created_at': new_comment.created_at.isoformat() if new_comment.created_at else None,
                                'attachments': attachments_data  
                            }
                            emit_comment_update_sync(
                                workspace_id=workspace.id,
                                comment_data=comment_data
                            )
                            
                            logger.info(f"📤 [MAIL SYNC] Socket.IO comment_updated event queued for workspace {workspace.id}")
                        except Exception as e:
                            logger.error(f"❌ [MAIL SYNC] Error emitting Socket.IO event for comment {new_comment.id}: {str(e)}")
                        
                        if processed_folder_id: 
                            new_reply_id = self._move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                            if new_reply_id and new_reply_id != email_id:
                                logger.info(f"📧 Reply email moved - ID changed from {email_id[:50]}... to {new_reply_id[:50]}...")
                                self._update_all_email_mappings_for_ticket(existing_mapping_by_conv.ticket_id, email_id, new_reply_id)
                        continue
                    else:
                        
                        email_subject_lower = email_subject.lower()
                        
                        is_system_notification = False
                        
                        sender_email_lower = sender_email.lower()
                        mailbox_email = user_email.lower()

                        if any(domain in sender_email_lower for domain in system_domains) or sender_email_lower == mailbox_email:
                            for pattern in notification_subject_patterns:
                                if pattern.lower() in email_subject_lower:
                                    is_system_notification = True
                                    
                                    self._mark_email_as_read(user_access_token, user_email, email_id)
                                    if processed_folder_id:
                                        self._move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                                    break
                        
                        if is_system_notification:
                            logger.info(f"[MAIL SYNC] Skipping system notification email: {email_subject}")
                            continue
                        
                        logger.info(f"[MAIL SYNC] Email ID {email_id} is a new conversation. Creating new ticket.")
                        email = self._parse_email_data(email_content, user_email, sync_config.workspace_id)
                        if not email: 
                            logger.warning(f"[MAIL SYNC] Could not parse new email data for email ID {email_id}. Skipping ticket creation.")
                            continue
                        
                        sender_email = email.sender.address if email.sender else ""
                        if sender_email.lower() == user_email.lower() or "microsoftexchange" in sender_email.lower():
                            logger.warning(f"[MAIL SYNC] Email from system address or self ({sender_email}). Marking as read and skipping ticket creation.")
                            self._mark_email_as_read(user_access_token, user_email, email_id)
                            if processed_folder_id:
                                self._move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                            continue
                        
                        task = self._create_task_from_email(email, sync_config, system_agent)
                        if task:
                            created_tasks_count += 1; logger.info(f"[MAIL SYNC] Created Task ID {task.id} from Email ID {email.id}.")
                            email_mapping = EmailTicketMapping(
                                email_id=email.id, email_conversation_id=email.conversation_id, ticket_id=task.id,
                                email_subject=email.subject, email_sender=f"{email.sender.name} <{email.sender.address}>",
                                email_received_at=email.received_at, is_processed=True)
                            self.db.add(email_mapping)
                            try:
                                self.db.commit()
                                if processed_folder_id:
                                    new_id = self._move_email_to_folder(user_access_token, user_email, email_id, processed_folder_id)
                                    if new_id and new_id != email_id:
                                        # 🔧 MEJORADO: Email ID changed after move, updating ALL related mappings
                                        logger.info(f"📧 Email moved - ID changed from {email_id[:50]}... to {new_id[:50]}...")
                                        self._update_all_email_mappings_for_ticket(task.id, email_id, new_id)
                            except Exception as commit_err:
                                logger.error(f"[MAIL SYNC] Error committing email mapping for task {task.id}: {str(commit_err)}")
                                self.db.rollback()
                        else: logger.warning(f"[MAIL SYNC] Failed to create task from email ID {email.id}.")
                except Exception as e: 
                    logger.error(f"[MAIL SYNC] Error processing email ID {email_data.get('id', 'N/A')}: {str(e)}", exc_info=True)
                    
                    # Manejo mejorado de errores de sesión
                    try:
                        self.db.rollback()
                        logger.info(f"[MAIL SYNC] Successfully rolled back transaction after error")
                    except Exception as rollback_error:
                        logger.error(f"[MAIL SYNC] Error during rollback: {str(rollback_error)}")
                        # Si el rollback falla, crear nueva sesión
                        try:
                            self.db.close()
                            from app.database.session import SessionLocal
                            self.db = SessionLocal()
                            logger.info(f"[MAIL SYNC] Created new database session after failed rollback")
                        except Exception as session_error:
                            logger.error(f"[MAIL SYNC] Error creating new session: {str(session_error)}")
                    
                    continue
            sync_config.last_sync_time = datetime.utcnow(); self.db.commit()
            
            # LIMPIEZA PERIÓDICA: Cada 10 sincronizaciones, limpiar mappings huérfanos
            if sync_config.id % 10 == 0:  # Solo config IDs múltiplos de 10
                self._cleanup_orphaned_mappings()
            
            if created_tasks_count > 0 or added_comments_count > 0:
                logger.info(f"📧 Config {sync_config.id}: {created_tasks_count} tickets, {added_comments_count} comments")
            return []
        except Exception as e: logger.error(f"[MAIL SYNC] Error during email synchronization for config ID {sync_config.id}: {str(e)}", exc_info=True); return []

    def _cleanup_orphaned_mappings(self):
        """Limpiar mappings huérfanos e inconsistentes"""
        try:
            # 1. Buscar mappings huérfanos (que apuntan a tickets inexistentes)
            orphaned_mappings = self.db.query(EmailTicketMapping).filter(
                ~EmailTicketMapping.ticket_id.in_(
                    self.db.query(Task.id).filter(Task.is_deleted == False)
                )
            ).all()
            
            # 2. Buscar mappings inconsistentes (subject muy diferente al ticket)
            inconsistent_mappings = []
            recent_mappings = self.db.query(EmailTicketMapping).filter(
                EmailTicketMapping.created_at > datetime.utcnow() - timedelta(hours=24)
            ).limit(100).all()  # Solo revisar mappings recientes para performance
            
            for mapping in recent_mappings:
                if mapping.email_subject:
                    ticket = self.db.query(Task).filter(Task.id == mapping.ticket_id).first()
                    if ticket and ticket.title:
                        # Comparar subjects - si son muy diferentes, probablemente inconsistente
                        if (mapping.email_subject.lower() != ticket.title.lower() and 
                            not any(word in ticket.title.lower() for word in mapping.email_subject.lower().split()[:3])):
                            inconsistent_mappings.append(mapping)
            
            total_cleaned = 0
            
            if orphaned_mappings:
                logger.warning(f"🧹 Found {len(orphaned_mappings)} orphaned email mappings. Cleaning up...")
                for mapping in orphaned_mappings:
                    self.db.delete(mapping)
                total_cleaned += len(orphaned_mappings)
            
            if inconsistent_mappings:
                logger.warning(f"🧹 Found {len(inconsistent_mappings)} inconsistent email mappings. Cleaning up...")
                for mapping in inconsistent_mappings:
                    self.db.delete(mapping)
                total_cleaned += len(inconsistent_mappings)
            
            if total_cleaned > 0:
                self.db.commit()
                logger.info(f"✅ Cleaned up {total_cleaned} problematic email mappings ({len(orphaned_mappings)} orphaned, {len(inconsistent_mappings)} inconsistent)")
            # No problematic mappings found
                
        except Exception as e:
            logger.error(f"❌ Error during mappings cleanup: {str(e)}")
            self.db.rollback()

    def _extract_original_sender_from_forwarded_email(self, email_content: str, subject: str = "") -> tuple[Optional[str], Optional[str]]:
        """
        Detecta si un email es reenviado y extrae el remitente original del contenido.
        
        Returns:
            tuple[email, name] del remitente original, o (None, None) si no se detecta forward
        """
        if not email_content:
            return None, None
        
        # Patrones para detectar emails reenviados
        forwarded_patterns = [
            r"---------- Forwarded message ---------",
            r"Begin forwarded message:",
            r"-----Original Message-----",
            r"-----Mensaje original-----",
            r"From:.*?<br>",
            r"De:.*?<br>",
            r"Subject.*?FW:|Subject.*?Fwd:",
            r"Asunto.*?RV:|Asunto.*?Reenviado:"
        ]
        
        # Verificar si es un email reenviado
        is_forwarded = any(re.search(pattern, email_content, re.IGNORECASE | re.DOTALL) 
                          for pattern in forwarded_patterns)
        
        # También verificar el asunto
        if subject:
            subject_forwarded_patterns = [r"^FW:", r"^Fwd:", r"^RV:", r"^Reenviado:"]
            is_forwarded = is_forwarded or any(re.search(pattern, subject, re.IGNORECASE) 
                                             for pattern in subject_forwarded_patterns)
        
        if not is_forwarded:
            return None, None
        
        logger.info(f"[FORWARD DETECTION] Email detected as forwarded. Extracting original sender...")
        
        # Patrones para extraer información del remitente original
        # Formato típico: "From: Name <email@domain.com>"
        original_sender_patterns = [
            # Formato HTML
            r"<p[^>]*><strong>From:</strong>\s*([^<]+?)\s*&lt;([^&]+?)&gt;</p>",
            r"<p[^>]*><strong>From:</strong>\s*([^<]+?)\s*<([^>]+?)></p>",
            r"<div[^>]*><strong>From:</strong>\s*([^<]+?)\s*&lt;([^&]+?)&gt;</div>",
            
            # Formato texto plano en HTML
            r"From:\s*([^<\n]+?)\s*&lt;([^&\n]+?)&gt;",
            r"From:\s*([^<\n]+?)\s*<([^>\n]+?)>",
            r"De:\s*([^<\n]+?)\s*&lt;([^&\n]+?)&gt;",
            r"De:\s*([^<\n]+?)\s*<([^>\n]+?)>",
            
            # Solo email sin nombre
            r"From:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            r"De:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            
            # Otros formatos comunes
            r"From:\s*\"?([^\"<\n]+?)\"?\s*&lt;([^&\n]+?)&gt;",
            r"From:\s*\"?([^\"<\n]+?)\"?\s*<([^>\n]+?)>"
        ]
        
        for pattern in original_sender_patterns:
            match = re.search(pattern, email_content, re.IGNORECASE | re.DOTALL)
            if match:
                if len(match.groups()) == 2:
                    # Patrón con nombre y email
                    name = match.group(1).strip().strip('"').strip("'")
                    email = match.group(2).strip()
                elif len(match.groups()) == 1:
                    # Solo email
                    email = match.group(1).strip()
                    name = email.split('@')[0]  # Usar la parte antes del @ como nombre
                else:
                    continue
                
                # Validar que el email sea válido
                if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
                    logger.info(f"[FORWARD DETECTION] Original sender found: {name} <{email}>")
                    return email, name
        
        # Si no encontramos con patrones específicos, buscar cualquier email en el contenido
        # que no sea el remitente actual
        email_pattern = r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b'
        emails_in_content = re.findall(email_pattern, email_content)
        
        if emails_in_content:
            # Tomar el primer email encontrado (probablemente el original)
            first_email = emails_in_content[0]
            logger.info(f"[FORWARD DETECTION] Fallback: Using first email found in content: {first_email}")
            return first_email, first_email.split('@')[0]
        
        logger.warning(f"[FORWARD DETECTION] Could not extract original sender from forwarded email")
        return None, None

    def _clean_email_address(self, email_string: str) -> Optional[str]:
        """
        Limpia y extrae una dirección de email válida de un string que puede estar malformado.
        Ej: 'support support@ies.org' -> 'support@ies.org'
        """
        if not email_string:
            return None
        
        import re
        # Buscar patrón de email válido en el string
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, email_string)
        
        if match:
            return match.group(0)
        
        # Si no se encuentra un patrón válido, intentar limpiar espacios extra
        cleaned = email_string.strip()
        if '@' in cleaned:
            # Remover espacios extra alrededor del @
            parts = cleaned.split('@')
            if len(parts) == 2:
                local_part = parts[0].strip().split()[-1]  # Tomar la última palabra antes del @
                domain_part = parts[1].strip().split()[0]  # Tomar la primera palabra después del @
                return f"{local_part}@{domain_part}"
        
        return None

    def _parse_email_data(self, email_content: Dict, user_email: str, workspace_id: int = None) -> Optional[EmailData]:
        try:
            sender_data = email_content.get("from", {}).get("emailAddress", {})
            sender_address = self._clean_email_address(sender_data.get("address", ""))
            if not sender_address: 
                logger.warning(f"Could not parse sender from email content: {email_content.get('id')}")
                return None
            sender = EmailAddress(name=sender_data.get("name", ""), address=sender_address)
            
            # Verificar si el correo es una notificación del sistema o proviene del mismo dominio
            sender_email = sender.address.lower()
            
            # Usar detección automática de dominios si tenemos workspace_id, sino usar básicos
            if workspace_id:
                system_domains = self._get_system_domains_for_workspace(workspace_id)
            else:
                system_domains = ["enque.cc", "microsoftexchange"]  # Fallback básico
                
            notification_subjects = ["new ticket #", "ticket #", "new response", "[id:"]
            
            # Si el remitente es de un dominio del sistema o es el mismo buzón
            if sender_email == user_email.lower() or any(domain in sender_email for domain in system_domains):
                logger.warning(f"Email from system address or company domain: {sender_email}")
                # No rechazar completamente, pero marcar para que luego se pueda filtrar
                
            # Si el asunto parece ser una notificación del sistema
            if email_content.get("subject", ""):
                subject_lower = email_content.get("subject", "").lower()
                if any(phrase in subject_lower for phrase in notification_subjects):
                    logger.warning(f"Email subject appears to be a system notification: {email_content.get('subject')}")
                    # No rechazar completamente, pero marcar para que luego se pueda filtrar
            
            # Procesar TO recipients con limpieza de emails
            recipients = []
            for r in email_content.get("toRecipients", []):
                if r.get("emailAddress"):
                    cleaned_address = self._clean_email_address(r.get("emailAddress", {}).get("address", ""))
                    if cleaned_address:
                        recipients.append(EmailAddress(name=r.get("emailAddress", {}).get("name", ""), address=cleaned_address))
            if not recipients: recipients = [EmailAddress(name="", address=user_email)]
            
            # Procesar CC recipients con limpieza de emails
            cc_recipients = []
            for r in email_content.get("ccRecipients", []):
                if r.get("emailAddress"):
                    cleaned_address = self._clean_email_address(r.get("emailAddress", {}).get("address", ""))
                    if cleaned_address:
                        cc_recipients.append(EmailAddress(name=r.get("emailAddress", {}).get("name", ""), address=cleaned_address))
            
            # Procesar BCC recipients con limpieza de emails
            bcc_recipients = []
            for r in email_content.get("bccRecipients", []):
                if r.get("emailAddress"):
                    cleaned_address = self._clean_email_address(r.get("emailAddress", {}).get("address", ""))
                    if cleaned_address:
                        bcc_recipients.append(EmailAddress(name=r.get("emailAddress", {}).get("name", ""), address=cleaned_address))
            
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
                sender=sender, to_recipients=recipients, cc_recipients=cc_recipients, bcc_recipients=bcc_recipients,
                body_content=body_content, body_type=body_type, received_at=received_time,
                attachments=attachments, importance=email_content.get("importance", "normal"))
        except Exception as e: logger.error(f"Error parsing email data for email ID {email_content.get('id', 'N/A')}: {str(e)}", exc_info=True); return None

    def _create_task_from_email(self, email: EmailData, config: EmailSyncConfig, system_agent: Agent) -> Optional[Task]:
        if not system_agent: logger.error("System agent is required for _create_task_from_email but was not provided."); return None
        
        # Verificación más inteligente para evitar bucles de notificación
        if email.subject:
            subject_lower = email.subject.lower()
            
            # 🔧 PERMITIR emails con FW/Fwd (forwards) independientemente del contenido
            if any(fw_pattern in subject_lower for fw_pattern in ["fw:", "fwd:", "rv:", "reenviado:"]):
                logger.info(f"Permitiendo email con forward en asunto: '{email.subject}'")
            else:
                # Lista completa de patrones de notificación (solo para emails que NO son forwards)
                notification_patterns = [
                    "new ticket #", "ticket #", "new response", 
                    "assigned", "has been created", "notification:",
                    "automated message", "do not reply", "noreply"
                ]
                
                # Si el asunto contiene patrones claros de notificación, rechazar
                if any(pattern in subject_lower for pattern in notification_patterns):
                    logger.warning(f"Ignorando correo con asunto '{email.subject}' que parece ser una notificación del sistema")
                    return None
                
                # 🔧 PERMITIR respuestas legítimas: si contiene [ID:] pero viene de dominio externo, probablemente es respuesta de usuario
                if "[id:" in subject_lower:
                    sender_domain = email.sender.address.split('@')[-1].lower() if '@' in email.sender.address else ""
                    system_domains = self._get_system_domains_for_workspace(config.workspace_id)
                    core_system_domains = ["enque.cc", "microsoftexchange"]
                    
                    # Si viene de dominio externo (no del sistema), probablemente es respuesta legítima
                    if sender_domain not in core_system_domains and sender_domain not in system_domains:
                        logger.info(f"Permitiendo respuesta de usuario externo con [ID:] en asunto: {email.sender.address} - '{email.subject}'")
                    else:
                        logger.warning(f"Ignorando correo con [ID:] de dominio del sistema: {email.sender.address} - '{email.subject}'")
                        return None
                
        # Verificación adicional por dominio solo para notificaciones obvias
        sender_domain = email.sender.address.split('@')[-1].lower() if '@' in email.sender.address else ""
        
        # Obtener dominios del sistema para este workspace automáticamente
        system_domains = self._get_system_domains_for_workspace(config.workspace_id)
        
        # Solo rechazar emails de dominios core del sistema (enque.cc, microsoftexchange)
        core_system_domains = ["enque.cc", "microsoftexchange"]
        if sender_domain in core_system_domains:
            logger.warning(f"Ignorando correo del dominio del sistema core: {sender_domain} - {email.sender.address}")
            return None
        
        # Para dominios del workspace (como s-fx.com, cliente1.com, etc.), 
        # solo rechazar si es claramente una notificación (por asunto)
        workspace_domains = [d for d in system_domains if d not in core_system_domains]
        if sender_domain in workspace_domains and email.subject:
            subject_lower = email.subject.lower()
            if any(keyword in subject_lower for keyword in ["new ticket #", "ticket #", "[id:", "has been"]):
                logger.warning(f"Ignorando notificación de dominio del workspace {sender_domain} con asunto '{email.subject}'")
                return None
            else:
                logger.info(f"Permitiendo email legítimo de dominio del workspace {sender_domain} con asunto '{email.subject}'")
        
        try:
            priority = config.default_priority
            if email.importance == "high": priority = "High"
            elif email.importance == "low": priority = "Low"
            workspace_id = config.workspace_id
            if not workspace_id: logger.error(f"Missing workspace_id in sync config {config.id}. Cannot create user/task."); return None
            
            # 🔧 NUEVA FUNCIONALIDAD: Detectar emails reenviados y extraer remitente original
            original_email, original_name = self._extract_original_sender_from_forwarded_email(
                email.body_content, email.subject
            )
            
            if original_email and original_name:
                # Email reenviado: usar remitente original como contacto principal
                logger.info(f"[FORWARD DETECTION] Creating ticket with original sender: {original_name} <{original_email}>")
                user = get_or_create_user(self.db, original_email, original_name, workspace_id=workspace_id)
                
                # Guardar información del forward para referencias futuras
                forwarded_by_email = email.sender.address
                forwarded_by_name = email.sender.name or "Unknown"
                logger.info(f"[FORWARD DETECTION] Email was forwarded by: {forwarded_by_name} <{forwarded_by_email}>")
            else:
                # Email normal: usar remitente directo
                user = get_or_create_user(self.db, email.sender.address, email.sender.name or "Unknown", workspace_id=workspace_id)
            
            if not user: logger.error(f"Could not get or create user for email: {email.sender.address} in workspace {workspace_id}"); return None
            company_id = user.company_id; assigned_agent = None
            if config.auto_assign and config.default_assignee_id:
                assigned_agent = self.db.query(Agent).filter(Agent.id == config.default_assignee_id).first()
            workspace = self.db.query(Workspace).filter(Workspace.id == config.workspace_id).first()
            if not workspace: logger.error(f"Workspace ID {config.workspace_id} not found. Skipping ticket creation."); return None
            due_date = datetime.utcnow() + timedelta(days=3)
            
            # Determinar team_id basado en la asignación del mailbox
            team_id = None
            if config.mailbox_connection_id:
                # Buscar si el mailbox está asignado a algún team
                from app.models.microsoft import mailbox_team_assignments
                team_assignment = self.db.query(mailbox_team_assignments).filter(
                    mailbox_team_assignments.c.mailbox_connection_id == config.mailbox_connection_id
                ).first()
                
                if team_assignment:
                    team_id = team_assignment.team_id
                    logger.info(f"Auto-assigning ticket to team {team_id} based on mailbox assignment")
            
            # NUEVO: Procesar TO recipients para guardar en el ticket
            to_recipients_str = None
            if email.to_recipients:
                to_emails = []
                for to in email.to_recipients:
                    if to.address:
                        if to.name and to.name.strip():
                            to_emails.append(f"{to.name} <{to.address}>")
                        else:
                            to_emails.append(to.address)
                if to_emails:
                    to_recipients_str = ", ".join(to_emails)
                    logger.info(f"Ticket from email will have TO recipients: {to_recipients_str}")
            
            # NUEVO: Procesar CC recipients para guardar en el ticket
            cc_recipients_str = None
            if email.cc_recipients:
                cc_emails = []
                for cc in email.cc_recipients:
                    if cc.address:
                        if cc.name and cc.name.strip():
                            cc_emails.append(f"{cc.name} <{cc.address}>")
                        else:
                            cc_emails.append(cc.address)
                if cc_emails:
                    cc_recipients_str = ", ".join(cc_emails)
                    logger.info(f"Ticket from email will have CC recipients: {cc_recipients_str}")
            
            # 🔧 NUEVA FUNCIONALIDAD: Incluir quien hizo forward en CC si aplica
            if original_email and original_name:
                # Si el email fue reenviado, agregar quien lo reenvió a los CCs
                forwarded_by_email = email.sender.address
                forwarded_by_name = email.sender.name
                
                # Usar formato "Nombre <email>" si hay nombre disponible
                if forwarded_by_name and forwarded_by_name.strip():
                    forwarded_by_formatted = f"{forwarded_by_name} <{forwarded_by_email}>"
                else:
                    forwarded_by_formatted = forwarded_by_email
                
                if cc_recipients_str:
                    cc_recipients_str = f"{cc_recipients_str}, {forwarded_by_formatted}"
                else:
                    cc_recipients_str = forwarded_by_formatted
                logger.info(f"[FORWARD DETECTION] Added forwarder to CC: {forwarded_by_formatted}")
                
                # Usar remitente original en email_sender
                email_sender_field = f"{original_name} <{original_email}>"
            else:
                # Email normal
                email_sender_field = f"{email.sender.name} <{email.sender.address}>"
            
            # Crear el ticket sin descripción inicial
            task = Task(
                title=email.subject or "No Subject", description=None, status="Unread", priority=priority,
                assignee_id=assigned_agent.id if assigned_agent else None, due_date=due_date, sent_from_id=system_agent.id,
                user_id=user.id, company_id=company_id, workspace_id=workspace.id, 
                mailbox_connection_id=config.mailbox_connection_id, team_id=team_id,
                email_message_id=email.id, email_conversation_id=email.conversation_id,
                email_sender=email_sender_field, to_recipients=to_recipients_str, cc_recipients=cc_recipients_str,
                last_update=datetime.utcnow())
            self.db.add(task); self.db.flush()
            
            activity = Activity(agent_id=system_agent.id, source_type='Ticket', source_id=task.id, workspace_id=workspace.id, action=f"Created ticket from email from {email.sender.name}")
            self.db.add(activity)

            # Procesar adjuntos si los hay
            attachments_for_comment = []
            if email.attachments:
                non_inline_attachments = [att for att in email.attachments if not att.is_inline and att.contentBytes]
                for att in non_inline_attachments:
                    try:
                        decoded_bytes = base64.b64decode(att.contentBytes)
                        
                        # ✅ FIX: Subir adjunto inicial a S3 (igual que para comentarios posteriores)
                        s3_url = None
                        try:
                            from app.services.s3_service import get_s3_service
                            s3_service = get_s3_service()
                            
                            # Determinar carpeta según tipo de archivo
                            folder = "images" if att.content_type.startswith("image/") else "documents"
                            
                            # Subir a S3
                            s3_url = s3_service.upload_file(
                                file_content=decoded_bytes,
                                filename=att.name,
                                content_type=att.content_type,
                                folder=folder
                            )
                            
                            logger.info(f"📎 Adjunto inicial '{att.name}' subido a S3: {s3_url}")
                            
                        except Exception as s3_error:
                            logger.error(f"❌ Error subiendo adjunto inicial '{att.name}' a S3: {str(s3_error)}")
                            # Fallback: guardar en BD si S3 falla
                            pass
                        
                        # Crear adjunto en BD con S3 URL o bytes según disponibilidad
                        db_attachment = TicketAttachment(
                            file_name=att.name,
                            content_type=att.content_type,
                            file_size=att.size,
                            s3_url=s3_url,  # ✅ FIX: Incluir URL de S3
                            content_bytes=decoded_bytes if not s3_url else None  # Solo bytes si S3 falló
                        )
                        attachments_for_comment.append(db_attachment)
                    except Exception as e:
                        logger.error(f"Error al procesar adjunto '{att.name}' para ticket {task.id}: {e}", exc_info=True)

            # Procesar el HTML para las imágenes inline
            processed_html = self._process_html_body(email.body_content, email.attachments, f"new ticket {task.id}")
            
            # Eliminar cualquier línea "From:" que pueda estar en el contenido del correo para evitar duplicidad
            processed_html = re.sub(r'^<p><strong>From:</strong>.*?</p>', '', processed_html, flags=re.DOTALL | re.IGNORECASE)
            
            # MODIFICACIÓN CLAVE: En lugar de usar al system_agent como remitente añadimos metadata especial al principio
            # del contenido del comentario con un formato específico que el frontend detectará para mostrar al usuario original.
            # Esto evita aparecer como "Admin Demo" y muestra correctamente al usuario original.
            
            # 🔧 NUEVA FUNCIONALIDAD: Mostrar quien realmente envió el mensaje en la conversación
            if original_email and original_name:
                # Email reenviado: mostrar quien hizo el forward en la conversación 
                # (el contacto principal ya está correcto como Richard)
                forward_sender_name = email.sender.name or "Unknown Forwarder"
                forward_sender_email = email.sender.address
                special_metadata = f'<original-sender>{forward_sender_name}|{forward_sender_email}</original-sender>'
                logger.info(f"[FORWARD DETECTION] Conversation will show forwarder: {forward_sender_name} <{forward_sender_email}>")
            else:
                # Email normal: usar usuario directo
                special_metadata = f'<original-sender>{user.name}|{user.email}</original-sender>'
            
            # NUEVO: Revisar contenido ANTES de insertar en BD para evitar errores de tamaño
            content_to_store = special_metadata + processed_html
            s3_html_url = None
            
            try:
                if content_to_store and content_to_store.strip():
                    from app.services.s3_service import get_s3_service
                    s3_service = get_s3_service()
                    
                    # Verificar si el contenido es muy grande o debe ir a S3
                    content_length = len(content_to_store)
                    should_migrate_to_s3 = (
                        content_length > 65000 or  # Más de 65KB (límite aproximado de TEXT)
                        s3_service.should_store_html_in_s3(content_to_store)
                                        )
                    
                    if should_migrate_to_s3:
                        # Generar un ID temporal para el archivo S3
                        import uuid
                        temp_id = str(uuid.uuid4())
                        
                        # Almacenar en S3 con ID temporal
                        s3_url = s3_service.upload_html_content(
                            html_content=content_to_store,
                            filename=f"temp-initial-comment-{temp_id}.html",
                            folder="comments"
                        )
                        
                        # Actualizar variables para la BD
                        s3_html_url = s3_url
                        content_to_store = f"[MIGRATED_TO_S3] Content moved to S3: {s3_url}"
            except Exception as e:
                logger.error(f"❌ [MAIL SYNC] Error pre-migrating initial content to S3: {str(e)}")
                # Continue with original content if S3 fails
                content_to_store = special_metadata + processed_html
                s3_html_url = None
            
            # El comentario principal con metadatos + contenido HTML + adjuntos
            initial_comment = Comment(
                ticket_id=task.id,
                agent_id=system_agent.id,  # Seguimos usando system_agent (requerido)
                workspace_id=workspace.id,
                content=content_to_store,  # Usar contenido procesado
                s3_html_url=s3_html_url,  # Incluir URL de S3 si existe
                is_private=False
            )
            
            # Añadir los adjuntos al comentario
            for attachment in attachments_for_comment:
                initial_comment.attachments.append(attachment)
                
            self.db.add(initial_comment)
                
            # MEJORADO: Post-procesamiento solo si es necesario renombrar archivo S3
            if s3_html_url and not s3_html_url.endswith(f"comment-{initial_comment.id}.html"):
                try:
                    # Hacer flush para obtener el ID real del comentario
                    self.db.flush()
                    
                    # Renombrar archivo en S3 con el ID real del comentario
                    from app.services.s3_service import get_s3_service
                    s3_service = get_s3_service()
                    
                    # Obtener el contenido original para almacenar con el nombre correcto
                    if '[MIGRATED_TO_S3] Content moved to S3: ' in content_to_store:
                        original_content = special_metadata + processed_html
                    else:
                        original_content = content_to_store
                    
                    # Crear nueva URL con ID real
                    final_s3_url = s3_service.store_comment_html(initial_comment.id, original_content)
                    
                    # Actualizar la URL en el comentario
                    initial_comment.s3_html_url = final_s3_url
                    initial_comment.content = f"[MIGRATED_TO_S3] Content moved to S3: {final_s3_url}"
                except Exception as e:
                    logger.warning(f"⚠️ [MAIL SYNC] Could not rename S3 file for initial comment {initial_comment.id}: {str(e)}")
                    # Continue with temp filename - not critical
            
            # Crear un TicketBody vacío (requerido pero no lo usaremos para mostrar contenido)
            ticket_body = TicketBody(ticket_id=task.id, email_body="")
            self.db.add(ticket_body)
            
            # Commit para asegurar que el ticket esté guardado antes de enviar notificaciones
            self.db.commit()
            
            # ✅ EMIT SOCKET.IO EVENT para notificar nuevo ticket en tiempo real
            try:
                from app.core.socketio import emit_new_ticket_sync
                
                task_data = {
                    'id': task.id,
                    'title': task.title,
                    'status': task.status,
                    'priority': task.priority,
                    'workspace_id': task.workspace_id,
                    'assignee_id': task.assignee_id,
                    'team_id': task.team_id,
                    'user_id': task.user_id,
                    'created_at': task.created_at.isoformat() if task.created_at else None,
                    'user_name': user.name if user else 'Unknown',
                    'user_email': user.email if user else ''
                }
                
                # Emitir evento de forma síncrona para email sync
                emit_new_ticket_sync(workspace.id, task_data)
            except Exception as e:
                logger.error(f"❌ [MAIL SYNC] Error emitting Socket.IO event for new ticket {task.id}: {str(e)}")
            
            # NUEVO: Ejecutar automations basadas en las condiciones del ticket
            try:
                from app.services.automation_service import execute_automations_for_ticket
                
                # Cargar el ticket con todas las relaciones necesarias para las condiciones de automation
                from sqlalchemy.orm import joinedload
                task_with_relations = self.db.query(Task).options(
                    joinedload(Task.user),
                    joinedload(Task.assignee),
                    joinedload(Task.company),
                    joinedload(Task.category),
                    joinedload(Task.team)
                ).filter(Task.id == task.id).first()
                
                if task_with_relations:
                    executed_actions = execute_automations_for_ticket(self.db, task_with_relations)
                    if executed_actions:
                        # Refresh the task to get updated values from automations
                        self.db.refresh(task)
                        
            except Exception as automation_error:
                logger.error(f"Error executing automations for new ticket {task.id}: {str(automation_error)}")
            
            # NUEVO: Procesar workflows basados en el contenido del email inicial
            try:
                from app.services.workflow_service import WorkflowService
                
                # Solo procesar si hay contenido significativo
                if email.body_content and email.body_content.strip():
                    workflow_service = WorkflowService(self.db)
                    
                    # Preparar contexto para workflows
                    workflow_context = {
                        'task_id': task.id,
                        'comment_id': initial_comment.id,
                        'agent_id': system_agent.id,  # Agente del sistema que procesa
                        'workspace_id': workspace.id,
                        'task_status': task.status,
                        'task_priority': task.priority,
                        'is_private': False,
                        'is_from_email': True,
                        'is_new_ticket': True,
                        'email_sender': user.email,
                        'email_sender_name': user.name,
                        'assignee_id': task.assignee_id
                    }
                    
                    # Procesar workflows basados en contenido del email inicial
                    workflow_results = workflow_service.process_message_for_workflows(
                        email.body_content,
                        workspace.id,
                        workflow_context
                    )
                    
                    if workflow_results:
                        logger.info(f"[MAIL SYNC] Executed {len(workflow_results)} workflows for new ticket {task.id}")
                        for result in workflow_results:
                            logger.info(f"[MAIL SYNC] Workflow executed: {result.get('workflow_name')} - {result.get('trigger')}")
                        
                        # Commit any changes made by workflows
                        self.db.commit()
                    
            except Exception as workflow_error:
                logger.error(f"[MAIL SYNC] Error processing workflows for new ticket: {str(workflow_error)}")
            
            # Verificar si debemos enviar notificaciones (evitar bucles y spam)
            should_send_notification = True
            
            # Evitar notificaciones para correos del sistema o notificaciones automáticas
            notification_keywords = ["ticket", "created", "notification", "system", "auto", "automated", "no-reply", "noreply"]
            system_domains = self._get_system_domains_for_workspace(workspace.id)  # Detección automática
            
            # Verificar si el asunto parece una notificación automática
            if email.subject:
                subject_lower = email.subject.lower()
                if any(keyword in subject_lower for keyword in notification_keywords):
                    # Si el asunto parece una notificación, reducir la probabilidad de enviar otra notificación
                    if any(domain in email.sender.address.lower() for domain in system_domains):
                        logger.info(f"Skipping notifications for ticket {task.id} as it appears to be a system notification")
                        should_send_notification = False
            
            # Enviar notificaciones de nuevo ticket solo si es apropiado
            if should_send_notification:
                try:
                    import asyncio
                    from app.services.notification_service import send_notification
                    
                    # 1. Notificar al usuario que creó el ticket (remitente del email)
                    if user and user.email and not any(domain in user.email.lower() for domain in system_domains):
                        template_vars = {
                            "user_name": user.name,
                            "ticket_id": task.id,
                            "ticket_title": task.title
                        }
                        
                        # Crear un nuevo bucle de eventos y ejecutar la corrutina de forma sincrónica
                        loop = asyncio.new_event_loop()
                        try:
                            loop.run_until_complete(
                                send_notification(
                                    db=self.db,
                                    workspace_id=workspace_id,
                                    category="users",
                                    notification_type="new_ticket_created",
                                    recipient_email=user.email,
                                    recipient_name=user.name,
                                    template_vars=template_vars,
                                    task_id=task.id
                                )
                            )
                            logger.info(f"Notification for new ticket {task.id} sent to user {user.name}")
                        finally:
                            loop.close()
                    
                    # 2. Notificar a miembros del equipo si el ticket está asignado a un equipo sin agente específico
                    if task.team_id and not task.assignee_id:
                        try:
                            from app.services.task_service import send_team_notification
                            loop = asyncio.new_event_loop()
                            try:
                                loop.run_until_complete(send_team_notification(self.db, task))
                                logger.info(f"Team notification sent for ticket {task.id} assigned to team {task.team_id}")
                            finally:
                                loop.close()
                        except Exception as team_notify_err:
                            logger.warning(f"Failed to send team notification for ticket {task.id}: {str(team_notify_err)}")
                    
                    # 3. Notificar a todos los agentes activos en el workspace (solo si no es un ticket de equipo)
                    elif not task.team_id:
                        active_agents = self.db.query(Agent).filter(
                            Agent.workspace_id == workspace_id,
                            Agent.is_active == True,
                            Agent.email != None,
                            Agent.email != ""
                        ).all()
                    
                        # Preparar variables de plantilla para notificaciones de agentes
                        agent_template_vars = {
                            "ticket_id": task.id,
                            "ticket_title": task.title,
                            "user_name": user.name if user else "Unknown User"
                        }
                        
                        # Notificar a cada agente activo
                        for agent in active_agents:
                            # Si el agente es el asignado, añadir información adicional 
                            if assigned_agent and agent.id == assigned_agent.id:
                                agent_template_vars["agent_name"] = agent.name
                            else:
                                agent_template_vars["agent_name"] = agent.name
                            
                            # Solo enviar si el agente no está en un dominio del sistema
                            if not any(domain in agent.email.lower() for domain in system_domains):
                                loop = asyncio.new_event_loop()
                                try:
                                    loop.run_until_complete(
                                        send_notification(
                                            db=self.db,
                                            workspace_id=workspace_id,
                                            category="agents",
                                            notification_type="new_ticket_created",
                                            recipient_email=agent.email,
                                            recipient_name=agent.name,
                                            template_vars=agent_template_vars,
                                            task_id=task.id
                                        )
                                    )
                                    logger.info(f"Notification for new ticket {task.id} sent to agent {agent.name}")
                                except Exception as agent_notify_err:
                                    logger.warning(f"Failed to send notification to agent {agent.name}: {str(agent_notify_err)}")
                                finally:
                                    loop.close()
                    
                except Exception as e:
                    logger.error(f"Error sending notifications for ticket {task.id} created from email: {str(e)}", exc_info=True)
            else:
                logger.info(f"Notifications suppressed for ticket {task.id} to prevent notification loops")
                
            return task
        except Exception as e: logger.error(f"Error creating task from email ID {email.id}: {str(e)}", exc_info=True); self.db.rollback(); return None

    @cached_microsoft_graph(ttl=600, key_prefix="mailbox_folders")  # Cache folders for 10 minutes
    @rate_limited(resource="mailbox")
    async def _get_mailbox_folders_cached(self, app_token: str, user_email: str) -> Dict[str, str]:
        """Get mailbox folders with caching"""
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers)
                response.raise_for_status()
                
            folders = response.json().get("value", [])
            # Create mapping of folder names to IDs
            folder_map = {}
            for folder in folders:
                display_name = folder.get("displayName", "").lower()
                folder_map[display_name] = folder.get("id")
                # Add common variants
                if display_name == "inbox":
                    folder_map.update({
                        "bandeja de entrada": folder.get("id"),
                        "boîte de réception": folder.get("id")
                    })
                    
            return folder_map
            
        except Exception as e:
            logger.error(f"Error getting folders for {user_email}: {str(e)}", exc_info=True)
            return {}
    
    @cached_microsoft_graph(ttl=300, key_prefix="mailbox_emails")  # Cache emails for 5 minutes
    @rate_limited(resource="mailbox")
    async def _get_mailbox_emails_cached(self, app_token: str, user_email: str, folder_id: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get mailbox emails with caching and rate limiting"""
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.graph_url}/users/{user_email}/mailFolders/{folder_id}/messages", 
                    headers=headers, 
                    params=params
                )
                response.raise_for_status()
                
            return response.json().get("value", [])
            
        except Exception as e:
            logger.error(f"Error getting emails for {user_email}: {str(e)}", exc_info=True)
            return []

    def get_mailbox_emails(self, app_token: str, user_email: str, folder_name: str = "Inbox", top: int = 10, filter_unread: bool = False) -> List[Dict[str, Any]]:
        """Get mailbox emails with improved caching and performance"""
        try:
            folder_id = None
            
            if PERFORMANCE_SERVICES_AVAILABLE:
                try:
                    # Get cached folder mapping
                    loop = asyncio.get_event_loop()
                    folder_map = {}
                    
                    if loop.is_running():
                        task = asyncio.create_task(self._get_mailbox_folders_cached(app_token, user_email))
                        folder_map = asyncio.run_coroutine_threadsafe(task, loop).result(timeout=10)
                    else:
                        folder_map = loop.run_until_complete(self._get_mailbox_folders_cached(app_token, user_email))
                    
                    folder_id = folder_map.get(folder_name.lower())
                    
                except Exception as cache_error:
                    pass  # Folder cache not available
            
            # Fallback to direct API calls if cache fails
            if not folder_id:
                headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
                response_folders = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, params={"$filter": f"displayName eq '{folder_name}'"})
                response_folders.raise_for_status()
                folders = response_folders.json().get("value", [])
                
                if folders:
                    folder_id = folders[0].get("id")
                else:
                    # Try common inbox names
                    common_inbox_names = ["inbox", "bandeja de entrada", "boîte de réception"]
                    response_all_folders = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers)
                    response_all_folders.raise_for_status()
                    all_folders = response_all_folders.json().get("value", [])
                    for folder in all_folders:
                        if folder.get("displayName", "").lower() in common_inbox_names:
                            folder_id = folder.get("id")
                            break
                    
                    if not folder_id:
                        response_inbox = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders/inbox", headers=headers)
                        if response_inbox.ok:
                            folder_id = response_inbox.json().get("id")
                        else:
                            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Folder '{folder_name}' not found.")
            
            # Prepare email query parameters
            params = {
                "$top": min(top, 50),  # Limit to prevent large responses
                "$orderby": "receivedDateTime DESC", 
                "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,bccRecipients,receivedDateTime,bodyPreview,importance,hasAttachments,body,isRead"
            }
            if filter_unread:
                params["$filter"] = "isRead eq false"
            
            # Try cached email retrieval
            if PERFORMANCE_SERVICES_AVAILABLE:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        task = asyncio.create_task(self._get_mailbox_emails_cached(app_token, user_email, folder_id, params))
                        return asyncio.run_coroutine_threadsafe(task, loop).result(timeout=15)
                    else:
                        return loop.run_until_complete(self._get_mailbox_emails_cached(app_token, user_email, folder_id, params))
                except Exception as cache_error:
                    pass  # Email cache not available
            
            # Fallback to direct API call
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            response_messages = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders/{folder_id}/messages", headers=headers, params=params)
            response_messages.raise_for_status()
            
            emails = response_messages.json().get("value", [])

            
            return emails
            
        except Exception as e:
            logger.error(f"Error getting emails for {user_email}: {str(e)}", exc_info=True)
            return []

    @cached_microsoft_graph(ttl=1800, key_prefix="email_content")  # Cache for 30 minutes (emails don't change)
    @rate_limited(resource="mailbox")
    async def _get_mailbox_email_content_cached(self, app_token: str, user_email: str, message_id: str) -> Dict[str, Any]:
        """Get email content with caching and rate limiting"""
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            params = {"$expand": "attachments"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.graph_url}/users/{user_email}/messages/{message_id}", 
                    headers=headers, 
                    params=params
                )
                response.raise_for_status()
                
            return response.json()
            
        except Exception as e:
            logger.error(f"Error getting full email content for message ID {message_id}: {str(e)}", exc_info=True)
            return {}

    def get_mailbox_email_content(self, app_token: str, user_email: str, message_id: str) -> Dict[str, Any]:
        """Get email content with improved caching"""
        try:
            # Try cached version first
            if PERFORMANCE_SERVICES_AVAILABLE:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        task = asyncio.create_task(self._get_mailbox_email_content_cached(app_token, user_email, message_id))
                        return asyncio.run_coroutine_threadsafe(task, loop).result(timeout=15)
                    else:
                        return loop.run_until_complete(self._get_mailbox_email_content_cached(app_token, user_email, message_id))
                except Exception as cache_error:
                    pass  # Email content cache not available
            
            # Fallback to direct API call
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            params = {"$expand": "attachments"}
            response = requests.get(f"{self.graph_url}/users/{user_email}/messages/{message_id}", headers=headers, params=params)
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"Error getting full email content for message ID {message_id}: {str(e)}", exc_info=True)
            return {}

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
        """
        Obtiene o crea una carpeta de procesamiento. Incluye lógica robusta para manejar 
        carpetas duplicadas y problemas de permisos en entornos multitenant.
        """
        try:
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            
            # Primero, buscar la carpeta existente
            search_params = {"$filter": f"displayName eq '{folder_name}'"}
            response = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, params=search_params)
            response.raise_for_status()
            folders = response.json().get("value", [])
            
            if folders:
                folder_id = folders[0].get("id")
                return folder_id
            
            # Si no existe, intentar crearla
            data = {"displayName": folder_name}
            response = requests.post(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, json=data)
            
            if response.status_code in [200, 201]:
                folder_id = response.json().get("id")
                return folder_id
            elif response.status_code == 409:
                # Conflicto - la carpeta ya existe (posible race condition)
                # Buscar nuevamente
                response = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders", headers=headers, params=search_params)
                response.raise_for_status()
                folders = response.json().get("value", [])
                if folders:
                    folder_id = folders[0].get("id")
                    return folder_id
            else:
                # Otro error al crear
                error_details = "No details available"
                try:
                    error_details = response.json()
                except ValueError:
                    error_details = response.text
                
                logger.warning(f"Failed to create folder '{folder_name}' (Status: {response.status_code}). Details: {error_details}")
                
                # Como fallback, intentar crear en la carpeta Inbox
                inbox_response = requests.get(f"{self.graph_url}/users/{user_email}/mailFolders/Inbox", headers=headers)
                if inbox_response.status_code == 200:
                    inbox_id = inbox_response.json().get("id")
                    subfolder_data = {"displayName": folder_name}
                    subfolder_response = requests.post(
                        f"{self.graph_url}/users/{user_email}/mailFolders/{inbox_id}/childFolders", 
                        headers=headers, 
                        json=subfolder_data
                    )
                    
                    if subfolder_response.status_code in [200, 201]:
                        folder_id = subfolder_response.json().get("id")
                        return folder_id
                    else:
                        logger.error(f"Failed to create subfolder '{folder_name}' in Inbox")
                
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting/creating folder '{folder_name}' for {user_email}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting/creating folder '{folder_name}' for {user_email}: {str(e)}", exc_info=True)
            return None

    def _move_email_to_folder(self, app_token: str, user_email: str, message_id: str, folder_id: str) -> Optional[str]:
        try:
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}/move"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}; data = {"destinationId": folder_id}
            response = requests.post(endpoint, headers=headers, json=data); response.raise_for_status()
            response_data = response.json(); new_message_id = response_data.get("id", message_id)
            if new_message_id != message_id: logger.info(f"Email ID changed from {message_id} to {new_message_id} after move.")
            return new_message_id
        except Exception as e: logger.error(f"Error moving email {message_id} to folder {folder_id} for user {user_email}: {str(e)}"); return message_id

    def _update_all_email_mappings_for_ticket(self, ticket_id: int, old_email_id: str, new_email_id: str) -> bool:
        """
        Actualiza todos los mappings de email relacionados con un ticket cuando el Message ID cambia.
        Esto es crítico para mantener la consistencia después de mover emails a carpetas.
        Incluye manejo robusto de duplicados y condiciones de carrera.
        """
        if not old_email_id or not new_email_id:
            logger.warning(f"Invalid email IDs provided: old='{old_email_id}', new='{new_email_id}'")
            return False
            
        try:
            # Verificar que el nuevo ID no sea demasiado largo
            if len(new_email_id) > 255:
                logger.warning(f"New email ID is too long ({len(new_email_id)} chars). Truncating to 255 chars.")
                new_email_id = new_email_id[:255]
            
            # Si el ID no cambió, no hay nada que hacer
            if old_email_id == new_email_id:
                logger.debug(f"Email ID unchanged for ticket {ticket_id}. No update needed.")
                return True
            
            logger.info(f"🔄 Updating email mappings for ticket {ticket_id}: {old_email_id[:50]}... → {new_email_id[:50]}...")
            
            # 🔧 ESTRATEGIA COMPLETAMENTE NUEVA: Crear nuevo mapping y eliminar el viejo
            # Esto evita conflictos de transacciones y duplicados
            
            # 1. Verificar si ya existe un mapping con el nuevo ID
            existing_new_mapping = self.db.query(EmailTicketMapping).filter(
                EmailTicketMapping.email_id == new_email_id,
                EmailTicketMapping.ticket_id == ticket_id
            ).first()
            
            if existing_new_mapping:
                logger.info(f"✅ Mapping with new email ID already exists for ticket {ticket_id}. Removing old mappings only.")
                # Solo eliminar los mappings antiguos
                old_mappings = self.db.query(EmailTicketMapping).filter(
                    EmailTicketMapping.ticket_id == ticket_id,
                    EmailTicketMapping.email_id == old_email_id
                ).all()
                
                for old_mapping in old_mappings:
                    self.db.delete(old_mapping)
                
                self.db.commit()
                logger.info(f"✅ Removed {len(old_mappings)} old email mappings for ticket {ticket_id}")
                return True
            
            # 2. Buscar todos los mappings antiguos para este ticket
            old_mappings = self.db.query(EmailTicketMapping).filter(
                EmailTicketMapping.ticket_id == ticket_id,
                EmailTicketMapping.email_id == old_email_id
            ).all()
            
            if not old_mappings:
                logger.debug(f"No old mappings found for ticket {ticket_id} with email ID {old_email_id[:50]}...")
                return False
            
            # 3. Crear nuevos mappings basados en los antiguos
            new_mappings_created = 0
            
            for old_mapping in old_mappings:
                try:
                    # Crear nuevo mapping con el nuevo email ID
                    new_mapping = EmailTicketMapping(
                        email_id=new_email_id,
                        email_conversation_id=old_mapping.email_conversation_id,
                        ticket_id=old_mapping.ticket_id,
                        email_subject=old_mapping.email_subject,
                        email_sender=old_mapping.email_sender,
                        email_received_at=old_mapping.email_received_at,
                        is_processed=old_mapping.is_processed,
                        created_at=old_mapping.created_at,
                        updated_at=datetime.utcnow()
                    )
                    
                    # Intentar agregar el nuevo mapping
                    self.db.add(new_mapping)
                    self.db.flush()  # Flush para detectar duplicados temprano
                    new_mappings_created += 1
                    
                except Exception as create_error:
                    if "Duplicate entry" in str(create_error):
                        logger.warning(f"🔧 Duplicate detected while creating new mapping for ticket {ticket_id}. Skipping creation.")
                        self.db.rollback()
                        # Verificar si el mapping ya existe
                        existing_check = self.db.query(EmailTicketMapping).filter(
                            EmailTicketMapping.email_id == new_email_id,
                            EmailTicketMapping.ticket_id == ticket_id
                        ).first()
                        if existing_check:
                            new_mappings_created += 1  # Contar como exitoso
                    else:
                        logger.error(f"Error creating new mapping for ticket {ticket_id}: {str(create_error)}")
                        self.db.rollback()
                        continue
            
            # 4. Si se crearon nuevos mappings exitosamente, eliminar los antiguos
            if new_mappings_created > 0:
                try:
                    # Commit los nuevos mappings primero
                    self.db.commit()
                    
                    # Ahora eliminar los mappings antiguos
                    for old_mapping in old_mappings:
                        self.db.delete(old_mapping)
                    
                    self.db.commit()
                    logger.info(f"✅ Successfully updated {new_mappings_created} email mappings for ticket {ticket_id}")
                    return True
                    
                except Exception as cleanup_error:
                    logger.error(f"Error during cleanup for ticket {ticket_id}: {str(cleanup_error)}")
                    self.db.rollback()
                    return False
            else:
                logger.warning(f"No new mappings were created for ticket {ticket_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating email mappings for ticket {ticket_id}: {str(e)}")
            try:
                self.db.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback for ticket {ticket_id}: {str(rollback_error)}")
            return False

    def _validate_ticket_mailbox_association(self, task: Task, mailbox_connection: MailboxConnection, email_mapping: EmailTicketMapping) -> bool:
        """
        Valida que el ticket esté correctamente asociado con el mailbox correcto.
        En entornos multitenant, esto es crítico para asegurar que las respuestas
        se envíen desde el mailbox correcto.
        """
        try:
            # Verificar que el task tenga un mailbox_connection_id válido
            if not task.mailbox_connection_id:
                logger.error(f"Task {task.id} has no mailbox_connection_id")
                return False
            
            # Verificar que el mailbox_connection existe y está activo
            if not mailbox_connection:
                logger.error(f"Mailbox connection {task.mailbox_connection_id} not found for task {task.id}")
                return False
            
            if not mailbox_connection.is_active:
                logger.error(f"Mailbox connection {mailbox_connection.email} is not active for task {task.id}")
                return False
            
            # Verificar que el mailbox pertenece al mismo workspace
            if mailbox_connection.workspace_id != task.workspace_id:
                logger.error(f"Mailbox {mailbox_connection.email} (workspace {mailbox_connection.workspace_id}) does not match task {task.id} workspace {task.workspace_id}")
                return False
            
            # Verificar que tenemos un mapping válido
            if not email_mapping or not email_mapping.email_id:
                logger.error(f"No valid email mapping found for task {task.id}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating ticket-mailbox association for task {task.id}: {str(e)}")
            return False

    def _process_html_for_email(self, html_content: str) -> str:
        """Procesa el HTML para asegurar un formato limpio y con espaciado controlado en clientes de correo."""
        try:
            if not html_content.strip():
                return '' 

            soup = BeautifulSoup(html_content, 'html.parser')

            # Procesar todos los párrafos primero para limpieza general y márgenes
            for p_tag in soup.find_all('p'):
                # Eliminar estilos en línea preexistentes que no sean de la firma procesada después
                if p_tag.has_attr('style') and not p_tag.find_parent(class_='email-signature'):
                    del p_tag['style'] 
                
                # Aplicar margen base a párrafos que no son de firma
                if not p_tag.find_parent(class_='email-signature'):
                     p_tag['style'] = 'margin: 0.5em 0; padding: 0; line-height: 1.4;' # Estilo base para párrafos normales
                else:
                    # Es un párrafo de firma, se procesará específicamente después
                    pass

            # Procesamiento específico para la firma de correo
            signature_elements = soup.find_all(class_='email-signature')
            for sig_wrapper in signature_elements:
                # Aplicar estilo base al contenedor de la firma si es un div
                if sig_wrapper.name == 'div':
                    sig_wrapper['style'] = 'line-height: 0.6; font-size: 0.9em; color: #6b7280;'
                
                for p_in_sig in sig_wrapper.find_all('p'):
                    p_in_sig['style'] = 'margin: 0 0 0.1em 0; padding: 0; line-height: 0.6; font-size: 0.9em; color: #6b7280;'
                
                # Asegurar que los <br> dentro de la firma tengan line-height mínimo si es necesario (aunque line-height en <br> es poco estándar)
                # Normalmente, el line-height del <p> o <div> contenedor debería ser suficiente.
                # for br_in_sig in sig_wrapper.find_all('br'):
                #     br_in_sig['style'] = 'line-height: 1;' # O incluso quitarlo si no ayuda

            # Eliminar párrafos vacíos que no sean de firma y no contengan imágenes/BRs significativos
            for p_tag in soup.find_all('p'):
                if not p_tag.find_parent(class_='email-signature'):
                    if not p_tag.get_text(strip=True) and not p_tag.find_all(('br', 'img')):
                        prev_sibling = p_tag.find_previous_sibling()
                        if prev_sibling and prev_sibling.name == 'br':
                            p_tag.decompose()
                        else:
                            br_tag = soup.new_tag('br')
                            p_tag.replace_with(br_tag)
            
            processed_html = str(soup)
            processed_html = re.sub(r'(<br\s*/?>\s*){2,}', '<br>\n', processed_html)

            return processed_html
        
        except Exception as e:
            logger.error(f"Error al procesar HTML para correo electrónico: {str(e)}", exc_info=True)
            return html_content

    def send_reply_email(self, task_id: int, reply_content: str, agent: Agent, attachment_ids: List[int] = None, cc_recipients: List[str] = None, bcc_recipients: List[str] = None) -> bool:
        """
        Send a reply email for a ticket that originated from an email.
        If the ticket has original CC recipients, they will be included in the reply.
        """
        logger.info(f"[REPLY EMAIL] Starting reply process for task {task_id} by agent {agent.name}")
        
        # IMPORTANTE: Forzar refresh para obtener datos actualizados del ticket
        self.db.expire_all()  # Expira cache de SQLAlchemy
        
        # Get the task with its mailbox connection and user information
        task = self.db.query(Task).options(
            joinedload(Task.mailbox_connection),
            joinedload(Task.user)  # Agregar user para debugging
        ).filter(Task.id == task_id).first()
        
        if not task:
            logger.error(f"❌ Task {task_id} not found for reply email")
            return False
        
        # Log información del usuario actual para debugging
        if task.user:
            logger.info(f"[REPLY EMAIL] Task {task_id} assigned to user: {task.user.name} ({task.user.email})")
        else:
            logger.info(f"[REPLY EMAIL] Task {task_id} has no assigned user")
        
        if not task.mailbox_connection:
            logger.error(f"❌ Task {task_id} has no associated mailbox connection. Cannot send reply.")
            return False
        
        mailbox_connection = task.mailbox_connection
        
        # Get email mappings to check original sender
        email_mappings = self.db.query(EmailTicketMapping).filter(
            EmailTicketMapping.ticket_id == task_id
        ).order_by(EmailTicketMapping.created_at.asc()).all()
        
        if not email_mappings:
            logger.error(f"❌ No email mappings found for ticket {task_id}. Cannot send reply.")
            return False
        
        # Get the original email sender from the first mapping
        original_mapping = email_mappings[0]
        original_sender = original_mapping.email_sender  # Format: "Name <email@domain.com>"
        
        # Extract email from original sender
        email_match = re.search(r'<([^>]+)>', original_sender) if original_sender else None
        original_sender_email = email_match.group(1) if email_match else (original_sender or "")
        
        # Check if the current ticket user is different from the original sender
        current_user_email = task.user.email if task.user else ""
        contact_changed = current_user_email and original_sender_email and current_user_email.lower() != original_sender_email.lower()
        
        if contact_changed:
            logger.info(f"[REPLY EMAIL] 🔄 Primary contact changed from {original_sender_email} to {current_user_email}")
            logger.info(f"[REPLY EMAIL] 📧 Sending NEW email to updated contact instead of reply")
            
            # Send a new email to the updated contact instead of using createReply
            subject = f"Re: [ID:{task_id}] {task.title}"
            
            # Format the HTML content if needed
            if not reply_content.strip().lower().startswith('<html'):
                html_body = f"<html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 16px 0; padding: 4px 0; min-height: 16px; line-height: 1.5; }}</style></head><body>{reply_content}</body></html>"
            else:
                html_body = reply_content
            
            # Use send_new_email method for the updated contact
            return self.send_new_email(
                mailbox_email=mailbox_connection.email,
                recipient_email=current_user_email,
                subject=subject,
                html_body=html_body,
                attachment_ids=attachment_ids,
                task_id=task_id,
                cc_recipients=cc_recipients
            )
        
        # If contact hasn't changed, proceed with normal reply logic
        logger.info(f"[REPLY EMAIL] 📧 Contact unchanged, sending normal reply to {original_sender_email}")
        
        # 🔧 NOTA: CC recipients se procesarán después de obtener original_message_id
        
        # Verificar que el token de aplicación (client credentials) no tiene permisos para acceder a mailboxes específicos
        # Necesitamos usar el token delegado del usuario que configuró este mailbox
        try:
            # Obtener el token específico para este mailbox
            mailbox_token = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                MicrosoftToken.expires_at > datetime.utcnow()
            ).order_by(MicrosoftToken.created_at.desc()).first()
            
            if not mailbox_token:
                # Intentar refrescar token expirado
                logger.warning(f"No active token found for mailbox {mailbox_connection.email}. Looking for refreshable token...")
                expired_token = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                    MicrosoftToken.refresh_token.isnot(None),
                    MicrosoftToken.refresh_token != ""
                ).order_by(MicrosoftToken.expires_at.desc()).first()
                
                if expired_token:
                    try:
                        mailbox_token = self.refresh_token(expired_token)
                    except Exception as refresh_error:
                        logger.error(f"Failed to refresh token for mailbox {mailbox_connection.email}: {str(refresh_error)}")
                        return False
                else:
                    logger.error(f"No refreshable token found for mailbox {mailbox_connection.email}")
                    return False
            
            if not mailbox_token:
                logger.error(f"Could not obtain valid token for mailbox {mailbox_connection.email}")
                return False
                
            # Usar el token del usuario específico del mailbox
            app_token = mailbox_token.access_token
            
        except Exception as e: 
            logger.error(f"Failed to get user token for mailbox {mailbox_connection.email}: {e}"); 
            return False
        email_mapping = email_mappings[0]
        original_message_id = email_mapping.email_id
        
        if not cc_recipients:
            original_cc_recipients = []
            try:
                message_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}"
                headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
                
                response = requests.get(message_endpoint, headers=headers)
                if response.status_code == 200:
                    message_data = response.json()
                    cc_recipients_data = message_data.get("ccRecipients", [])
                    for cc_recipient in cc_recipients_data:
                        email_address = cc_recipient.get("emailAddress", {}).get("address")
                        if email_address:
                            original_cc_recipients.append(email_address)
                    
                    if original_cc_recipients:
                        logger.info(f"Found {len(original_cc_recipients)} CC recipients from original email: {original_cc_recipients}")
                else:
                    logger.warning(f"Could not fetch original message for CC recipients. Status: {response.status_code}")
            except Exception as cc_error:
                logger.error(f"Error fetching original CC recipients: {str(cc_error)}")
            cc_recipients = original_cc_recipients.copy()
            if task.cc_recipients:
                ticket_cc_recipients = [email.strip() for email in task.cc_recipients.split(",") if email.strip()]
                for ticket_cc in ticket_cc_recipients:
                    if ticket_cc not in cc_recipients:
                        cc_recipients.append(ticket_cc)
                logger.info(f"Added {len(ticket_cc_recipients)} CC recipients from ticket: {ticket_cc_recipients}")
            
            if cc_recipients:
                logger.info(f"Final CC recipients list ({len(cc_recipients)}): {cc_recipients}")
            else:
                logger.info("No CC recipients found for this reply")
        else:
            logger.info(f"Using provided CC recipients: {cc_recipients}")
        if cc_recipients:
            cleaned_cc_recipients = []
            for cc_email in cc_recipients:
                
                cleaned_email = cc_email.strip()
                email_match = re.search(r'<([^>]+)>', cleaned_email)
                if email_match:
                    cleaned_email = email_match.group(1).strip()
                if ' ' in cleaned_email:
                    email_pattern = r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
                    email_matches = re.findall(email_pattern, cleaned_email)
                    if email_matches:
                        cleaned_email = email_matches[0]
                if cleaned_email and '@' in cleaned_email and '.' in cleaned_email and cleaned_email not in cleaned_cc_recipients:
                    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                    if re.match(email_pattern, cleaned_email):
                        cleaned_cc_recipients.append(cleaned_email)
                    else:
                        logger.warning(f"Invalid email format after cleaning: {cleaned_email} (original: {cc_email})")
            
            cc_recipients = cleaned_cc_recipients
            logger.info(f"Cleaned CC recipients for Microsoft Graph: {cc_recipients}")
        if not self._validate_ticket_mailbox_association(task, mailbox_connection, email_mapping):
            return False
        
        try:
            if not mailbox_connection:
                logger.error(f"❌ Mailbox connection not found for ticket {task_id}. Cannot send reply.")
                return False
            message_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
            
            response = requests.get(message_endpoint, headers=headers)
            if response.status_code == 404:
                logger.warning(f"Message ID {original_message_id} not found (404) in mailbox {mailbox_connection.email}.")
                all_mappings = self.db.query(EmailTicketMapping).filter(
                    EmailTicketMapping.ticket_id == task_id
                ).order_by(EmailTicketMapping.updated_at.desc()).all()
                
                found_valid_mapping = False
                for mapping in all_mappings:
                    if mapping.email_id != original_message_id:
                        test_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{mapping.email_id}"
                        test_response = requests.get(test_endpoint, headers=headers)
                        
                        if test_response.status_code == 200:
                            original_message_id = mapping.email_id
                            found_valid_mapping = True
                            break
                
                if not found_valid_mapping:
                    # Intentar buscar por conversation ID si está disponible
                    conversation_mapping = self.db.query(EmailTicketMapping).filter(
                        EmailTicketMapping.ticket_id == task_id,
                        EmailTicketMapping.email_conversation_id.isnot(None)
                    ).first()
                    
                    if conversation_mapping and conversation_mapping.email_conversation_id:
                        # Buscar emails en esta conversación en todas las carpetas
                        search_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages"
                        search_params = {
                            "$filter": f"conversationId eq '{conversation_mapping.email_conversation_id}'",
                            "$select": "id,subject,receivedDateTime,parentFolderId",
                            "$top": 20
                        }
                        
                        search_response = requests.get(search_endpoint, headers=headers, params=search_params)
                        
                        if search_response.status_code == 200:
                            conversation_emails = search_response.json().get("value", [])
                            
                            if conversation_emails:
                                # Usar el email más reciente de la conversación
                                latest_email = max(conversation_emails, key=lambda x: x.get("receivedDateTime", ""))
                                new_message_id = latest_email.get("id")
                                
                                if new_message_id:
                                    # Verificar que este email sea accesible antes de usarlo
                                    verify_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{new_message_id}"
                                    verify_response = requests.get(verify_endpoint, headers=headers)
                                    
                                    if verify_response.status_code == 200:
                                        original_message_id = new_message_id
                                        found_valid_mapping = True
                                        
                                        # Actualizar el mapping en la base de datos con el nuevo Message ID
                                        try:
                                            email_mapping.email_id = new_message_id
                                            self.db.commit()
                                        except Exception as update_error:
                                            logger.error(f"Failed to update email mapping: {str(update_error)}")
                                            self.db.rollback()
                    
                    # Buscar en la carpeta "Enque Processed"
                    if not found_valid_mapping:
                        try:
                            # Obtener ID de la carpeta "Enque Processed"
                            folders_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/mailFolders"
                            folders_params = {"$filter": "displayName eq 'Enque Processed'"}
                            
                            folders_response = requests.get(folders_endpoint, headers=headers, params=folders_params)
                            
                            if folders_response.status_code == 200:
                                folders = folders_response.json().get("value", [])
                                
                                if folders:
                                    processed_folder_id = folders[0].get("id")
                                    
                                    # Verificar si tenemos conversation_mapping válido
                                    if conversation_mapping and conversation_mapping.email_conversation_id:
                                        # Buscar emails por conversation ID en la carpeta procesada
                                        processed_search_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/mailFolders/{processed_folder_id}/messages"
                                        processed_search_params = {
                                            "$filter": f"conversationId eq '{conversation_mapping.email_conversation_id}'",
                                            "$select": "id,subject,receivedDateTime,conversationId",
                                            "$top": 10
                                        }
                                        
                                        processed_response = requests.get(processed_search_endpoint, headers=headers, params=processed_search_params)
                                        
                                        if processed_response.status_code == 200:
                                            processed_emails = processed_response.json().get("value", [])
                                            
                                            if processed_emails:
                                                # Usar el email más reciente
                                                latest_processed = max(processed_emails, key=lambda x: x.get("receivedDateTime", ""))
                                                processed_message_id = latest_processed.get("id")
                                                
                                                if processed_message_id:
                                                    # Verificar acceso al email procesado
                                                    verify_processed_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{processed_message_id}"
                                                    verify_processed_response = requests.get(verify_processed_endpoint, headers=headers)
                                                    
                                                    if verify_processed_response.status_code == 200:
                                                        original_message_id = processed_message_id
                                                        found_valid_mapping = True
                                                        
                                                        # Actualizar el mapping con el ID de la carpeta procesada
                                                        try:
                                                            email_mapping.email_id = processed_message_id
                                                            self.db.commit()
                                                        except Exception as update_error:
                                                            logger.error(f"Failed to update email mapping with processed ID: {str(update_error)}")
                                                            self.db.rollback()
                        except Exception as processed_search_error:
                            logger.error(f"Error searching in 'Enque Processed' folder: {str(processed_search_error)}")
                    
                    if not found_valid_mapping:
                        logger.error(f"❌ No valid message ID found for ticket {task_id} in mailbox {mailbox_connection.email}. Cannot send reply.")
                        logger.error(f"💡 This ticket was created from mailbox {mailbox_connection.email} but the original email cannot be found.")
                        logger.error(f"💡 This may indicate that the email was deleted, archived, or moved to a different folder.")
                    return False
                    
            elif response.status_code != 200:
                logger.warning(f"⚠️ Unexpected response code {response.status_code} when verifying message ID in {mailbox_connection.email}")
                
        except Exception as verify_error:
            logger.error(f"❌ Error verifying message ID {original_message_id} for task {task_id}: {str(verify_error)}")

        reply_content = self._process_html_for_email(reply_content)
        attachments_data = []
        if attachment_ids and len(attachment_ids) > 0:
            # Retrieve attachment data from provided IDs
            for attachment_id in attachment_ids:
                attachment = self.db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
                if attachment:
                    # Get file content - either from content_bytes or download from S3
                    file_content = None
                    if attachment.content_bytes:
                        # Use existing content_bytes (legacy)
                        file_content = attachment.content_bytes
                    elif attachment.s3_url:
                        # Download from S3
                        file_content = self._download_file_from_s3(attachment.s3_url)
                        if not file_content:
                            logger.error(f"Failed to download attachment {attachment.file_name} from S3")
                            continue
                    else:
                        logger.error(f"Attachment {attachment.file_name} (ID: {attachment_id}) has no content_bytes or s3_url")
                        continue
                    
                    # Convert file content to base64 for MS Graph API
                    content_b64 = base64.b64encode(file_content).decode('utf-8')
                    attachments_data.append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": attachment.file_name,
                        "contentType": attachment.content_type,
                        "contentBytes": content_b64
                    })
                else:
                    logger.warning(f"Attachment ID {attachment_id} not found when preparing email reply")
        
        # If no specific attachment IDs were provided, fallback to getting from the latest comment
        if not attachments_data:
            # Get the latest comment by this agent to find attachments
            latest_comment = self.db.query(Comment).filter(
                Comment.ticket_id == task_id,
                Comment.agent_id == agent.id
            ).order_by(Comment.created_at.desc()).first()
            
            # Check for attachments
            if latest_comment:
                attachments = self.db.query(TicketAttachment).filter(
                    TicketAttachment.comment_id == latest_comment.id
                ).all()
                
                if attachments:
                    for attachment in attachments:
                        # Get file content - either from content_bytes or download from S3
                        file_content = None
                        if attachment.content_bytes:
                            # Use existing content_bytes (legacy)
                            file_content = attachment.content_bytes
                        elif attachment.s3_url:
                            # Download from S3
                            file_content = self._download_file_from_s3(attachment.s3_url)
                            if not file_content:
                                logger.error(f"Failed to download attachment {attachment.file_name} from S3 (fallback method)")
                                continue
                        else:
                            logger.error(f"Attachment {attachment.file_name} has no content_bytes or s3_url (fallback method)")
                            continue
                        
                        # Convert file content to base64 for MS Graph API
                        content_b64 = base64.b64encode(file_content).decode('utf-8')
                        attachments_data.append({
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "name": attachment.file_name,
                            "contentType": attachment.content_type,
                            "contentBytes": content_b64
                        })
        
        # Format the HTML content if needed
        if not reply_content.strip().lower().startswith('<html'):
             html_body = f"<html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 16px 0; padding: 4px 0; min-height: 16px; line-height: 1.5; }}</style></head><body>{reply_content}</body></html>"
        else: html_body = reply_content
        
        # Microsoft Graph API has two ways to reply to emails:
        # 1. Simple reply (without attachments) - uses /messages/{id}/reply endpoint
        # 2. Create draft and send (with attachments) - uses /messages and /sendMail endpoints
        
        if attachments_data:
            # Use createReply to create a draft reply, add attachments, then send
            try:
                # Step 1: Create a draft reply
                create_reply_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}/createReply"
                headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
                
                # Just create the draft
                response = requests.post(create_reply_endpoint, headers=headers)
                if response.status_code not in [200, 201, 202]:
                    error_details = "No details available"
                    try: error_details = response.json()
                    except ValueError: error_details = response.text
                    logger.error(f"Failed to create draft reply for task_id: {task_id}. Status Code: {response.status_code}. Details: {error_details}")
                    response.raise_for_status()
                
                # Step 2: Get the draft message ID and update it with content and attachments
                draft_message = response.json()
                draft_id = draft_message.get("id")
                if not draft_id:
                    logger.error(f"Failed to get draft ID from createReply response for task_id: {task_id}")
                    return False
                
                # Modify the draft subject to include ticket ID in format [ID:XXXXX]
                original_subject = draft_message.get("subject", "").strip()
                ticket_id_tag = f"[ID:{task_id}]"
                
                # Check if the ID tag is already in the subject
                if ticket_id_tag not in original_subject:
                    # Add the ticket ID tag right after "Re:" if it exists, otherwise at the beginning
                    if original_subject.lower().startswith("re:"):
                        new_subject = f"Re: {ticket_id_tag} {original_subject[3:].strip()}"
                    else:
                        new_subject = f"{ticket_id_tag} {original_subject}"
                else:
                    # Subject already has the tag, use as is
                    new_subject = original_subject
                
                # Step 3: Update the draft with our content, subject, and attachments
                update_payload = {
                    "subject": new_subject,
                    "body": {
                        "contentType": "HTML",
                        "content": html_body
                    }
                }

                if cc_recipients:
                    update_payload["ccRecipients"] = [{"emailAddress": {"address": email}} for email in cc_recipients]
                
                if bcc_recipients:
                    update_payload["bccRecipients"] = [{"emailAddress": {"address": email}} for email in bcc_recipients]
                
                update_message_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{draft_id}"
                response = requests.patch(update_message_endpoint, headers=headers, json=update_payload)
                if response.status_code not in [200, 201, 202]:
                    error_details = "No details available"
                    try: error_details = response.json()
                    except ValueError: error_details = response.text
                    logger.error(f"Failed to update draft message for task_id: {task_id}. Status Code: {response.status_code}. Details: {error_details}")
                    response.raise_for_status()
                
                # Step 4: Add attachments one by one
                for attachment_data in attachments_data:
                    attachments_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{draft_id}/attachments"
                    attachment_response = requests.post(attachments_endpoint, headers=headers, json=attachment_data)
                    if attachment_response.status_code not in [200, 201, 202]:
                        logger.warning(f"Failed to add attachment to draft message for task_id: {task_id}. Status Code: {attachment_response.status_code}")
                
                # Step 5: Send the message
                send_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{draft_id}/send"
                send_response = requests.post(send_endpoint, headers=headers)
                if send_response.status_code not in [200, 201, 202, 204]:  # 204 No Content is success for this endpoint
                    error_details = "No details available"
                    try: error_details = send_response.json()
                    except ValueError: error_details = send_response.text
                    logger.error(f"Failed to send draft message for task_id: {task_id}. Status Code: {send_response.status_code}. Details: {error_details}")
                    send_response.raise_for_status()
                
                logger.info(f"📧 Reply sent for task {task_id}")
                return True
            except requests.exceptions.RequestException as e:
                error_details = "No details available"; status_code = 'N/A'
                if e.response is not None:
                    status_code = e.response.status_code
                    try: error_details = e.response.json()
                    except ValueError: error_details = e.response.text
                logger.error(f"Failed to send email reply with attachments for task_id: {task_id}. Status Code: {status_code}. Details: {error_details}. Error: {str(e)}")
                return False
            except Exception as e:
                logger.error(f"An unexpected error occurred while sending email reply with attachments for task_id: {task_id}. Error: {str(e)}", exc_info=True)
                return False
        else:
            # For simple reply without attachments, we need to:
            # 1. Get the original message to extract its subject
            # 2. Create a message with modified subject and our content
            # 3. Send it as a reply-all
            try:
                # Get the original message to check its subject
                message_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}"
                headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
                
                response = requests.get(message_endpoint, headers=headers)
                if response.status_code != 200:
                    # If we can't get the original message, fall back to simple reply
                    logger.warning(f"Couldn't get original message details for task {task_id}. Falling back to simple reply.")
                    reply_payload = {"comment": html_body}
                    reply_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}/reply"
                    response = requests.post(reply_endpoint, headers=headers, json=reply_payload)
                    response.raise_for_status()
                    logger.info(f"📧 Reply sent for task {task_id}")
                    return True
                else:
                    # Si llegamos aquí, pudimos obtener el mensaje original, así que procedemos con el flujo normal
                    message_data = response.json()
                    original_subject = message_data.get("subject", "").strip()
                    ticket_id_tag = f"[ID:{task_id}]"
                    
                    # Check if the ID tag is already in the subject
                    if ticket_id_tag not in original_subject:
                        # Add the ticket ID tag right after "Re:" if it exists, otherwise at the beginning
                        if original_subject.lower().startswith("re:"):
                            new_subject = f"Re: {ticket_id_tag} {original_subject[3:].strip()}"
                        else:
                            new_subject = f"{ticket_id_tag} {original_subject}"
                        
                        # Subject modified
                    else:
                        # Subject already has the tag, use as is
                        new_subject = original_subject
                        logger.info(f"Subject already contains ticket ID tag: '{original_subject}'")
                    
                    # Create a proper reply message with our modified subject
                    create_reply_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}/createReply"
                    response = requests.post(create_reply_endpoint, headers=headers)
                    response.raise_for_status()
                    
                    # Get the draft
                    draft_message = response.json()
                    draft_id = draft_message.get("id")
                    if not draft_id:
                        logger.error(f"Failed to get draft ID from createReply response for task_id: {task_id}")
                        return False
                    
                    # Update the draft with our content and subject
                    update_payload = {
                        "subject": new_subject,
                        "body": {
                            "contentType": "HTML",
                            "content": html_body
                        }
                    }

                    if cc_recipients:
                        update_payload["ccRecipients"] = [{"emailAddress": {"address": email}} for email in cc_recipients]
                    
                    if bcc_recipients:
                        update_payload["bccRecipients"] = [{"emailAddress": {"address": email}} for email in bcc_recipients]
                    
                    update_message_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{draft_id}"
                    response = requests.patch(update_message_endpoint, headers=headers, json=update_payload)
                    response.raise_for_status()
                    
                    # Send the modified message
                    send_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{draft_id}/send"
                    response = requests.post(send_endpoint, headers=headers)
                    response.raise_for_status()
                    
                    return True
            except requests.exceptions.RequestException as e:
                error_details = "No details available"; status_code = 'N/A'
                if e.response is not None:
                    status_code = e.response.status_code
                    try: error_details = e.response.json()
                    except ValueError: error_details = e.response.text
                
                # If something fails with our approach, fall back to simple reply
                logger.warning(f"Failed custom reply approach for task {task_id}. Status Code: {status_code}. Falling back to simple reply.")
                try:
                    reply_payload = {"comment": html_body}
                    reply_endpoint = f"{self.graph_url}/users/{mailbox_connection.email}/messages/{original_message_id}/reply"
                    response = requests.post(reply_endpoint, headers=headers, json=reply_payload)
                    response.raise_for_status()
                    logger.info(f"📧 Reply sent for task {task_id}")
                    return True
                except Exception as fallback_error:
                    logger.error(f"Both custom and fallback reply methods failed for task {task_id}. Error: {str(fallback_error)}")
                return False
            except Exception as e:
                logger.error(f"An unexpected error occurred while sending email reply for task_id: {task_id}. Error: {str(e)}", exc_info=True)
                return False

    def send_new_email(self, mailbox_email: str, recipient_email: str, subject: str, html_body: str, attachment_ids: List[int] = None, task_id: Optional[int] = None, cc_recipients: List[str] = None, bcc_recipients: List[str] = None) -> bool:
        logger.info(f"Attempting to send new email from: {mailbox_email} to: {recipient_email} with subject: {subject}")
        
        # 🔧 CORRECCIÓN CRÍTICA: Usar token de usuario específico del mailbox, no token de aplicación
        try:
            # Buscar el mailbox connection por email
            mailbox_connection = self.db.query(MailboxConnection).filter(
                MailboxConnection.email == mailbox_email,
                MailboxConnection.is_active == True
            ).first()
            
            if not mailbox_connection:
                logger.error(f"Mailbox connection not found for email: {mailbox_email}")
                return False
            
            # Obtener el token específico para este mailbox
            mailbox_token = self.db.query(MicrosoftToken).filter(
                MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                MicrosoftToken.expires_at > datetime.utcnow()
            ).order_by(MicrosoftToken.created_at.desc()).first()
            
            if not mailbox_token:
                # Intentar refrescar token expirado
                logger.warning(f"No active token found for mailbox {mailbox_email}. Looking for refreshable token...")
                expired_token = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox_connection.id,
                    MicrosoftToken.refresh_token.isnot(None),
                    MicrosoftToken.refresh_token != ""
                ).order_by(MicrosoftToken.expires_at.desc()).first()
                
                if expired_token:
                    try:
                        mailbox_token = self.refresh_token(expired_token)
                    except Exception as refresh_error:
                        logger.error(f"Failed to refresh token for mailbox {mailbox_email}: {str(refresh_error)}")
                        return False
                else:
                    logger.error(f"No refreshable token found for mailbox {mailbox_email}")
                    return False
            
            if not mailbox_token:
                logger.error(f"Could not obtain valid token for mailbox {mailbox_email}")
                return False
                
            # Usar el token del usuario específico del mailbox
            app_token = mailbox_token.access_token
            
        except Exception as e: 
            logger.error(f"Failed to get user token for mailbox {mailbox_email}: {e}"); 
            return False
        
        # Procesar el contenido HTML para mejorar compatibilidad con Gmail
        html_body = self._process_html_for_email(html_body)
        
        # Check for attachments if IDs were provided
        attachments_data = []
        if attachment_ids and len(attachment_ids) > 0:
            # Retrieve attachment data
            for attachment_id in attachment_ids:
                attachment = self.db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
                if attachment:
                    # Get file content - either from content_bytes or download from S3
                    file_content = None
                    if attachment.content_bytes:
                        # Use existing content_bytes (legacy)
                        file_content = attachment.content_bytes
                        logger.info(f"Using content_bytes for attachment {attachment.file_name} (ID: {attachment_id}) in new email")
                    elif attachment.s3_url:
                        # Download from S3
                        logger.info(f"Downloading attachment {attachment.file_name} from S3: {attachment.s3_url} for new email")
                        file_content = self._download_file_from_s3(attachment.s3_url)
                        if not file_content:
                            logger.error(f"Failed to download attachment {attachment.file_name} from S3 for new email")
                            continue
                    else:
                        logger.error(f"Attachment {attachment.file_name} (ID: {attachment_id}) has no content_bytes or s3_url for new email")
                        continue
                    
                    # Convert file content to base64 for MS Graph API
                    content_b64 = base64.b64encode(file_content).decode('utf-8')
                    attachments_data.append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": attachment.file_name,
                        "contentType": attachment.content_type,
                        "contentBytes": content_b64
                    })
                    logger.info(f"Added attachment {attachment.file_name} ({attachment.id}) to new email")
                else:
                    logger.warning(f"Attachment ID {attachment_id} not found when preparing email")
        
        # Format HTML content if needed
        if not html_body.strip().lower().startswith('<html'):
            html_body = f"<html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 16px 0; padding: 4px 0; min-height: 16px; line-height: 1.5; }}</style></head><body>{html_body}</body></html>"
        
        # If task_id is provided, add it to the subject line in format [ID:XXXXX]
        original_subject = subject.strip()
        if task_id:
            ticket_id_tag = f"[ID:{task_id}]"
            
            # Check if the ID tag is already in the subject
            if ticket_id_tag not in original_subject:
                new_subject = f"{ticket_id_tag} {original_subject}"
                logger.info(f"Modified subject for task {task_id} from '{original_subject}' to '{new_subject}'")
                subject = new_subject
            else:
                logger.info(f"Subject already contains ticket ID tag: '{original_subject}'")
        
        # Prepare basic email payload
        email_payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_body},
                "toRecipients": [{"emailAddress": {"address": recipient_email}}]
            },
            "saveToSentItems": "true"
        }
        
        # Add CC recipients if provided
        if cc_recipients:
            # 🧹 LIMPIAR formato de CC recipients antes de enviar a Microsoft Graph
            cleaned_cc_recipients = []
            for cc_email in cc_recipients:
                # Extraer solo la dirección de email, manejando varios formatos:
                # - "email@domain.com"
                # - "Name <email@domain.com>"  
                # - "S-FX.com Devs <dev@s-fx.com>" (formato con espacios)
                
                cleaned_email = cc_email.strip()
                
                # Si contiene <>, extraer el contenido
                email_match = re.search(r'<([^>]+)>', cleaned_email)
                if email_match:
                    cleaned_email = email_match.group(1).strip()
                
                # Si aún contiene espacios, tomar solo la primera parte que parece email
                if ' ' in cleaned_email:
                    # Buscar la primera dirección de email válida en la cadena
                    email_pattern = r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
                    email_matches = re.findall(email_pattern, cleaned_email)
                    if email_matches:
                        cleaned_email = email_matches[0]
                
                # Validar que sea un email válido y no esté duplicado
                if cleaned_email and '@' in cleaned_email and '.' in cleaned_email and cleaned_email not in cleaned_cc_recipients:
                    # Validación adicional con regex
                    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                    if re.match(email_pattern, cleaned_email):
                        cleaned_cc_recipients.append(cleaned_email)
                    else:
                        logger.warning(f"Invalid email format after cleaning: {cleaned_email} (original: {cc_email})")
            
            if cleaned_cc_recipients:
                email_payload["message"]["ccRecipients"] = [{"emailAddress": {"address": email}} for email in cleaned_cc_recipients]
                logger.info(f"Including {len(cleaned_cc_recipients)} cleaned CC recipients in new email: {cleaned_cc_recipients}")
            else:
                logger.warning("No valid CC recipients after cleaning")
        
        # Add BCC recipients if provided
        if bcc_recipients:
            email_payload["message"]["bccRecipients"] = [{"emailAddress": {"address": email}} for email in bcc_recipients]
            logger.info(f"Including {len(bcc_recipients)} BCC recipients in new email: {bcc_recipients}")
        
        # Add attachments to payload if any were found
        if attachments_data:
            email_payload["message"]["attachments"] = attachments_data
            logger.info(f"Including {len(attachments_data)} attachments in new email")
        
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
        subject: str, html_body: str, task_id: Optional[int] = None
    ) -> bool:
        if not user_access_token:
            logger.error("Token is None or empty. Cannot send email.")
            return False
            

        
        # Procesar el contenido HTML para mejorar compatibilidad con Gmail
        html_body = self._process_html_for_email(html_body)
        
        # Format HTML content if needed
        if not html_body.strip().lower().startswith('<html'):
            html_body = f"<html><head><style>body {{ font-family: sans-serif; font-size: 10pt; }} p {{ margin: 0 0 16px 0; padding: 4px 0; min-height: 16px; line-height: 1.5; }}</style></head><body>{html_body}</body></html>"
        
        # If task_id is provided, add it to the subject line in format [ID:XXXXX]
        original_subject = subject.strip()
        if task_id:
            ticket_id_tag = f"[ID:{task_id}]"
            
            # Check if the ID tag is already in the subject
            if ticket_id_tag not in original_subject:
                new_subject = f"{ticket_id_tag} {original_subject}"
                logger.info(f"Modified subject for task {task_id} from '{original_subject}' to '{new_subject}'")
                subject = new_subject
            else:
                logger.info(f"Subject already contains ticket ID tag: '{original_subject}'")
        
        email_payload = {
            "message": {"subject": subject, "body": {"contentType": "HTML", "content": html_body},
                        "toRecipients": [{"emailAddress": {"address": recipient_email}}]},
            "saveToSentItems": "true"}
        try:
            send_mail_endpoint = f"{self.graph_url}/users/{sender_mailbox_email}/sendMail"
            headers = {"Authorization": f"Bearer {user_access_token}", "Content-Type": "application/json"}
            
            async with httpx.AsyncClient() as client:
                response = await client.post(send_mail_endpoint, headers=headers, json=email_payload, timeout=30.0)
            
            if response.status_code not in [200, 202]:
                error_details = "No details available"; 
                try: 
                    error_details = response.json()
                    logger.error(f"Detailed error response: {error_details}")
                except Exception: 
                    error_details = response.text
                    logger.error(f"Error response text: {error_details}")
                    
                logger.error(f"Failed to send email from {sender_mailbox_email} using user token. Status: {response.status_code}. Details: {error_details}")
                response.raise_for_status() 
                
            logger.info(f"📧 Email sent to {recipient_email}")
            return True
        except httpx.HTTPStatusError as e:
            error_details = "No details available"; 
            try: 
                error_details = e.response.json()
                logger.error(f"Detailed error response in exception: {error_details}")
            except Exception: 
                error_details = e.response.text
                logger.error(f"Error response text in exception: {error_details}")
                
            logger.error(f"HTTP error sending email from {sender_mailbox_email} using user token. Status: {e.response.status_code}. Details: {error_details}. Error: {str(e)}")
            return False
        except httpx.TimeoutException as e:
            logger.error(f"Timeout error sending email from {sender_mailbox_email}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error sending email from {sender_mailbox_email} using user token: {e}", exc_info=True)
            return False

    def _get_system_domains_for_workspace(self, workspace_id: int) -> List[str]:
        
        try:

            core_system_domains = ["enque.cc", "microsoftexchange"]
            
      
            mailbox_connections = self.db.query(MailboxConnection).filter(
                MailboxConnection.workspace_id == workspace_id,
                MailboxConnection.is_active == True
            ).all()
            
            # Extraer dominios únicos de los buzones
            workspace_domains = set()
            for mailbox in mailbox_connections:
                if mailbox.email and '@' in mailbox.email:
                    domain = mailbox.email.split('@')[-1].lower()
                    workspace_domains.add(domain)
            
        
            all_system_domains = core_system_domains + list(workspace_domains)
            

            
            return all_system_domains
            
        except Exception as e:
            logger.error(f"Error detecting system domains for workspace {workspace_id}: {str(e)}")
            # Fallback a dominios core si hay error
            return ["enque.cc", "microsoftexchange"]

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