from datetime import datetime, timedelta, timezone
from typing import Any, Union, Dict, Optional
import hashlib

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Password context for hashing - configuración más robusta
pwd_context = CryptContext(
    schemes=["bcrypt"], 
    deprecated="auto",
    bcrypt__default_ident="2b"  # Especificar explícitamente el identificador bcrypt
)

def _prepare_password(password: str) -> bytes:
    """
    Prepara la contraseña para bcrypt:
    - Convierte a bytes usando UTF-8
    - Trunca a 72 bytes si es necesario (límite de bcrypt)
    - Para contraseñas muy largas, usa un hash SHA-256 primero
    """
    if isinstance(password, str):
        password_bytes = password.encode('utf-8')
    else:
        password_bytes = password
    
    # Si la contraseña es muy larga, usar SHA-256 primero
    if len(password_bytes) > 72:
        # Usar SHA-256 para reducir contraseñas largas manteniendo entropía
        password_hash = hashlib.sha256(password_bytes).hexdigest()
        password_bytes = password_hash.encode('utf-8')
    
    return password_bytes

# Verify password
def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        prepared_password = _prepare_password(plain_password)
        return pwd_context.verify(prepared_password, hashed_password)
    except Exception as e:
        # Log del error pero no exponer detalles internos
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error verifying password: {e}")
        return False

# Hash password
def get_password_hash(password: str) -> str:
    try:
        prepared_password = _prepare_password(password)
        return pwd_context.hash(prepared_password)
    except Exception as e:
        # Log del error pero lanzar excepción porque es crítico
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error hashing password: {e}")
        raise ValueError("Failed to hash password")

# Create access token
def create_access_token(
    subject: Union[str, Any], 
    expires_delta: timedelta = None,
    extra_data: Optional[Dict[str, Any]] = None
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    # Inicializar el payload con los datos básicos
    to_encode = {"exp": expire, "sub": str(subject)}
    
    # Añadir datos adicionales al token si se proporcionan
    if extra_data:
        to_encode.update(extra_data)
    
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt