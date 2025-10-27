# backend/app/api/endpoints/users.py
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

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
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 1000,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve all users for the current workspace.
    """
    stmt = select(User).filter(User.workspace_id == current_workspace.id).order_by(User.name).offset(skip).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()
    return users


@router.post("/", response_model=UserSchema)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Create a new user within the current workspace.
    """
    # Check if email already exists in this workspace
    stmt = select(User).filter(
        User.email == user_in.email,
        User.workspace_id == current_workspace.id
    )
    result = await db.execute(stmt)
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in this workspace",
        )

    # Treat company_id=0 as None/null
    company_id_from_input = user_in.company_id if user_in.company_id != 0 else None

    # Validate company_id if provided directly
    if company_id_from_input is not None:
        stmt = select(Company).filter(
            Company.id == company_id_from_input,
            Company.workspace_id == current_workspace.id
        )
        result = await db.execute(stmt)
        company = result.scalars().first()
        if not company:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company with ID {company_id_from_input} does not exist in this workspace",
            )

    # Create new user with the current workspace
    user_data = user_in.dict(exclude={'company_id'}) 
    user_data["workspace_id"] = current_workspace.id
    user_data["company_id"] = company_id_from_input # Use the processed company_id from input
    
    user = User(**user_data)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Attempt automatic company assignment if company_id is still None
    if user.company_id is None and user.email:
        user_email_domain = user.email.split('@')[-1].lower() if '@' in user.email else None
        if user_email_domain:
            print(f"Attempting to auto-assign user {user.email} with domain {user_email_domain}")
            # Search for company with matching email_domain (case-insensitive)
            # Ensure email_domain in DB is also compared in lowercase if it's not guaranteed
            stmt = select(Company).filter(
                Company.workspace_id == current_workspace.id,
                func.lower(Company.email_domain) == user_email_domain 
            )
            result = await db.execute(stmt)
            company_to_assign = result.scalars().first() # Consider what to do if multiple companies have the same domain

            if company_to_assign:
                print(f"Found matching company: {company_to_assign.name} (ID: {company_to_assign.id}) for domain {user_email_domain}")
                user.company_id = company_to_assign.id
                db.add(user) # Re-add to session if needed, or let commit handle it
                await db.commit()
                await db.refresh(user)
                print(f"User {user.email} automatically assigned to company {company_to_assign.name}")
            else:
                print(f"No matching company found for domain {user_email_domain}")

    # If user has no company (either initially or after auto-assign attempt failed), 
    # add to unassigned_users for this workspace
    if user.company_id is None:
        # Check if already exists in unassigned_users for this workspace
        stmt = select(UnassignedUser).filter(
            UnassignedUser.email == user.email,
            UnassignedUser.workspace_id == current_workspace.id
        )
        result = await db.execute(stmt)
        unassigned_user_entry_exists = result.scalars().first()
        if not unassigned_user_entry_exists:
            unassigned_user_data = UnassignedUser(
                name=user.name,
                email=user.email,
                phone=user.phone,
                workspace_id=current_workspace.id
            )
            db.add(unassigned_user_data)
            await db.commit() # Commit the unassigned_user_data entry
            print(f"User {user.email} added to unassigned users list.")
        else:
            print(f"User {user.email} already in unassigned users list or has a company.")
    
    return user


