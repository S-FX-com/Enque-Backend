from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user, get_current_active_admin, get_current_workspace
from app.database.session import get_db
from app.models.agent import Agent
from app.models.company import Company
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.company import Company as CompanySchema, CompanyCreate, CompanyUpdate
from app.schemas.user import User as UserSchema

router = APIRouter()


@router.get("/", response_model=List[CompanySchema])
async def read_companies(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve all companies
    """
    companies = db.query(Company).filter(Company.workspace_id == current_workspace.id).order_by(Company.name).offset(skip).limit(limit).all()
    return companies


@router.post("/", response_model=CompanySchema)
async def create_company(
    company_in: CompanyCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Create a new company
    """
    # Create company with current workspace
    company_data = company_in.dict()
    company_data["workspace_id"] = current_workspace.id
    company = Company(**company_data)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    return company


@router.get("/{company_id}", response_model=CompanySchema)
async def read_company(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get company by ID
    """
    company = db.query(Company).filter(
        Company.id == company_id,
        Company.workspace_id == current_workspace.id
    ).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )
    return company


@router.put("/{company_id}", response_model=CompanySchema)
async def update_company(
    company_id: int,
    company_in: CompanyUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Update a company
    """
    company = db.query(Company).filter(
        Company.id == company_id,
        Company.workspace_id == current_workspace.id
    ).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )
    
    # Actualizar atributos de la empresa
    update_data = company_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)
    
    db.commit()
    db.refresh(company)
    
    return company


@router.delete("/{company_id}", response_model=CompanySchema)
async def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Delete a company (admin only)
    """
    company = db.query(Company).filter(
        Company.id == company_id,
        Company.workspace_id == current_workspace.id
    ).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )
    
    # Verificar si hay usuarios asociados
    users_count = db.query(User).filter(
        User.company_id == company_id,
        User.workspace_id == current_workspace.id
    ).count()
    if users_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete company because it has {users_count} associated users",
        )
    
    db.delete(company)
    db.commit()
    
    return company


@router.get("/{company_id}/users", response_model=List[UserSchema])
async def read_company_users(
    company_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve all users for a specific company
    """
    # Verificar que la empresa existe
    company = db.query(Company).filter(
        Company.id == company_id,
        Company.workspace_id == current_workspace.id
    ).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )
    
    users = db.query(User).filter(
        User.company_id == company_id,
        User.workspace_id == current_workspace.id
    ).order_by(User.name).offset(skip).limit(limit).all()
    return users 