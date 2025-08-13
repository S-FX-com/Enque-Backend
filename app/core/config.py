import os
from typing import List, Union, Optional
from pydantic_settings import BaseSettings
from pydantic import validator


class Settings(BaseSettings):
    API_V1_STR: str = "/v1"
    PROJECT_NAME: str = "Enque API"
    FRONTEND_URL: str = "https://app.enque.cc" # Default Frontend URL (should be overridden by env var in production/dev)
    
    # CORS Configuration
    BACKEND_CORS_ORIGINS: Union[List[str], str] = ["https://app.enque.cc", "https://*.enque.cc"]

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # JWT Configuration
    JWT_SECRET: str = "temporarysecret"  # Valor predeterminado temporal
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    AGENT_INVITATION_TOKEN_EXPIRE_HOURS: int = 72 # Agent invitation token validity in hours
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 2 # Password reset token validity in hours


    # Database Configuration
    MYSQL_HOST: Optional[str] = None
    MYSQL_USER: Optional[str] = None
    MYSQL_PASSWORD: Optional[str] = None
    MYSQL_DATABASE: Optional[str] = None
    MYSQL_PORT: Optional[str] = None
    
    DATABASE_URI: Optional[str] = None
    
    @validator("DATABASE_URI", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: dict) -> Optional[str]:
        # Si ya tenemos un valor, lo devolvemos
        if v:
            return v
            
        # Verificar si estamos usando MYSQL_URL directamente (para Railway)
        mysql_url = os.getenv("MYSQL_URL") or os.getenv("DATABASE_URL")
        if mysql_url:
            return mysql_url
            
        # Construir URL de conexión si no hay MYSQL_URL
        db_params = ['MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_DATABASE']
        if all(values.get(x) for x in db_params):
            connection_string = "mysql+pymysql://"
            connection_string += f"{values.get('MYSQL_USER')}:{values.get('MYSQL_PASSWORD')}"
            connection_string += f"@{values.get('MYSQL_HOST')}:{values.get('MYSQL_PORT')}/{values.get('MYSQL_DATABASE')}"
            return connection_string
        
        # Si no hay configuración de base de datos, devolver None
        return None

    # Microsoft Graph API Configuration
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_TENANT_ID: str = ""
    MICROSOFT_REDIRECT_URI: str = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
    MICROSOFT_SCOPE: str = "offline_access Mail.Read Mail.ReadWrite"
    
    # Microsoft Graph API URLs - Using /common for multitenant support
    MICROSOFT_AUTH_URL: str = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    MICROSOFT_TOKEN_URL: str = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    MICROSOFT_GRAPH_URL: str = "https://graph.microsoft.com/v1.0"
    
    # Email Integration
    ENABLE_EMAIL_SYNC: bool = True
    EMAIL_SYNC_INTERVAL: int = 1  # minutes
    EMAIL_DEFAULT_FOLDER: str = "Inbox"
    EMAIL_DEFAULT_PRIORITY: str = "Medium"
    
    # Base URL for API
    API_BASE_URL: str = "https://enque-backend-production.up.railway.app"
    
    @property
    def clean_api_base_url(self) -> str:
        """Return API_BASE_URL without trailing slash"""
        return self.API_BASE_URL.rstrip('/')

    # System Email Sender
    SYSTEM_SENDER_EMAIL: str = "noreply@enque.cc" # Default system sender email, ensure this mailbox exists or app has send-as permission

    # Token Management
    CLEANUP_OLD_TOKENS: bool = True  # Limpiar tokens antiguos excepto los 5 más recientes

    # ⚡ Performance & Caching Configuration
    REDIS_URL: Optional[str] = None  # Redis connection URL for caching
    CACHE_EXPIRE_MICROSOFT_GRAPH: int = 300  # Microsoft Graph cache expiration (5 minutes)
    CACHE_EXPIRE_USER_INFO: int = 3600  # User info cache (1 hour)
    CACHE_EXPIRE_MAILBOX_LIST: int = 600  # Mailbox list cache (10 minutes)
    CACHE_EXPIRE_FOLDERS: int = 1800  # Folder list cache (30 minutes)
    
    # Database Connection Pool - EMERGENCY INCREASE for email processing
    DB_POOL_SIZE: int = 40  # Increased from 25 to 40 for email sync stability
    DB_MAX_OVERFLOW: int = 80  # Increased from 50 to 80 to handle peak loads
    DB_POOL_TIMEOUT: int = 60  # Increased from 30 to 60 seconds
    DB_POOL_RECYCLE: int = 3600  # Recycle connections after 1 hour
    
    # Rate Limiting for Microsoft Graph
    MS_GRAPH_RATE_LIMIT: int = 10  # Requests per second to Microsoft Graph
    MS_GRAPH_BURST_LIMIT: int = 50  # Burst limit
    
    # Background Job Configuration - EMERGENCY TUNING for DB pool stability
    EMAIL_SYNC_BATCH_SIZE: int = 5  # 🚑 REDUCED: From 10 to 5 to minimize DB connections
    EMAIL_SYNC_CONCURRENT_CONNECTIONS: int = 2  # 🚑 REDUCED: From 3 to 2 max concurrent syncs
    EMAIL_SYNC_FREQUENCY_SECONDS: int = 180  # 🚑 INCREASED: From 120 to 180 seconds (3 min intervals)

    class Config:
        # Leer variables de entorno directamente, sin depender de archivos .env
        env_file = None
        case_sensitive = True


settings = Settings()