# --- Endpoint to get unassigned users ---
# Changed response_model to UserSchema as we'll fetch from the main User table
@router.get("/unassigned", response_model=List[UserSchema])
async def read_unassigned_users(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve users from the main User table who are not assigned to a company
    within the current workspace.
    """
    # Query the main User table for users in the current workspace with no company_id
    stmt = select(User).filter(
        User.workspace_id == current_workspace.id,
        User.company_id == None # Use SQLAlchemy's way to check for NULL
    ).order_by(User.name).offset(skip).limit(limit)
    result = await db.execute(stmt)
    unassigned_users = result.scalars().all()
    return unassigned_users


@router.get("/{user_id}", response_model=UserSchema)
async def read_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get user by ID within the current workspace.
    """
    stmt = select(User).filter(
        User.id == user_id,
        User.workspace_id == current_workspace.id
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
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
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Update a user within the current workspace.
    """
    stmt = select(User).filter(
        User.id == user_id,
        User.workspace_id == current_workspace.id
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    print(f"--- Updating User ID: {user_id} ---") # Log start
    update_data = user_in.dict(exclude_unset=True)
    print(f"Received update data: {update_data}") # Log received payload

    # Process company_id specifically
    new_company_id = update_data.get("company_id") # Get potential new company_id
    if "company_id" in update_data: # Check if company_id was explicitly passed
        if new_company_id == 0:
            new_company_id = None # Treat 0 as None
            update_data["company_id"] = None # Ensure update_data reflects this

        # Validate company_id if it's not None
        if new_company_id is not None:
            stmt = select(Company).filter(
                Company.id == new_company_id,
                Company.workspace_id == current_workspace.id
            )
            result = await db.execute(stmt)
            company = result.scalars().first()
            if not company:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Company with ID {new_company_id} does not exist in this workspace",
                )
    else:
        # If company_id wasn't in the input, keep the existing one
        new_company_id = user.company_id

    # Store the old company_id for comparison *before* updating the user object
    old_company_id = user.company_id
    print(f"Old company_id: {old_company_id}") # Log old value

    # Update user attributes from update_data
    print("Attempting to set attributes...")
    for field, value in update_data.items():
        print(f"Setting {field} = {value}") # Log each attribute set
        setattr(user, field, value)

    print(f"User object before commit: company_id={user.company_id}, name={user.name}") # Log state before commit

    try:
        await db.commit()
        print("Commit successful.") # Log commit success
        await db.refresh(user)
        print(f"User object after refresh: company_id={user.company_id}") # Log state after refresh
    except Exception as e:
        print(f"Error during commit: {e}") # Log commit error
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database commit failed")

    # Handle unassigned users synchronization based on the change in company_id
    if old_company_id is None and new_company_id is not None:
        # User was assigned to a company, remove from unassigned_users for this workspace
        stmt = select(UnassignedUser).filter(
            UnassignedUser.email == user.email,
            UnassignedUser.workspace_id == current_workspace.id # Check workspace
        )
        result = await db.execute(stmt)
        unassigned_user = result.scalars().first()
        if unassigned_user:
            print(f"Removing user {user.email} from unassigned.")
            await db.delete(unassigned_user)
            await db.commit() # Commit this change specifically
    elif old_company_id is not None and new_company_id is None:
        print(f"Adding user {user.email} to unassigned.")
        # User was removed from a company, add to unassigned_users for this workspace
        stmt = select(UnassignedUser).filter(
            UnassignedUser.email == user.email,
            UnassignedUser.workspace_id == current_workspace.id # Check workspace
        )
        result = await db.execute(stmt)
        unassigned_user = result.scalars().first()
        if not unassigned_user:
            unassigned_user_entry = UnassignedUser(
                name=user.name,
                email=user.email,
                phone=user.phone,
                workspace_id=current_workspace.id # Assign workspace_id
            )
            db.add(unassigned_user_entry)
            await db.commit() # Commit this change specifically
    # If company_id didn't change or changed between two companies, do nothing with unassigned_users
    else:
         print(f"No change needed for unassigned_users table (old: {old_company_id}, new: {new_company_id}).")


    print(f"--- Update User ID: {user_id} Finished ---") # Log end
    return user


@router.delete("/{user_id}", response_model=UserSchema)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Delete a user within the current workspace.
    """
    stmt = select(User).filter(
        User.id == user_id,
        User.workspace_id == current_workspace.id
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # First remove from unassigned_users if exists (within the same workspace)
    stmt = select(UnassignedUser).filter(
        UnassignedUser.email == user.email,
        UnassignedUser.workspace_id == current_workspace.id # Check workspace
    )
    result = await db.execute(stmt)
    unassigned_user = result.scalars().first()
    if unassigned_user:
        await db.delete(unassigned_user)
        # Commit this deletion separately or ensure it's part of the final commit

    # Now delete the main user record
    await db.delete(user)
    await db.commit() # Commit both deletions

    return user
