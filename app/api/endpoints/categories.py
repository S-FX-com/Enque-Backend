from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.api import dependencies
from app.schemas import category as category_schema
from app.models import category as category_model
from app.models.agent import Agent # Import Agent model for current_user type hint

router = APIRouter()

@router.post("/", response_model=category_schema.Category, status_code=status.HTTP_201_CREATED)
def create_category(
    *,
    db: Session = Depends(dependencies.get_db),
    category_in: category_schema.CategoryCreate,
    current_user: Agent = Depends(dependencies.get_current_active_user) # Require active user
):
    """
    Create a new category within the user's workspace.
    """
    # Optional: Check if category with the same name already exists
    existing_category = db.query(category_model.Category).filter(category_model.Category.name == category_in.name).first()
    if existing_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A category with this name already exists in this workspace.",
        )
        
    # Ensure workspace_id from input matches current user's workspace or set it
    if category_in.workspace_id != current_user.workspace_id:
         raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN,
             detail="Cannot create category in another workspace.",
         )
         
    # Create category with correct workspace_id
    db_category = category_model.Category(
        name=category_in.name, 
        workspace_id=current_user.workspace_id
    )
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category

@router.get("/", response_model=List[category_schema.Category])
def read_categories(
    db: Session = Depends(dependencies.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(dependencies.get_current_active_user) # Require active user
):
    """
    Retrieve categories for the current user's workspace.
    """
    categories = db.query(category_model.Category).filter(
        category_model.Category.workspace_id == current_user.workspace_id
    ).offset(skip).limit(limit).all()
    return categories

@router.get("/{category_id}", response_model=category_schema.Category)
def read_category(
    *,
    db: Session = Depends(dependencies.get_db),
    category_id: int,
    current_user: Agent = Depends(dependencies.get_current_active_user) # Require active user
):
    """
    Get category by ID, ensuring it belongs to the user's workspace.
    """
    category = db.query(category_model.Category).filter(
        category_model.Category.id == category_id,
        category_model.Category.workspace_id == current_user.workspace_id # Check workspace
    ).first()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category

@router.put("/{category_id}", response_model=category_schema.Category)
def update_category(
    *,
    db: Session = Depends(dependencies.get_db),
    category_id: int,
    category_in: category_schema.CategoryUpdate,
    current_user: Agent = Depends(dependencies.get_current_active_user) # Require active user
):
    """
    Update a category, ensuring it belongs to the user's workspace.
    """
    category = db.query(category_model.Category).filter(
        category_model.Category.id == category_id,
        category_model.Category.workspace_id == current_user.workspace_id # Check workspace
    ).first()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    # Optional: Check if the new name already exists within the same workspace
    if category_in.name and category_in.name != category.name:
        existing_category = db.query(category_model.Category).filter(
            category_model.Category.name == category_in.name,
            category_model.Category.workspace_id == current_user.workspace_id
        ).first()
        if existing_category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A category with this name already exists in this workspace.",
            )

    update_data = category_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)
    
    db.add(category)
    db.commit()
    db.refresh(category)
    return category

@router.delete("/{category_id}", response_model=category_schema.Category)
def delete_category(
    *,
    db: Session = Depends(dependencies.get_db),
    category_id: int,
    current_user: Agent = Depends(dependencies.get_current_active_user) # Require active user
):
    """
    Delete a category, ensuring it belongs to the user's workspace.
    Note: Consider the implications if tasks are linked (ON DELETE behavior in SQL).
    """
    category = db.query(category_model.Category).filter(
        category_model.Category.id == category_id,
        category_model.Category.workspace_id == current_user.workspace_id # Check workspace
    ).first()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    
    # Optional: Add checks here if you want to prevent deletion of categories in use,
    # depending on your ON DELETE strategy in the database.
    
    db.delete(category)
    db.commit()
    return category
