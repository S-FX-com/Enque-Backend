import asyncio
from typing import Any, Dict, List, Optional

import httpx
import requests
from fastapi import HTTPException, status

from app.core.config import settings
from app.utils.logger import logger

try:
    from app.services.cache_service import cached_microsoft_graph
    from app.services.rate_limiter import rate_limited
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


class MicrosoftGraphClient:
    def __init__(self):
        self.graph_url = settings.MICROSOFT_GRAPH_URL

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

    def mark_email_as_read(self, app_token: str, user_email: str, message_id: str) -> bool:
        try:
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}; data = {"isRead": True}
            response = requests.patch(endpoint, headers=headers, json=data); response.raise_for_status()
            logger.info(f"Marked email {message_id} as read for user {user_email}."); return True
        except Exception as e: logger.error(f"Error marking email {message_id} as read for user {user_email}: {str(e)}"); return False

    def get_or_create_processed_folder(self, app_token: str, user_email: str, folder_name: str) -> Optional[str]:
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

    def move_email_to_folder(self, app_token: str, user_email: str, message_id: str, folder_id: str) -> Optional[str]:
        try:
            endpoint = f"{self.graph_url}/users/{user_email}/messages/{message_id}/move"
            headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}; data = {"destinationId": folder_id}
            response = requests.post(endpoint, headers=headers, json=data); response.raise_for_status()
            response_data = response.json(); new_message_id = response_data.get("id", message_id)
            if new_message_id != message_id: logger.info(f"Email ID changed from {message_id} to {new_message_id} after move.")
            return new_message_id
        except Exception as e: logger.error(f"Error moving email {message_id} to folder {folder_id} for user {user_email}: {str(e)}"); return message_id

    async def send_teams_activity_notification(self, access_token: str, agent_microsoft_id: str, title: str, message: str, link_to_ticket: str, subdomain: str):
        """
        Sends an activity feed notification to a specific agent in Microsoft Teams.
        """
        notification_endpoint = f"{self.graph_url}/users/{agent_microsoft_id}/teamwork/sendActivityNotification"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        teams_app_id = "9793e065-fc8e-4920-a72e-12eee326e783"
        ticket_id = link_to_ticket.split('/')[-1]

        # The subEntityId will be passed to our backend redirector
        # It contains the necessary info to construct the final URL
        import urllib.parse
        sub_entity_data = f"{ticket_id}|{subdomain}"
        encoded_sub_entity = urllib.parse.quote(sub_entity_data, safe='')

        # This is the deep link that Teams requires for the webUrl field
        teams_deep_link = f"https://teams.microsoft.com/l/entity/{teams_app_id}/teams-redirect?subEntityId={encoded_sub_entity}"
        
        logger.info(f"Constructed Teams deep link: {teams_deep_link}")
        logger.info(f"Target redirect URL to be built by backend: https://{subdomain}.enque.cc/tickets/{ticket_id}")

        # The final URL for the template text can be direct, as it's just for display
        final_web_url = f"https://{subdomain}.enque.cc/tickets/{ticket_id}"

        # Construct the notification payload
        notification_payload = {
            "topic": {
                "source": "text",
                "value": title,
                "webUrl": teams_deep_link  # Use the required Teams deep link here
            },
            "activityType": "ticketNotification", # This must match a type in your manifest
            "previewText": {
                "content": message
            },
            "recipient": {
                "@odata.type": "microsoft.graph.aadUserNotificationRecipient",
                "userId": agent_microsoft_id
            },
            "templateParameters": [
                { "name": "action", "value": title },
                { "name": "ticketId", "value": f"#{ticket_id}" },
                { "name": "workspaceUrl", "value": final_web_url } # Display the final URL in the notification text
            ]
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(notification_endpoint, headers=headers, json=notification_payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(f"Error response from Microsoft Graph API: {exc.response.text}")
            raise exc
        
        logger.info(f"Successfully sent Teams activity notification to agent {agent_microsoft_id} for ticket link: {link_to_ticket}")
