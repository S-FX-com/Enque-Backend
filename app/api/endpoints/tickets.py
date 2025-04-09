from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from typing import List

from app.models.agent import Agent
from app.schemas.ticket import TicketCreate, TicketResponse, TicketUpdate
from app.core.security import get_current_active_user
from app.libs.database import get_db
from app.services.ticket import (
    create_ticket,
    get_tickets,
    get_ticket,
    update_ticket,
    delete_ticket,
)

router = APIRouter()


@router.post("/", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket_route(
    ticket: TicketCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return create_ticket(db, ticket)


@router.get("/", response_model=List[TicketResponse])
def get_tickets_route(
    request: Request,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_tickets(db, request, skip, limit)


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket_route(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return get_ticket(db, ticket_id)


@router.put("/{ticket_id}", response_model=TicketResponse)
def update_ticket_route(
    ticket_id: int,
    ticket: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    return update_ticket(db, ticket_id, ticket)


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket_route(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
):
    delete_ticket(db, ticket_id)
    return None
