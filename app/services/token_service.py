from datetime import datetime, timedelta
from typing import Optional

import requests
import httpx
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.core.config import settings
from app.utils.logger import logger
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken


class TokenService:
    """
    Dedicated service that owns every authentication and token-management
    concern for Microsoft Graph.  MicrosoftGraphService now delegates all
    token work to this class so that it can focus exclusively on mailbox
    and email-processing logic.
    """

    def __init__(self, db: Session, integration: Optional[MicrosoftIntegration]):
        self.db = db
        self.integration = integration
        self.has_env_config = bool(
            settings.MICROSOFT_CLIENT_ID
            and settings.MICROSOFT_CLIENT_SECRET
            and settings.MICROSOFT_TENANT_ID
        )

        # Application-wide (client-credential) token cache
        self._app_token: Optional[str] = None
        self._app_token_expires_at: datetime = datetime.utcnow()

    # ---------------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------------

    # --- Client-credential flow -------------------------------------------------
    def get_application_token(self) -> str:
        """
        Return a tenant-scoped application token obtained through the
        OAuth2 client-credentials flow.  Result is cached in-memory until it
        expires.
        """
        if self._app_token and self._app_token_expires_at > datetime.utcnow():
            return self._app_token

        if not self.integration and not self.has_env_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active Microsoft integration found",
            )

        tenant_id = (
            self.integration.tenant_id
            if self.integration
            else settings.MICROSOFT_TENANT_ID
        )
        client_id = (
            self.integration.client_id
            if self.integration
            else settings.MICROSOFT_CLIENT_ID
        )
        client_secret = (
            self.integration.client_secret
            if self.integration
            else settings.MICROSOFT_CLIENT_SECRET
        )

        token_endpoint = (
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        )
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }

        try:
            response = requests.post(token_endpoint, data=data, timeout=15)
            response.raise_for_status()
            token_data = response.json()
            self._app_token = token_data["access_token"]
            self._app_token_expires_at = datetime.utcnow() + timedelta(
                seconds=token_data["expires_in"]
            )
            return self._app_token
        except Exception as exc:
            logger.error("Failed to get application token", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to get application token: {exc}",
            ) from exc

    # --- Refresh flow ----------------------------------------------------------
    def refresh_token(self, token: MicrosoftToken) -> MicrosoftToken:
        """
        Synchronously refresh a delegated access token using its refresh_token.
        """
        if not self.integration and not self.has_env_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active Microsoft integration or env config found",
            )
        if not token.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No refresh token available to refresh.",
            )

        client_id = (
            self.integration.client_id
            if self.integration
            else settings.MICROSOFT_CLIENT_ID
        )
        client_secret = (
            self.integration.client_secret
            if self.integration
            else settings.MICROSOFT_CLIENT_SECRET
        )
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token",
            "scope": "offline_access Mail.Read Mail.ReadWrite Mail.Send User.Read",
        }
        token_endpoint = settings.MICROSOFT_TOKEN_URL

        try:
            response = requests.post(token_endpoint, data=data, timeout=15)
            response.raise_for_status()
            token_data = response.json()

            token.access_token = token_data["access_token"]
            if "refresh_token" in token_data:
                token.refresh_token = token_data["refresh_token"]
            token.expires_at = datetime.utcnow() + timedelta(
                seconds=token_data["expires_in"]
            )

            self.db.add(token)
            self.db.commit()
            self.db.refresh(token)
            logger.info("Successfully refreshed token ID: %s", token.id)
            return token
        except requests.exceptions.HTTPError as exc:
            logger.error(
                "HTTP error refreshing token ID %s: %s - %s",
                token.id,
                exc.response.status_code if exc.response else "N/A",
                exc.response.text if exc.response else "N/A",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to refresh token: {exc}",
            ) from exc
        except Exception as exc:
            logger.error(
                "Unexpected error refreshing token ID %s", token.id, exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error refreshing token: {exc}",
            ) from exc

    async def refresh_token_async(self, token: MicrosoftToken) -> MicrosoftToken:
        """
        Asynchronous version of `refresh_token` for use by background schedulers.
        """
        if not self.integration and not self.has_env_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active Microsoft integration or env config found",
            )
        if not token.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No refresh token available to refresh.",
            )

        client_id = (
            self.integration.client_id
            if self.integration
            else settings.MICROSOFT_CLIENT_ID
        )
        client_secret = (
            self.integration.client_secret
            if self.integration
            else settings.MICROSOFT_CLIENT_SECRET
        )
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token",
            "scope": "offline_access Mail.Read Mail.ReadWrite Mail.Send User.Read",
        }
        token_endpoint = settings.MICROSOFT_TOKEN_URL

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(token_endpoint, data=data)
            response.raise_for_status()
            token_data = response.json()

            token.access_token = token_data["access_token"]
            if "refresh_token" in token_data:
                token.refresh_token = token_data["refresh_token"]
            token.expires_at = datetime.utcnow() + timedelta(
                seconds=token_data["expires_in"]
            )

            self.db.add(token)
            self.db.commit()
            self.db.refresh(token)
            logger.info("Successfully refreshed token ID: %s", token.id)
            return token
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HTTP error refreshing token ID %s: %s - %s",
                token.id,
                exc.response.status_code if exc.response else "N/A",
                exc.response.text if exc.response else "N/A",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to refresh token: {exc}",
            ) from exc
        except Exception as exc:
            logger.error(
                "Unexpected async error refreshing token ID %s", token.id, exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error refreshing token: {exc}",
            ) from exc

    # --- Utility helpers -------------------------------------------------------
    def get_most_recent_valid_token(self) -> Optional[MicrosoftToken]:
        """
        Return the most recent *non-expired* token or attempt to synchronously
        refresh the newest expired-but-refreshable one.
        """
        token = (
            self.db.query(MicrosoftToken)
            .filter(MicrosoftToken.expires_at > datetime.utcnow())
            .order_by(MicrosoftToken.created_at.desc())
            .first()
        )
        if token:
            return token

        expired_refreshable_token = (
            self.db.query(MicrosoftToken)
            .filter(
                MicrosoftToken.refresh_token.isnot(None),
                MicrosoftToken.refresh_token != "",
            )
            .order_by(MicrosoftToken.expires_at.desc())
            .first()
        )
        if expired_refreshable_token:
            try:
                return self.refresh_token(expired_refreshable_token)
            except HTTPException:
                pass
            except Exception as exc:
                logger.error(
                    "Unexpected error during synchronous refresh of token ID %s: %s",
                    expired_refreshable_token.id,
                    exc,
                    exc_info=True,
                )
        return None

    async def check_and_refresh_all_tokens_async(self) -> None:
        """
        Periodic maintenance task: refresh any tokens expiring within the next
        10 minutes.  Intended for use by a background scheduler.
        """
        try:
            expiring_soon = datetime.utcnow() + timedelta(minutes=10)
            tokens_to_check = (
                self.db.query(MicrosoftToken)
                .filter(
                    MicrosoftToken.expires_at < expiring_soon,
                    MicrosoftToken.refresh_token.isnot(None),
                    MicrosoftToken.refresh_token != "",
                )
                .all()
            )
            for token_to_refresh in tokens_to_check:
                try:
                    await self.refresh_token_async(token_to_refresh)
                except Exception as exc:
                    logger.warning(
                        "Failed to refresh token ID %s during bulk check: %s",
                        token_to_refresh.id,
                        exc,
                    )
        except Exception as exc:
            logger.error(
                "Error during periodic token refresh check: %s", exc, exc_info=True
            )