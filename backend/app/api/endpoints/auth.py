from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, verify_password, get_password_hash
from app.database.session import get_db
from app.models.agent import Agent
from app.schemas.token import Token
from app.schemas.agent import Agent as AgentSchema, AgentCreate
from app.api.dependencies import get_current_active_user

router = APIRouter()


@router.post("/login", response_model=Token)
async def login_access_token(
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    # Find user by email
    user = db.query(Agent).filter(Agent.email == form_data.username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    
    # Verify password
    if not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )
    
    return {
        "access_token": token,
        "token_type": "bearer",
    }


@router.get("/me", response_model=AgentSchema)
async def get_current_user(
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get currently authenticated user
    """
    return current_user


@router.post("/register/agent", response_model=AgentSchema)
async def register_agent(
    user_in: AgentCreate, db: Session = Depends(get_db)
) -> Any:
    """
    Register a new agent (public endpoint for initial registration)
    """
    # Check if email already exists
    user = db.query(Agent).filter(Agent.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Create new agent
    user = Agent(
        name=user_in.name,
        email=user_in.email,
        password=get_password_hash(user_in.password),
        role=user_in.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user 