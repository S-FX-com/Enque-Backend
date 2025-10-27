from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, delete

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
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve all companies
    """
    stmt = select(Company).filter(Company.workspace_id == current_workspace.id).order_by(Company.name).offset(skip).limit(limit)
    result = await db.execute(stmt)
    companies = result.scalars().all()
    return companies


@router.post("/", response_model=CompanySchema)
async def create_company(
    company_in: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Create a new company and automatically assign existing unassigned users
    with matching email domains.
    """
    company_data = company_in.dict()
    company_data["workspace_id"] = current_workspace.id
    company = Company(**company_data)
    db.add(company)
    await db.commit()
    await db.refresh(company)
    logger.info(f"Company '{company.name}' (ID: {company.id}) created successfully.")

    new_domain = company.email_domain
    if new_domain:
        normalized_domain = new_domain.lower()
        logger.info(f"New company has domain '{normalized_domain}'. Checking for existing unassigned users to assign.")
        
        users_to_check_stmt = select(User).filter(
            User.workspace_id == current_workspace.id,
            User.company_id == None
        )
        users_to_check = (await db.execute(users_to_check_stmt)).scalars().all()

        assigned_user_emails = []
        for user in users_to_check:
            if user.email:
                user_domain = user.email.split('@')[-1].lower() if '@' in user.email else None
                if user_domain == normalized_domain:
                    user.company_id = company.id
                    db.add(user)
                    assigned_user_emails.append(user.email)
                    logger.info(f"Assigning existing user {user.email} (ID: {user.id}) to new company {company.name}")

        if assigned_user_emails:
            logger.info(f"Removing {len(assigned_user_emails)} users from unassigned list: {assigned_user_emails}")
            delete_stmt = delete(UnassignedUser).where(
                UnassignedUser.email.in_(assigned_user_emails),
                UnassignedUser.workspace_id == current_workspace.id
            )
            await db.execute(delete_stmt)
            await db.commit()
            logger.info(f"Successfully assigned {len(assigned_user_emails)} existing users to new company {company.name}.")
        else:
            logger.info(f"No existing unassigned users found with domain '{normalized_domain}'.")
    
    return company


@router.get("/{company_id}", response_model=CompanySchema)
async def read_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get company by ID
    """
    stmt = select(Company).filter(
        Company.id == company_id,
        Company.workspace_id == current_workspace.id
    )
    company = (await db.execute(stmt)).scalars().first()
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
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Update a company
    """
    stmt = select(Company).filter(
        Company.id == company_id,
        Company.workspace_id == current_workspace.id
    )
    company = (await db.execute(stmt)).scalars().first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )
    
    update_data = company_in.dict(exclude_unset=True)
    original_email_domain = company.email_domain
    
    for field, value in update_data.items():
        setattr(company, field, value)
    
    await db.commit()
    await db.refresh(company)

    new_email_domain = company.email_domain
    if new_email_domain and new_email_domain != original_email_domain:
        normalized_new_domain = new_email_domain.lower()
        
        users_stmt = select(User).filter(
            User.workspace_id == current_workspace.id,
            User.company_id == None
        )
        users_to_potentially_assign = (await db.execute(users_stmt)).scalars().all()

        assigned_users_emails = []
        for user_to_check in users_to_potentially_assign:
            if user_to_check.email:
                user_email_domain = user_to_check.email.split('@')[-1].lower() if '@' in user_to_check.email else None
                if user_email_domain == normalized_new_domain:
                    user_to_check.company_id = company.id
                    db.add(user_to_check)
                    assigned_users_emails.append(user_to_check.email)

        if assigned_users_emails:
            delete_stmt = delete(UnassignedUser).where(
                UnassignedUser.email.in_(assigned_users_emails),
                UnassignedUser.workspace_id == current_workspace.id
            )
            await db.execute(delete_stmt)
            await db.commit()

    return company


@router.delete("/{company_id}", response_model=CompanySchema)
async def delete_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Delete a company (admin only)
    """
    stmt = select(Company).filter(
        Company.id == company_id,
        Company.workspace_id == current_workspace.id
    )
    company = (await db.execute(stmt)).scalars().first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )
    
    users_count_stmt = select(func.count(User.id)).filter(
        User.company_id == company_id,
        User.workspace_id == current_workspace.id
    )
    users_count = (await db.execute(users_count_stmt)).scalar_one()
    if users_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete company because it has {users_count} associated users",
        )
    
    await db.delete(company)
    await db.commit()
    
    return company


@router.get("/{company_id}/users", response_model=List[UserSchema])
async def read_company_users(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve all users for a specific company
    """
    company_stmt = select(Company).filter(
        Company.id == company_id,
        Company.workspace_id == current_workspace.id
    )
    company = (await db.execute(company_stmt)).scalars().first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )
    
    users_stmt = select(User).filter(
        User.company_id == company_id,
        User.workspace_id == current_workspace.id
    ).order_by(User.name).offset(skip).limit(limit)
    users = (await db.execute(users_stmt)).scalars().all()
    return users
