from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.task import Task
from app.models.agent import Agent
from app.models.team import Team, TeamMember
from app.schemas.task import TaskWithDetails
from typing import Any, List, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

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


@router.post("/emergency/reset-email-sync")
async def emergency_reset_email_sync(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user)
) -> Any:
    """🚑 EMERGENCY: Reset email sync circuit breaker"""
    
    # Solo admin/manager puede usar este endpoint
    if current_user.role not in ['Admin', 'Manager']:
        raise HTTPException(
            status_code=403,
            detail="Only Admin/Manager can reset email sync circuit breaker"
        )
    
    try:
        from app.services.email_sync_task import reset_email_sync_circuit_breaker, email_sync_circuit_breaker
        from app.database.session import get_pool_status, log_pool_status
        
        # Log pool status antes del reset
        logger.info("🚑 EMERGENCY RESET requested by user: " + current_user.email)
        log_pool_status()
        
        # Información del circuit breaker antes del reset
        cb_status_before = {
            "failure_count": email_sync_circuit_breaker.failure_count,
            "last_failure_time": email_sync_circuit_breaker.last_failure_time,
            "can_execute": email_sync_circuit_breaker.can_execute()
        }
        
        # Resetear circuit breaker
        result = reset_email_sync_circuit_breaker()
        
        return {
            "success": True,
            "message": "Email sync circuit breaker reset successfully",
            "reset_by": current_user.email,
            "circuit_breaker_before": cb_status_before,
            "db_pool_status": get_pool_status(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error resetting email sync circuit breaker: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error resetting circuit breaker: {str(e)}"
        )


@router.get("/timezone-info")
async def get_timezone_info():
    """Get current timezone information for debugging"""
    import pytz
    from datetime import datetime, timezone
    
    # UTC time
    now_utc = datetime.now(timezone.utc)
    
    # Eastern time
    eastern = pytz.timezone('US/Eastern')
    now_et = datetime.now(eastern)
    
    return {
        "utc_time": now_utc.isoformat(),
        "eastern_time": now_et.isoformat(),
        "timezone_name": now_et.tzname(),
        "utc_offset": str(now_et.utcoffset())
    }

 