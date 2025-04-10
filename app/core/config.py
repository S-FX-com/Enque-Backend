from typing import List, Union
from pydantic_settings import BaseSettings
from pydantic import validator
import re


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

    def get_cors_regex(self) -> str:
        # Convierte las origins a regex para permitir subdominios
        patterns = []
        for origin in self.BACKEND_CORS_ORIGINS:
            parsed = re.match(r"^(https?://)([^:/]+)(:\d+)?$", origin)
            if parsed:
                scheme, domain, port = parsed.groups()
                escaped_domain = re.escape(domain)
                subdomain_pattern = rf"{scheme}([a-zA-Z0-9\-]+\.)*{escaped_domain}"
                if port:
                    subdomain_pattern += re.escape(port)
                patterns.append(subdomain_pattern)
        return "|".join(patterns)

    # JWT Configuration
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Database
    DATABASE_URL: str

    # Microsoft Graph API Configuration
    MICROSOFT_CLIENT_ID: str
    MICROSOFT_CLIENT_SECRET: str
    MICROSOFT_TENANT_ID: str
    MICROSOFT_REDIRECT_URI: str
    MICROSOFT_SCOPE: str
    
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