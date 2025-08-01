import os
from typing import List, Union, Optional
from pydantic_settings import BaseSettings
from pydantic import validator


class Settings(BaseSettings):
    API_V1_STR: str = "/v1"
    PROJECT_NAME: str = "Enque API"
    FRONTEND_URL: str = "https://app.enque.cc" 

    BACKEND_CORS_ORIGINS: Union[List[str], str] = ["https://app.enque.cc", "https://*.enque.cc"]

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    JWT_SECRET: str = "temporarysecret"  
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  
    AGENT_INVITATION_TOKEN_EXPIRE_HOURS: int = 72 
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 2 

    MYSQL_HOST: Optional[str] = None
    MYSQL_USER: Optional[str] = None
    MYSQL_PASSWORD: Optional[str] = None
    MYSQL_DATABASE: Optional[str] = None
    MYSQL_PORT: Optional[str] = None
    
    DATABASE_URI: Optional[str] = None
    
    @validator("DATABASE_URI", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: dict) -> Optional[str]:

        if v:
            return v

        mysql_url = os.getenv("MYSQL_URL") or os.getenv("DATABASE_URL")
        if mysql_url:
            return mysql_url

        db_params = ['MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_DATABASE']
        if all(values.get(x) for x in db_params):
            connection_string = "mysql+pymysql://"
            connection_string += f"{values.get('MYSQL_USER')}:{values.get('MYSQL_PASSWORD')}"
            connection_string += f"@{values.get('MYSQL_HOST')}:{values.get('MYSQL_PORT')}/{values.get('MYSQL_DATABASE')}"
            return connection_string

        return None

    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_TENANT_ID: str = ""
    MICROSOFT_REDIRECT_URI: str = "https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback"
    MICROSOFT_SCOPE: str = "offline_access Mail.Read Mail.ReadWrite"
    MICROSOFT_AUTH_URL: str = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    MICROSOFT_TOKEN_URL: str = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    MICROSOFT_GRAPH_URL: str = "https://graph.microsoft.com/v1.0"
    
    # Email Integration
    ENABLE_EMAIL_SYNC: bool = True
    EMAIL_SYNC_INTERVAL: int = 1 
    EMAIL_DEFAULT_FOLDER: str = "Inbox"
    EMAIL_DEFAULT_PRIORITY: str = "Medium"

    API_BASE_URL: str = "https://enque-backend-production.up.railway.app"

    SYSTEM_SENDER_EMAIL: str = "noreply@enque.cc" 
    CLEANUP_OLD_TOKENS: bool = True  

    REDIS_URL: Optional[str] = None  
    CACHE_EXPIRE_MICROSOFT_GRAPH: int = 300  
    CACHE_EXPIRE_USER_INFO: int = 3600  
    CACHE_EXPIRE_MAILBOX_LIST: int = 600  
    CACHE_EXPIRE_FOLDERS: int = 1800  
    
    DB_POOL_SIZE: int = 40  
    DB_MAX_OVERFLOW: int = 80  
    DB_POOL_TIMEOUT: int = 60  
    DB_POOL_RECYCLE: int = 3600  
    
    
    MS_GRAPH_RATE_LIMIT: int = 10  
    MS_GRAPH_BURST_LIMIT: int = 50  

    EMAIL_SYNC_BATCH_SIZE: int = 5  
    EMAIL_SYNC_CONCURRENT_CONNECTIONS: int = 2  
    EMAIL_SYNC_FREQUENCY_SECONDS: int = 180  

    class Config:

        env_file = None
        case_sensitive = True


settings = Settings()
