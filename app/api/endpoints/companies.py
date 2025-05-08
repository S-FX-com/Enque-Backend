from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.dependencies import get_current_active_user, get_current_active_admin, get_current_workspace
from app.database.session import get_db
from app.models.agent import Agent
from app.models.company import Company
from app.models.user import User, UnassignedUser
from app.models.workspace import Workspace
from app.schemas.company import Company as CompanySchema, CompanyCreate, CompanyUpdate
from app.schemas.user import User as UserSchema
from app.utils.logger import logger

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
    Create a new company and automatically assign existing unassigned users
    with matching email domains.
    """
    # Create company with current workspace
    company_data = company_in.dict()
    company_data["workspace_id"] = current_workspace.id
    company = Company(**company_data)
    db.add(company)
    db.commit()
    db.refresh(company)
    logger.info(f"Company '{company.name}' (ID: {company.id}) created successfully.")

    # --- Automatic assignment of EXISTING unassigned users ---
    new_domain = company.email_domain
    if new_domain:
        normalized_domain = new_domain.lower()
        logger.info(f"New company has domain '{normalized_domain}'. Checking for existing unassigned users to assign.")
        
        # Find users in the same workspace without a company
        users_to_check = db.query(User).filter(
            User.workspace_id == current_workspace.id,
            User.company_id == None
        ).all()

        assigned_user_ids = []
        assigned_user_emails = []
        for user in users_to_check:
            if user.email:
                user_domain = user.email.split('@')[-1].lower() if '@' in user.email else None
                if user_domain == normalized_domain:
                    user.company_id = company.id
                    db.add(user)
                    assigned_user_ids.append(user.id)
                    assigned_user_emails.append(user.email)
                    logger.info(f"Assigning existing user {user.email} (ID: {user.id}) to new company {company.name}")

        if assigned_user_ids:
            # Remove these users from the UnassignedUser table
            logger.info(f"Removing {len(assigned_user_emails)} users from unassigned list: {assigned_user_emails}")
            db.query(UnassignedUser).filter(
                UnassignedUser.email.in_(assigned_user_emails),
                UnassignedUser.workspace_id == current_workspace.id
            ).delete(synchronize_session=False)
            
            db.commit() # Commit user company_id updates and UnassignedUser deletions
            logger.info(f"Successfully assigned {len(assigned_user_ids)} existing users to new company {company.name}.")
        else:
            logger.info(f"No existing unassigned users found with domain '{normalized_domain}'.")
    # --- End Automatic Assignment ---
    
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
    
    update_data = company_in.dict(exclude_unset=True)
    
    # Guardar el email_domain original para detectar si cambió
    original_email_domain = company.email_domain
    
    # Actualizar atributos de la empresa
    for field, value in update_data.items():
        setattr(company, field, value)
    
    db.commit()
    db.refresh(company)

    # Lógica de asignación automática de usuarios si email_domain cambió y es válido
    new_email_domain = company.email_domain # Ya está en minúsculas si así se guardó, o se normaliza aquí
    if new_email_domain and new_email_domain != original_email_domain:
        normalized_new_domain = new_email_domain.lower()
        print(f"Company {company.name} (ID: {company.id}) email_domain changed to {normalized_new_domain}. Attempting to assign users.")
        
        # Buscar usuarios sin compañía asignada en el mismo workspace
        users_to_potentially_assign = db.query(User).filter(
            User.workspace_id == current_workspace.id,
            User.company_id == None
        ).all()

        assigned_count = 0
        for user_to_check in users_to_potentially_assign:
            if user_to_check.email:
                user_email_domain = user_to_check.email.split('@')[-1].lower() if '@' in user_to_check.email else None
                if user_email_domain == normalized_new_domain:
                    user_to_check.company_id = company.id
                    db.add(user_to_check) # Marcar para actualizar
                    assigned_count += 1
                    print(f"Assigning user {user_to_check.email} (ID: {user_to_check.id}) to company {company.name}")

        if assigned_count > 0:
            db.commit()
            print(f"Successfully assigned {assigned_count} users to company {company.name} based on new email domain.")
            # No es necesario un db.refresh() para los usuarios aquí, ya que la respuesta es la compañía.
            # El frontend debería re-evaluar las listas de usuarios a través de la invalidación de queries.

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