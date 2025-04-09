import os
from typing import List, Union, Optional
from pydantic_settings import BaseSettings
from pydantic import validator


class Settings(BaseSettings):
    # CORS Configuration
    BACKEND_CORS_ORIGINS: Union[List[str], str] = []
    
    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # JWT Configuration
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Database
    DATABASE_URL: str

    # Microsoft Graph API Configuration
    MICROSOFT_CLIENT_ID: str = "9793e065-fc8e-4920-a72e-12eee326e783"
    MICROSOFT_CLIENT_SECRET: str = "BvH8Q~zwL6XzPTWwkW1ryLaq4bfbi7u-KYq5NcXe"
    MICROSOFT_TENANT_ID: str = "76d9eabb-931c-452b-9e08-058b058b6581"
    MICROSOFT_REDIRECT_URI: str = "https://obiedesk-backend-production.up.railway.app/v1/microsoft/auth/callback"
    MICROSOFT_SCOPE: str = "offline_access Mail.Read Mail.ReadWrite"
    
    # Microsoft Graph API URLs
    MICROSOFT_AUTH_URL: str = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    MICROSOFT_TOKEN_URL: str = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    MICROSOFT_GRAPH_URL: str = "https://graph.microsoft.com/v1.0"
    
    # Email Integration
    ENABLE_EMAIL_SYNC: bool = True
    EMAIL_SYNC_INTERVAL: int = 1  # minutes
    EMAIL_DEFAULT_FOLDER: str = "Inbox"
    EMAIL_DEFAULT_PRIORITY: str = "Medium"
    
    # Base URL for API
    API_BASE_URL: str = "https://obiedesk-backend-production.up.railway.app"
    
    # Token Management
    CLEANUP_OLD_TOKENS: bool = True  # Limpiar tokens antiguos excepto los 5 más recientes

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings() 