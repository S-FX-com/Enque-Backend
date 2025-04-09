from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.schemas.token import Token
from app.schemas.agent import AgentResponse
from app.models.agent import Agent
from app.libs.database import get_db
from app.core.security import get_current_active_user
from app.services.auth import login_and_get_token, get_current_user

router = APIRouter()

@router.post("/", response_model=Token, summary="Get Access Token")
def auth_route(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    try:
        return login_and_get_token(db, form_data.username, form_data.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.get("/me", response_model=AgentResponse, summary="Get Current User")
def auth_me_route(current_user: Agent = Depends(get_current_active_user)):
    return get_current_user(current_user)
