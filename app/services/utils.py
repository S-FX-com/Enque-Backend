# backend/app/services/utils.py
from sqlalchemy.orm import Session
from typing import Optional # Import Optional
from app.models.user import User, UnassignedUser
from app.models.workspace import Workspace # Import Workspace if needed for type hint


def get_or_create_user(db: Session, email: str, name: Optional[str] = None, workspace_id: Optional[int] = None) -> Optional[User]:
    """
    Get an existing user by email within a specific workspace,
    or create a new one if not found. Adds to unassigned_users if created without company.

    Args:
        db: Database session
        email: User email address
        name: User name (optional)
        workspace_id: The ID of the workspace to search/create within. Required for creation.

    Returns:
        User object or None if creation failed due to missing workspace_id.
    """
    # Try to find user by email within the specific workspace
    # Note: This assumes email is unique *within* a workspace for Users.
    # If email should be globally unique, adjust the filter.
    user_query = db.query(User).filter(User.email == email)
    if workspace_id:
        user_query = user_query.filter(User.workspace_id == workspace_id)
    user = user_query.first()

    if user:
        # Ensure the found user belongs to the correct workspace if workspace_id was provided
        if workspace_id and user.workspace_id != workspace_id:
             # This case should ideally not happen if email is unique per workspace,
             # but handle defensively. Could indicate data inconsistency.
             print(f"Warning: Found user {email} but belongs to workspace {user.workspace_id}, expected {workspace_id}")
             return None # Or raise an error?
        return user

    # --- Create new user if not found ---
    # Workspace ID is required for creation
    if not workspace_id:
        print(f"Error: workspace_id is required to create a new user for email {email}")
        return None # Cannot create user without workspace context

    if not name:
        # Use part of email as name if not provided
        name = email.split('@')[0]

    # Create user with workspace_id (company_id will be None initially)
    user = User(
        name=name,
        email=email,
        workspace_id=workspace_id, # Assign workspace_id
        company_id=None # Explicitly set company_id to None
    )

    db.add(user)
    # It's better to commit after potentially adding to unassigned_users as well
    # db.commit()
    # db.refresh(user)

    # If the user has no company (which is always true for newly created users here),
    # add to unassigned_users for this workspace
    if user.company_id is None:
        # Check if already exists in unassigned_users for this workspace
        unassigned_user = db.query(UnassignedUser).filter(
            UnassignedUser.email == email,
            UnassignedUser.workspace_id == workspace_id # Filter by workspace
        ).first()
        if not unassigned_user:
            unassigned_user_entry = UnassignedUser(
                name=name,
                email=email,
                workspace_id=workspace_id # Assign workspace_id
                # phone is not available here unless passed in
            )
            db.add(unassigned_user_entry)

    # Commit both User and potentially UnassignedUser
    try:
        db.commit()
        db.refresh(user) # Refresh after commit to get ID etc.
        # Refresh unassigned_user_entry if needed
        # if 'unassigned_user_entry' in locals(): db.refresh(unassigned_user_entry)
    except Exception as e:
        db.rollback()
        print(f"Error committing new user/unassigned user for {email}: {e}")
        return None # Return None on commit error

    return user

# Removed the duplicated original function definition
