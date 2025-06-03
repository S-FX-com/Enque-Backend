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

    # System Email Sender
    SYSTEM_SENDER_EMAIL: str = "noreply@enque.cc" # Default system sender email, ensure this mailbox exists or app has send-as permission

    # Token Management
    CLEANUP_OLD_TOKENS: bool = True  # Limpiar tokens antiguos excepto los 5 más recientes

    class Config:
        # Leer variables de entorno directamente, sin depender de archivos .env
        env_file = None
        case_sensitive = True


settings = Settings()
