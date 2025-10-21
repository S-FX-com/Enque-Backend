import base64
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
import requests
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent import Agent
from app.models.microsoft import (EmailSyncConfig, MailboxConnection,
                                  MicrosoftIntegration, MicrosoftToken)
from app.models.workspace import Workspace
from app.services.microsoft_user_service import MicrosoftUserService
from app.utils.logger import logger


class MicrosoftAuthService:
    def __init__(self, db: Session, integration: MicrosoftIntegration, user_service: MicrosoftUserService):
        self.db = db
        self.integration = integration
        self.user_service = user_service
        self.has_env_config = bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET and settings.MICROSOFT_TENANT_ID)
        self.auth_url = settings.MICROSOFT_AUTH_URL
        self.token_url = settings.MICROSOFT_TOKEN_URL
        self._app_token = None
        self._app_token_expires_at = datetime.utcnow()

    def get_application_token(self) -> str:
        if self._app_token and self._app_token_expires_at > datetime.utcnow():
            return self._app_token

        if not self.integration and not self.has_env_config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active Microsoft integration found")

        tenant_id = self.integration.tenant_id if self.integration else settings.MICROSOFT_TENANT_ID
        client_id = self.integration.client_id if self.integration else settings.MICROSOFT_CLIENT_ID
        client_secret = self.integration.client_secret if self.integration else settings.MICROSOFT_CLIENT_SECRET
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
        prompt: Optional[str] = "consent" 
    ) -> str:
        """Get the URL for Microsoft OAuth authentication flow, allowing custom redirect URI, scopes, state and prompt."""
        if not self.integration and not self.has_env_config:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Microsoft integration not configured")

        client_id = self.integration.client_id if self.integration else settings.MICROSOFT_CLIENT_ID

        final_redirect_uri = redirect_uri or (self.integration.redirect_uri if self.integration else settings.MICROSOFT_REDIRECT_URI)
        if not final_redirect_uri:
             final_redirect_uri = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
             logger.warning(f"No redirect_uri provided or configured, falling back to default: {final_redirect_uri}")

        default_scopes = ["offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared", "User.Read", "TeamsActivity.Send"]
        final_scopes = scopes if scopes else default_scopes
        scope_string = " ".join(final_scopes)
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
        token_endpoint = self.token_url  
        try:
            response = requests.post(token_endpoint, data=data)
            response.raise_for_status()
            token_data = response.json()
            refresh_token_val = token_data.get("refresh_token", "")
            user_info = self.user_service.get_user_info(token_data["access_token"])
            mailbox_email = user_info.get("mail")
            if not mailbox_email:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not get email address from Microsoft user info")
            workspace_id: Optional[int] = None
            agent_id: Optional[int] = None
            connection_id: Optional[int] = None  
            is_reconnect: bool = False  
            
            if state:
                try:
                    missing_padding = len(state) % 4
                    if missing_padding: state += '=' * (4 - missing_padding)
                    decoded_state_json = base64.urlsafe_b64decode(state).decode('utf-8')
                    state_data = json.loads(decoded_state_json)
                    ws_id_str = state_data.get('workspace_id')
                    ag_id_str = state_data.get('agent_id')
                    conn_id_str = state_data.get('connection_id')  
                    is_reconnect_str = state_data.get('is_reconnect')  
                    
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
            
            workspace = self.db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if not workspace: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workspace with ID {workspace_id} not found.")

            # --- START: Logic to handle both auth and profile_link flows ---
            try:
                missing_padding = len(state) % 4
                if missing_padding: state += '=' * (4 - missing_padding)
                decoded_state_json = base64.urlsafe_b64decode(state).decode('utf-8')
                state_data = json.loads(decoded_state_json)
                flow_type = state_data.get('flow')
                
                current_agent = None
                if flow_type == 'profile_link':
                    if not agent_id: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent ID missing in state for profile_link flow.")
                    current_agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
                    if not current_agent: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent with ID {agent_id} not found.")
                    if current_agent.workspace_id != workspace.id: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent does not belong to the specified workspace.")
                
                elif flow_type == 'auth':
                    microsoft_id = user_info.get("id")
                    microsoft_email = user_info.get("mail") or user_info.get("userPrincipalName")

                    # New Strategy: Prioritize finding the user in the target workspace and handle multi-workspace scenarios.
                    
                    # 1. Find agent by microsoft_id in the target workspace.
                    agent = self.db.query(Agent).filter(Agent.microsoft_id == microsoft_id, Agent.workspace_id == workspace_id).first()

                    # 2. If not found, find by email in the target workspace.
                    if not agent:
                        agent = self.db.query(Agent).filter(Agent.email == microsoft_email, Agent.workspace_id == workspace_id).first()

                    # 3. If still not found, it might be a new agent for this workspace.
                    if not agent:
                        # Before creating, check if this Microsoft account is linked to an agent in another workspace.
                        # This is to avoid the IntegrityError, as microsoft_id must be unique.
                        is_ms_id_already_used = self.db.query(Agent).filter(Agent.microsoft_id == microsoft_id).first() is not None
                        
                        logger.info(f"Creating new Microsoft agent: {microsoft_email} in workspace {workspace_id}")
                        display_name = user_info.get("displayName", microsoft_email.split("@")[0])
                        agent = Agent(
                            name=display_name,
                            email=microsoft_email,
                            role="agent",
                            auth_method="microsoft",
                            workspace_id=workspace_id,
                            is_active=True
                        )
                        # Only set microsoft_id on the new agent if it's not already in use in another workspace.
                        if not is_ms_id_already_used:
                            agent.microsoft_id = microsoft_id

                        self.db.add(agent)
                        self.db.flush()  # Flush to get the agent ID

                    current_agent = agent

                if current_agent and flow_type in ['profile_link', 'auth']:
                    logger.info(f"'{flow_type}' flow detected for agent {current_agent.id}. Updating agent with latest token info.")
                    return self.user_service.handle_profile_linking(token_data, user_info, current_agent, workspace, self.integration)

            except Exception as decode_err:
                logger.warning(f"Could not decode state for flow check: {decode_err}")
            # --- END: Logic to handle both auth and profile_link flows ---
            
            # Fallback for mailbox connection if flow is not auth or profile_link
            if not agent_id: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent ID missing in state parameter for mailbox flow.")
            current_agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
            if not current_agent: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent with ID {agent_id} not found.")
            if current_agent.workspace_id != workspace.id: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent does not belong to the specified workspace.")
            
            if needs_integration:
                self.integration = MicrosoftIntegration(
                    tenant_id=tenant_id, client_id=client_id, client_secret=client_secret,
                    redirect_uri=settings.MICROSOFT_REDIRECT_URI, scope=scope, is_active=True)
                self.db.add(self.integration); self.db.commit(); self.db.refresh(self.integration)
            mailbox_connection = None
            if is_reconnect and connection_id:
                mailbox_connection = self.db.query(MailboxConnection).filter(
                    MailboxConnection.id == connection_id,
                    MailboxConnection.workspace_id == workspace_id
                ).first()
                
                if not mailbox_connection:
                    logger.error(f"Could not find mailbox connection with ID {connection_id} for workspace {workspace_id}")
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Mailbox connection with ID {connection_id} not found")
                if mailbox_connection.email != mailbox_email:
                    logger.info(f"Updating email address for connection {connection_id} from {mailbox_connection.email} to {mailbox_email}")
                    mailbox_connection.email = mailbox_email
                    mailbox_connection.display_name = user_info.get("displayName", "Microsoft User")
                old_tokens = self.db.query(MicrosoftToken).filter(
                    MicrosoftToken.mailbox_connection_id == mailbox_connection.id
                ).all()
                
                if old_tokens:
                    for old_token in old_tokens:
                        self.db.delete(old_token)
                    logger.info(f"Deleted {len(old_tokens)} old token(s) for mailbox connection {connection_id}")
                
                self.db.commit()
            else:
                mailbox_connection = self.db.query(MailboxConnection).filter(
                    MailboxConnection.email == mailbox_email, 
                    MailboxConnection.workspace_id == workspace.id
                ).first()
                
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
        token_endpoint = self.token_url  
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
                    logger.warning(f"Refresh token for token ID {token.id} is invalid or expired. Deleting it.")
                    self.db.delete(token)
                    self.db.commit()
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
        token_endpoint = self.token_url  
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
                    logger.warning(f"Refresh token for token ID {token.id} is invalid or expired. Deleting it.")
                    self.db.delete(token)
                    self.db.commit()
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid. Re-authentication required.")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to refresh token: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error refreshing token ID {token.id}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected error refreshing token: {str(e)}")
