from sqlalchemy.orm import Session
from app.models.user import User, UnassignedUser


def get_or_create_user(db: Session, email: str, name: str = None) -> User:
    """
    Get an existing user by email or create a new one if not found
    
    Args:
        db: Database session
        email: User email address
        name: User name (optional)
        
    Returns:
        User object
    """
    # Try to find user by email
    user = db.query(User).filter(User.email == email).first()
    
    if user:
        return user
        
    # Create new user if not found
    if not name:
        # Use part of email as name if not provided
        name = email.split('@')[0]
        
    # Create user
    user = User(
        name=name,
        email=email
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # If the user has no company, add to unassigned_users
    if user.company_id is None:
        # Check if already exists in unassigned_users
        unassigned_user = db.query(UnassignedUser).filter(UnassignedUser.email == email).first()
        if not unassigned_user:
            unassigned_user = UnassignedUser(
                name=name,
                email=email
            )
            db.add(unassigned_user)
            db.commit()
    
    return user 