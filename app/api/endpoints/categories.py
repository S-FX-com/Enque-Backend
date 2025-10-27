from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from app.api import dependencies
from app.schemas import category as category_schema
from app.models import category as category_model
from app.models.agent import Agent

router = APIRouter()

@router.post("/", response_model=category_schema.Category, status_code=status.HTTP_201_CREATED)
async def create_category(
    *,
    db: AsyncSession = Depends(dependencies.get_db),
    category_in: category_schema.CategoryCreate,
    current_user: Agent = Depends(dependencies.get_current_active_user)
):
    """
    Create a new category within the user's workspace.
    """
    existing_category_stmt = select(category_model.Category).filter(category_model.Category.name == category_in.name)
    existing_category = (await db.execute(existing_category_stmt)).scalars().first()
    if existing_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A category with this name already exists in this workspace.",
        )
        
    if category_in.workspace_id != current_user.workspace_id:
         raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN,
             detail="Cannot create category in another workspace.",
         )
         
    db_category = category_model.Category(
        name=category_in.name, 
        workspace_id=current_user.workspace_id
    )
    db.add(db_category)
    await db.commit()
    await db.refresh(db_category)
    return db_category

@router.get("/", response_model=List[category_schema.Category])
async def read_categories(
    db: AsyncSession = Depends(dependencies.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(dependencies.get_current_active_user)
):
    """
    Retrieve categories for the current user's workspace.
    """
    categories_stmt = select(category_model.Category).filter(
        category_model.Category.workspace_id == current_user.workspace_id
    ).offset(skip).limit(limit)
    categories = (await db.execute(categories_stmt)).scalars().all()
    return categories

@router.get("/{category_id}", response_model=category_schema.Category)
async def read_category(
    *,
    db: AsyncSession = Depends(dependencies.get_db),
    category_id: int,
    current_user: Agent = Depends(dependencies.get_current_active_user)
):
    """
    Get category by ID, ensuring it belongs to the user's workspace.
    """
    category_stmt = select(category_model.Category).filter(
        category_model.Category.id == category_id,
        category_model.Category.workspace_id == current_user.workspace_id
    )
    category = (await db.execute(category_stmt)).scalars().first()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category

@router.put("/{category_id}", response_model=category_schema.Category)
async def update_category(
    *,
    db: AsyncSession = Depends(dependencies.get_db),
    category_id: int,
    category_in: category_schema.CategoryUpdate,
    current_user: Agent = Depends(dependencies.get_current_active_user)
):
    """
    Update a category, ensuring it belongs to the user's workspace.
    """
    category_stmt = select(category_model.Category).filter(
        category_model.Category.id == category_id,
        category_model.Category.workspace_id == current_user.workspace_id
    )
    category = (await db.execute(category_stmt)).scalars().first()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    if category_in.name and category_in.name != category.name:
        existing_category_stmt = select(category_model.Category).filter(
            category_model.Category.name == category_in.name,
            category_model.Category.workspace_id == current_user.workspace_id
        )
        existing_category = (await db.execute(existing_category_stmt)).scalars().first()
        if existing_category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A category with this name already exists in this workspace.",
            )

    update_data = category_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)
    
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category

@router.delete("/{category_id}", response_model=category_schema.Category)
async def delete_category(
    *,
    db: AsyncSession = Depends(dependencies.get_db),
    category_id: int,
    current_user: Agent = Depends(dependencies.get_current_active_user)
):
    """
    Delete a category, ensuring it belongs to the user's workspace.
    """
    category_stmt = select(category_model.Category).filter(
        category_model.Category.id == category_id,
        category_model.Category.workspace_id == current_user.workspace_id
    )
    category = (await db.execute(category_stmt)).scalars().first()
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    
    await db.delete(category)
    await db.commit()
    return category
