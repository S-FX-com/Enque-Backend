from sqlalchemy.orm import Session
from typing import Optional 
from app.models.user import User, UnassignedUser
from app.models.workspace import Workspace 
from app.models.company import Company 
from sqlalchemy import func 
from sqlalchemy.exc import IntegrityError 


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
    user_query = db.query(User).filter(User.email == email)
    if workspace_id:
        user_query = user_query.filter(User.workspace_id == workspace_id)
    user = user_query.first()

    if user:
        if workspace_id and user.workspace_id != workspace_id:
             print(f"Warning: Found user {email} but belongs to workspace {user.workspace_id}, expected {workspace_id}")
             return None 
        return user
    if not workspace_id:
        print(f"Error: workspace_id is required to create a new user for email {email}")
        return None 

    try:
        if not name:

            name = email.split('@')[0]
        new_user_obj = User(
            name=name,
            email=email,
            workspace_id=workspace_id, 
            company_id=None 
        )

        user_email_domain = email.split('@')[-1].lower() if '@' in email else None
        if user_email_domain and workspace_id:
            company_to_assign = db.query(Company).filter(
                Company.workspace_id == workspace_id,
                func.lower(Company.email_domain) == user_email_domain
            ).first()

            if company_to_assign:
                new_user_obj.company_id = company_to_assign.id


        db.add(new_user_obj)
        if new_user_obj.company_id is None:
            unassigned_user_exists = db.query(UnassignedUser).filter(
                UnassignedUser.email == email,
                UnassignedUser.workspace_id == workspace_id 
            ).first()
            if not unassigned_user_exists:
                unassigned_user_entry = UnassignedUser(
                    name=name,
                    email=email,
                    workspace_id=workspace_id 
                )
                db.add(unassigned_user_entry)

        db.commit()
        db.refresh(new_user_obj) 
        return new_user_obj

    except IntegrityError as e:
        db.rollback()
        if e.orig and hasattr(e.orig, 'args') and isinstance(e.orig.args, tuple) and len(e.orig.args) > 0:
            error_code = e.orig.args[0]
            error_message = str(e.orig.args[1]) if len(e.orig.args) > 1 else ""

            if error_code == 1062 and ('users.ix_users_email' in error_message or 'ix_users_email' in error_message):
                print(f"Race condition handled: User {email} likely created by another process. Re-fetching.")
                existing_user = user_query.first()
                if existing_user:
                    return existing_user
                else:
                    print(f"Error: User {email} insert failed (duplicate), but not found on re-fetch.")
                    return None
            else:
                print(f"Unhandled IntegrityError during user creation for {email}: {e}")
                raise 
        else:
            print(f"Unexpected IntegrityError structure for {email}: {e}")
            raise

    except Exception as e:
        db.rollback()
        print(f"Generic error committing new user/unassigned user for {email}: {e}")
        return None

