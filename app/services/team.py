from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException, Request

from app.models.team import Team
from app.schemas.team import TeamCreate, TeamUpdate


def create_team(db: Session, team_data: TeamCreate) -> Team:
    db_team = Team(**team_data.dict())
    db.add(db_team)
    db.commit()
    db.refresh(db_team)
    return db_team


def get_teams(db: Session, request: Request, skip: int, limit: int) -> list[Team]:
    query = db.query(Team)

    filter_conditions = []
    for key, value in request.query_params.items():
        if key.startswith("filter[") and key.endswith("]"):
            field_name = key[7:-1]
            if hasattr(Team, field_name):
                column = getattr(Team, field_name)

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


def get_team(db: Session, team_id: int) -> Team:
    team = db.query(Team).filter(Team.id == team_id).first()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def update_team(db: Session, team_id: int, team_data: TeamUpdate) -> Team:
    db_team = db.query(Team).filter(Team.id == team_id).first()
    if db_team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    update_data = team_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_team, key, value)

    db.commit()
    db.refresh(db_team)
    return db_team


def delete_team(db: Session, team_id: int) -> None:
    db_team = db.query(Team).filter(Team.id == team_id).first()
    if db_team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    db.delete(db_team)
    db.commit()
