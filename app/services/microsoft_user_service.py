import asyncio
import base64
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx
import requests
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.agent import Agent
from app.models.microsoft import MicrosoftToken
from app.models.workspace import Workspace
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


class MicrosoftUserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.graph_url = settings.MICROSOFT_GRAPH_URL

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

    def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Legacy sync version - tries cache first, then calls API"""
        try:
            if PERFORMANCE_SERVICES_AVAILABLE:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        task = asyncio.create_task(self._get_user_info_cached(access_token))
                        return asyncio.run_coroutine_threadsafe(task, loop).result(timeout=10)
                    else:
                        return loop.run_until_complete(self._get_user_info_cached(access_token))
                except Exception as cache_error:
                    logger.warning(f"Cache failed, falling back to direct API: {cache_error}")
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            response = requests.get(f"{self.graph_url}/me", headers=headers)
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"Failed to get user info: {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to get user info: {str(e)}")

    async def _get_user_profile_photo(self, access_token: str) -> Optional[bytes]:
        """
        Obtiene la foto de perfil del usuario desde Microsoft Graph API.
        Retorna los bytes de la imagen o None si no hay foto disponible.
        """
        try:
            headers = {"Authorization": f"Bearer {access_token}"}
            
            # Intentar obtener la foto de perfil
            photo_url = f"{self.graph_url}/me/photo/$value"
            async with httpx.AsyncClient() as client:
                response = await client.get(photo_url, headers=headers, timeout=30)

            if response.status_code == 200:
                logger.info("Successfully retrieved user profile photo from Microsoft Graph")
                return response.content
            elif response.status_code == 404:
                logger.info("User has no profile photo in Microsoft 365")
                return None
            else:
                logger.warning(f"Failed to get profile photo: HTTP {response.status_code}")
                return None
                
        except httpx.TimeoutException:
            logger.warning("Timeout while fetching profile photo from Microsoft Graph")
            return None
        except Exception as e:
            logger.error(f"Error fetching profile photo: {str(e)}")
            return None

    async def _upload_avatar_to_s3(self, photo_bytes: bytes, agent_id: int) -> Optional[str]:
        """
        Sube la foto de perfil a S3 y retorna la URL pública.
        """
        def _sync_upload():
            from app.services.s3_service import get_s3_service
            s3_service = get_s3_service()
            filename = f"agent_{agent_id}_avatar.jpg"
            folder = "avatars"
            return s3_service.upload_file(
                file_content=photo_bytes,
                filename=filename,
                folder=folder,
                content_type="image/jpeg"
            )

        try:
            avatar_url = await asyncio.to_thread(_sync_upload)
            logger.info(f"✅ Avatar uploaded to S3 for agent {agent_id}: {avatar_url}")
            return avatar_url
        except Exception as e:
            logger.error(f"❌ Error uploading avatar to S3 for agent {agent_id}: {str(e)}")
            return None

    async def handle_profile_linking(self, token_data: dict, user_info: dict, current_agent: Agent, workspace: Workspace, integration: "MicrosoftIntegration") -> MicrosoftToken:
        try:
            # Re-fetch the agent from the database within the current session to ensure it's attached
            stmt = select(Agent).filter(Agent.id == current_agent.id)
            result = await self.db.execute(stmt)
            agent_to_update = result.scalars().first()
            if not agent_to_update:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found during profile linking.")

            # 1. Check if microsoft_id already exists in another agent
            microsoft_id = user_info.get("id")
            microsoft_email = user_info.get("mail") or user_info.get("userPrincipalName")
            
            # Check if this Microsoft ID is already used by another agent
            stmt = select(Agent).filter(Agent.microsoft_id == microsoft_id)
            result = await self.db.execute(stmt)
            existing_agent_with_ms_id = result.scalars().first()
            
            # Only assign the microsoft_id if it's not already in use by another agent.
            # This is the key to allowing a single Microsoft user to exist in multiple workspaces.
            if not existing_agent_with_ms_id:
                agent_to_update.microsoft_id = microsoft_id
            elif existing_agent_with_ms_id.id != agent_to_update.id:
                logger.info(f"Microsoft ID {microsoft_id} is already linked to agent {existing_agent_with_ms_id.id}. "
                            f"The current agent {agent_to_update.id} will be authenticated without altering the existing link.")

            # 2. Assign all other Microsoft-related data to the current agent
            agent_to_update.microsoft_email = microsoft_email
            agent_to_update.microsoft_tenant_id = settings.MICROSOFT_TENANT_ID
            agent_to_update.microsoft_profile_data = json.dumps(user_info)
            
            refresh_token_val = token_data.get("refresh_token")

            if refresh_token_val:
                agent_to_update.microsoft_refresh_token = refresh_token_val
            else:
                logger.warning(f"No refresh token provided for agent {agent_to_update.id}")

            if agent_to_update.auth_method == "password":
                agent_to_update.auth_method = "both"
            
            # 3. Commit the critical token and profile data FIRST
            await self.db.commit()

            # 4. Handle non-critical updates (avatar) in a separate transaction
            try:
                photo_bytes = await self._get_user_profile_photo(token_data["access_token"])
                if photo_bytes:
                    avatar_url = await self._upload_avatar_to_s3(photo_bytes, agent_to_update.id)
                    if avatar_url:
                        agent_to_update.avatar_url = avatar_url
                        await self.db.commit() # Commit avatar update separately
            except Exception as avatar_error:
                logger.error(f"Error processing avatar for agent {agent_to_update.id}: {str(avatar_error)}")
                await self.db.rollback() # Rollback only the avatar transaction if it fails

            # 4. Refresh the agent object to get the latest state from the DB
            await self.db.refresh(agent_to_update)
            
            # 5. Invalidate cache (another non-critical operation)
            try:
                from app.core.cache import user_cache
                user_cache.delete(agent_to_update.id)
            except Exception as cache_error:
                logger.error(f"Failed to invalidate cache for agent {agent_to_update.id}: {cache_error}")

            # 6. Create a temporary MicrosoftToken object for the response
            token_obj_for_response = MicrosoftToken(
                integration_id=integration.id,
                agent_id=agent_to_update.id,
                access_token=token_data["access_token"],
                refresh_token=refresh_token_val,
                token_type=token_data["token_type"],
                expires_at=datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            )
            
            return token_obj_for_response
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error handling profile linking: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to link Microsoft profile: {str(e)}"
            )
