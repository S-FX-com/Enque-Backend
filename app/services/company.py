from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException, Request

from app.models.company import Company
from app.schemas.company import CompanyCreate, CompanyUpdate


def create_company(db: Session, company_data: CompanyCreate) -> Company:
    db_company = Company(**company_data.dict())
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company


def get_companies(db: Session, request: Request, skip: int, limit: int) -> list[Company]:
    query = db.query(Company)

    filter_conditions = []
    for key, value in request.query_params.items():
        if key.startswith("filter[") and key.endswith("]"):
            field_name = key[7:-1]
            if hasattr(Company, field_name):
                column = getattr(Company, field_name)

                if column.property.columns[0].type.python_type == int:
                    value = int(value)
                elif column.property.columns[0].type.python_type == float:
                    value = float(value)
                elif column.property.columns[0].type.python_type == bool:
                    value = value.lower() in ["true", "1", "yes"]

                if isinstance(value, str):
                    filter_conditions.append(column.ilike(f"%{value}%"))
                else:
                    filter_conditions.append(column == value)

    if filter_conditions:
        query = query.filter(and_(*filter_conditions))

    return query.offset(skip).limit(limit).all()


def get_company(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def update_company(db: Session, company_id: int, company_data: CompanyUpdate) -> Company:
    db_company = db.query(Company).filter(Company.id == company_id).first()
    if db_company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    update_data = company_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_company, key, value)

    db.commit()
    db.refresh(db_company)
    return db_company


def delete_company(db: Session, company_id: int) -> None:
    db_company = db.query(Company).filter(Company.id == company_id).first()
    if db_company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    db.delete(db_company)
    db.commit()
