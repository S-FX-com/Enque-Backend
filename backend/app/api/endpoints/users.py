from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user, get_current_workspace
from app.database.session import get_db
from app.models.user import User, UnassignedUser
from app.models.agent import Agent
from app.models.company import Company
from app.models.workspace import Workspace
from app.schemas.user import User as UserSchema, UserCreate, UserUpdate
from app.schemas.user import UnassignedUser as UnassignedUserSchema

router = APIRouter()


@router.get("/", response_model=List[UserSchema])
async def read_users(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve all users
    """
    users = db.query(User).filter(User.workspace_id == current_workspace.id).order_by(User.name).offset(skip).limit(limit).all()
    return users


@router.post("/", response_model=UserSchema)
async def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Create a new user
    """
    # Check if email already exists in this workspace
    user = db.query(User).filter(
        User.email == user_in.email,
        User.workspace_id == current_workspace.id
    ).first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in this workspace",
        )
    
    # Treat company_id=0 as None/null
    if user_in.company_id == 0:
        user_in.company_id = None
    
    # Validate company_id if provided
    if user_in.company_id is not None:
        company = db.query(Company).filter(
            Company.id == user_in.company_id,
            Company.workspace_id == current_workspace.id
        ).first()
        if not company:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company with ID {user_in.company_id} does not exist in this workspace",
            )
    
    # Create new user with the current workspace
    user_data = user_in.dict()
    user_data["workspace_id"] = current_workspace.id
    user = User(**user_data)
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


@router.get("/{user_id}", response_model=UserSchema)
async def read_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get user by ID
    """
    user = db.query(User).filter(
        User.id == user_id,
        User.workspace_id == current_workspace.id
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.put("/{user_id}", response_model=UserSchema)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Update a user
    """
    user = db.query(User).filter(
        User.id == user_id,
        User.workspace_id == current_workspace.id
    ).first()
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
        company = db.query(Company).filter(
            Company.id == user_in.company_id,
            Company.workspace_id == current_workspace.id
        ).first()
        if not company:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company with ID {user_in.company_id} does not exist in this workspace",
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


@router.delete("/{user_id}", response_model=UserSchema)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Delete a user
    """
    user = db.query(User).filter(
        User.id == user_id,
        User.workspace_id == current_workspace.id
    ).first()
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


@router.get("/unassigned", response_model=List[UnassignedUserSchema])
async def read_unassigned_users(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve all unassigned users
    """
    unassigned_users = db.query(UnassignedUser).order_by(UnassignedUser.name).offset(skip).limit(limit).all()
    return unassigned_users 