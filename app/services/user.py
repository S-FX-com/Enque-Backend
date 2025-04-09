from sqlalchemy.orm import Session
from fastapi import HTTPException, Request
from sqlalchemy import and_

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


def create_user(db: Session, user_data: UserCreate) -> User:
    db_user = User(**user_data.dict())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_users(db: Session, request: Request, skip: int, limit: int) -> list[User]:
    query = db.query(User)

    filter_conditions = []
    for key, value in request.query_params.items():
        if key.startswith("filter[") and key.endswith("]"):
            field_name = key[7:-1]
            if hasattr(User, field_name):
                column = getattr(User, field_name)

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


def get_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def update_user(db: Session, user_id: int, user_data: UserUpdate) -> User:
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)

    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, user_id: int) -> None:
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(db_user)
    db.commit()

def get_or_create_user(
    db: Session,
    email: str,
    name: str,
    workspace_id: int
):
    user = db.query(User).filter(
        User.email == email,
        User.workspace_id == workspace_id
    ).first()

    if user:
        return user

    new_user = User(email=email, name=name, workspace_id=workspace_id)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user