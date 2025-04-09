from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.activity import Activity
from app.schemas.activity import ActivityCreate, ActivityUpdate


def create_activity(db: Session, activity_data: ActivityCreate) -> Activity:
    db_activity = Activity(**activity_data.dict())
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity


def get_activities(
    db: Session,
    filters: Optional[Dict[str, Any]] = None,
    skip: int = 0,
    limit: int = 100
) -> List[Activity]:
    query = db.query(Activity)

    if filters:
        filter_conditions = []
        for field_name, value in filters.items():
            if hasattr(Activity, field_name):
                column = getattr(Activity, field_name)
                col_type = column.property.columns[0].type.python_type

                try:
                    if col_type == int:
                        value = int(value)
                    elif col_type == float:
                        value = float(value)
                    elif col_type == bool:
                        value = str(value).lower() in ["true", "1", "yes"]
                except Exception:
                    continue

                if isinstance(value, str):
                    filter_conditions.append(column.ilike(f"%{value}%"))
                else:
                    filter_conditions.append(column == value)

        if filter_conditions:
            query = query.filter(and_(*filter_conditions))

    return query.offset(skip).limit(limit).all()


def get_activity_by_id(db: Session, activity_id: int) -> Optional[Activity]:
    return db.query(Activity).filter(Activity.id == activity_id).first()


def update_activity(
    db: Session,
    activity_id: int,
    update_data: ActivityUpdate
) -> Optional[Activity]:
    db_activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if db_activity is None:
        return None

    for key, value in update_data.dict(exclude_unset=True).items():
        setattr(db_activity, key, value)

    db.commit()
    db.refresh(db_activity)
    return db_activity


def delete_activity(db: Session, activity_id: int) -> bool:
    db_activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if db_activity is None:
        return False

    db.delete(db_activity)
    db.commit()
    return True
