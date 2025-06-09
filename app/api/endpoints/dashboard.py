from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.task import Task
from app.models.agent import Agent
from app.models.team import Team, TeamMember
from app.schemas.task import TaskWithDetails
from typing import Any, List, Dict

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    user_id = current_user.id
    workspace_id = current_user.workspace_id

    user_info = db.query(Agent).filter(
        Agent.id == user_id,
        Agent.workspace_id == workspace_id
    ).first()

    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    assigned_tickets = db.query(Task).options(
        joinedload(Task.user),
        joinedload(Task.category)
    ).filter(
        Task.assignee_id == user_id,
        Task.workspace_id == workspace_id,
        Task.is_deleted == False
    ).order_by(Task.created_at.desc()).limit(50).all()

    user_teams = db.query(Team).join(TeamMember).filter(
        TeamMember.agent_id == user_id,
        Team.workspace_id == workspace_id
    ).all()

    team_stats = []
    for team in user_teams:
        team_tasks = db.query(Task).filter(
            Task.team_id == team.id,
            Task.workspace_id == workspace_id,
            Task.is_deleted == False
        ).all()

        tickets_open = len([t for t in team_tasks if t.status in ['Open', 'Unread']])
        tickets_with_user = len([t for t in team_tasks if t.user_id == user_id])
        tickets_assigned = len(team_tasks)

        team_stats.append({
            "id": team.id,
            "name": team.name,
            "description": team.description,
            "ticketsOpen": tickets_open,
            "ticketsWithUser": tickets_with_user,
            "ticketsAssigned": tickets_assigned,
        })

    tickets_assigned_count = len(assigned_tickets)
    tickets_completed_count = len([t for t in assigned_tickets if t.status == 'Closed'])
    teams_count = len(user_teams)

    recent_tickets = []
    for ticket in assigned_tickets[:10]:
        recent_tickets.append({
            "id": ticket.id,
            "title": ticket.title,
            "status": ticket.status,
            "priority": ticket.priority,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "user": {
                "id": ticket.user.id if ticket.user else None,
                "name": ticket.user.name if ticket.user else None,
                "email": ticket.user.email if ticket.user else None,
            } if ticket.user else None
        })

    return {
        "user": {
            "id": user_info.id,
            "name": user_info.name,
            "email": user_info.email,
            "role": user_info.role,
        },
        "stats": {
            "ticketsAssignedCount": tickets_assigned_count,
            "ticketsCompletedCount": tickets_completed_count,
            "teamsCount": teams_count,
        },
        "recentTickets": recent_tickets,
        "teamsStats": team_stats,
    } 