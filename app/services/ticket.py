from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException, Request

from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate


def create_ticket(db: Session, ticket_data: TicketCreate) -> Ticket:
    db_ticket = Ticket(**ticket_data.dict())
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def get_tickets(db: Session, request: Request, skip: int, limit: int) -> list[Ticket]:
    query = db.query(Ticket)

    filter_conditions = []
    for key, value in request.query_params.items():
        if key.startswith("filter[") and key.endswith("]"):
            field_name = key[7:-1]
            if hasattr(Ticket, field_name):
                column = getattr(Ticket, field_name)

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


def get_ticket(db: Session, ticket_id: int) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def update_ticket(db: Session, ticket_id: int, ticket_data: TicketUpdate) -> Ticket:
    db_ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    update_data = ticket_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_ticket, key, value)

    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def delete_ticket(db: Session, ticket_id: int) -> None:
    db_ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    db.delete(db_ticket)
    db.commit()
