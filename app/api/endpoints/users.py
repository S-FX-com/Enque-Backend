from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.user import User, UnassignedUser
from app.models.agent import Agent
from app.models.company import Company
from app.schemas.user import User as UserSchema, UserCreate, UserUpdate
from app.schemas.user import UnassignedUser as UnassignedUserSchema

router = APIRouter()


@router.get("/users", response_model=List[UserSchema])
async def read_users(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all users
    """
    users = db.query(User).order_by(User.name).offset(skip).limit(limit).all()
    return users


@router.post("/users", response_model=UserSchema)
async def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Create a new user
    """
    # Check if email already exists
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Treat company_id=0 as None/null
    if user_in.company_id == 0:
        user_in.company_id = None
    
    # Validate company_id if provided
    if user_in.company_id is not None:
        company = db.query(Company).filter(Company.id == user_in.company_id).first()
        if not company:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company with ID {user_in.company_id} does not exist",
            )
    
    # Create new user
    user = User(**user_in.dict())
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # If user has no company, add to unassigned_users
    if user.company_id is None:
        # Check if already exists in unassigned_users
        unassigned_user = db.query(UnassignedUser).filter(UnassignedUser.email == user.email).first()
        if not unassigned_user:
            unassigned_user = UnassignedUser(
                name=user.name,
                email=user.email,
                phone=user.phone
            )
            db.add(unassigned_user)
            db.commit()
    
    return user


@router.get("/users/{user_id}", response_model=UserSchema)
async def read_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get user by ID
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.put("/users/{user_id}", response_model=UserSchema)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Update a user
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Treat company_id=0 as None/null
    if user_in.company_id == 0:
        user_in.company_id = None
    
    # Validate company_id if provided
    if user_in.company_id is not None:
        company = db.query(Company).filter(Company.id == user_in.company_id).first()
        if not company:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company with ID {user_in.company_id} does not exist",
            )
    
    # Store the old company_id for comparison
    old_company_id = user.company_id
    
    # Update user attributes
    update_data = user_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    
    # Handle unassigned users synchronization
    if old_company_id is None and user.company_id is not None:
        # User was assigned to a company, remove from unassigned_users
        unassigned_user = db.query(UnassignedUser).filter(UnassignedUser.email == user.email).first()
        if unassigned_user:
            db.delete(unassigned_user)
            db.commit()
    elif old_company_id is not None and user.company_id is None:
        # User was removed from a company, add to unassigned_users
        unassigned_user = db.query(UnassignedUser).filter(UnassignedUser.email == user.email).first()
        if not unassigned_user:
            unassigned_user = UnassignedUser(
                name=user.name,
                email=user.email,
                phone=user.phone
            )
            db.add(unassigned_user)
            db.commit()
    
    return user


@router.delete("/users/{user_id}", response_model=UserSchema)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Delete a user
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # First remove from unassigned_users if exists
    unassigned_user = db.query(UnassignedUser).filter(UnassignedUser.email == user.email).first()
    if unassigned_user:
        db.delete(unassigned_user)
    
    db.delete(user)
    db.commit()
    
    return user


@router.get("/unassigned-users", response_model=List[UnassignedUserSchema])
async def read_unassigned_users(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all unassigned users
    """
    users = db.query(UnassignedUser).order_by(UnassignedUser.name).offset(skip).limit(limit).all()
    return users 