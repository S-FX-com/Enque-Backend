from typing import Optional
from pydantic import BaseModel, validator
from datetime import datetime, timezone

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None # Add expires_in to match the actual response


class TokenPayload(BaseModel):
    sub: Optional[int] = None
    exp: Optional[datetime] = None
    
    @validator("exp")
    def check_expiration(cls, v):
        if v is not None:
            # Convertir la fecha actual a UTC para una comparación correcta
            now_utc = datetime.now(timezone.utc)
            # Asegurarse de que ambas fechas tienen información de zona horaria
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
                
            if v < now_utc:
                raise ValueError("Token has expired")
        return v


class TokenData(BaseModel):
    id: Optional[int] = None
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
