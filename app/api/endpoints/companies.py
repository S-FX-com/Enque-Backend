from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from typing import List

from app.models.agent import Agent
from app.schemas.company import CompanyCreate, CompanyResponse, CompanyUpdate
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.services.company import (
    create_company,
    get_companies,
    get_company,
    update_company,
    delete_company,
)

router = APIRouter()


@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company_route(
    company: CompanyCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return create_company(db, company)


@router.get("/", response_model=List[CompanyResponse])
def get_companies_route(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_companies(db, request, skip, limit)


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company_route(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_company(db, company_id)


@router.put("/{company_id}", response_model=CompanyResponse)
def update_company_route(
    company_id: int,
    company: CompanyUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return update_company(db, company_id, company)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company_route(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    delete_company(db, company_id)
    return None
