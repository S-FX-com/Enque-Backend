from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_ # Import func for count and or_ for OR conditions

# Import the new dependency
from app.api.dependencies import get_current_active_user, get_current_active_admin_or_manager
from app.database.session import get_db
from app.models.team import Team, TeamMember
from app.models.agent import Agent
from app.models.task import Task # Import Task model
from app.models.microsoft import MailboxConnection, mailbox_team_assignments # Import mailbox models
from app.schemas.team import Team as TeamSchema, TeamCreate, TeamUpdate
from app.schemas.team import TeamMember as TeamMemberSchema, TeamMemberCreate

router = APIRouter()


@router.get("/", response_model=List[TeamSchema])
async def read_teams(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve teams for the current user's workspace with ticket counts.
    Includes tickets directly assigned to the team AND tickets from mailboxes assigned to the team.
    Admin/Manager users can see ALL teams with ALL tickets. Regular agents see teams based on membership.
    """
    teams_with_counts = []
    teams_query = db.query(Team).filter(
        Team.workspace_id == current_user.workspace_id
    ).order_by(Team.name).offset(skip).limit(limit).all()
    
    # Check if user is admin or manager
    is_admin_or_manager = current_user.role in ['admin', 'manager']

    for team in teams_query:
        if is_admin_or_manager:
            # Admin/Manager: Count ALL tickets for this team without team membership restrictions
            total_ticket_count = db.query(func.count(Task.id.distinct())).filter(
                or_(
                    # Direct team assignment
                    Task.team_id == team.id,
                    # Mailbox team assignment (only for tickets without direct team assignment)
                    and_(
                        Task.team_id.is_(None),  # Only count mailbox tickets that don't have team_id
                        Task.mailbox_connection_id.isnot(None),
                        Task.mailbox_connection_id.in_(
                            db.query(mailbox_team_assignments.c.mailbox_connection_id).filter(
                                mailbox_team_assignments.c.team_id == team.id
                            )
                        )
                    )
                ),
                Task.status.notin_(['Closed', 'Resolved']),
                Task.is_deleted == False,
                Task.workspace_id == current_user.workspace_id  # Ensure workspace filtering
            ).scalar() or 0
            
        else:
            # Regular agent: Count tickets directly assigned to team + mailbox tickets if user is team member
            direct_ticket_count = db.query(func.count(Task.id)).filter(
                Task.team_id == team.id,
                Task.status.notin_(['Closed', 'Resolved']),
                Task.is_deleted == False,
                Task.workspace_id == current_user.workspace_id
            ).scalar() or 0
            
            # Count mailbox tickets only if current user is a member of this team
            is_team_member = db.query(TeamMember).filter(
                TeamMember.team_id == team.id,
                TeamMember.agent_id == current_user.id
            ).first() is not None
            
            if is_team_member:
                mailbox_ticket_count = db.query(func.count(Task.id)).join(
                    MailboxConnection, Task.mailbox_connection_id == MailboxConnection.id
                ).join(
                    mailbox_team_assignments, MailboxConnection.id == mailbox_team_assignments.c.mailbox_connection_id
                ).filter(
                    mailbox_team_assignments.c.team_id == team.id,
                    Task.team_id.is_(None),  # Only count mailbox tickets without direct team assignment
                    Task.status.notin_(['Closed', 'Resolved']),
                    Task.is_deleted == False,
                    Task.workspace_id == current_user.workspace_id
                ).scalar() or 0
            else:
                mailbox_ticket_count = 0
            
            total_ticket_count = direct_ticket_count + mailbox_ticket_count
        
        team_data = TeamSchema.from_orm(team)
        team_data.ticket_count = total_ticket_count
        teams_with_counts.append(team_data)
        
    return teams_with_counts


@router.post("/", response_model=TeamSchema)
async def create_team(
    team_in: TeamCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager),
) -> Any:
    """
    Create a new team
    """
    team = Team(**team_in.dict())
    db.add(team)
    db.commit()
    db.refresh(team)
    
    return team


@router.get("/{team_id}", response_model=TeamSchema)
async def read_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get team by ID
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    return team


@router.put("/{team_id}", response_model=TeamSchema)
async def update_team(
    team_id: int,
    team_in: TeamUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager), 
) -> Any:
    """
    Update a team
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    update_data = team_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(team, field, value)
    
    db.commit()
    db.refresh(team)
    
    return team


@router.delete("/{team_id}", response_model=TeamSchema)
async def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager), 
) -> Any:
    """
    Delete a team
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    db.delete(team)
    db.commit()
    
    return team

@router.get("/{team_id}/members", response_model=List[TeamMemberSchema])
async def read_team_members(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all members of a team
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
    return members


@router.post("/{team_id}/members", response_model=TeamMemberSchema)
async def add_team_member(
    team_id: int,
    member_in: TeamMemberCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager), 
) -> Any:
    """
    Add a member to a team
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    agent = db.query(Agent).filter(Agent.id == member_in.agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    existing_member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.agent_id == member_in.agent_id
    ).first()
    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent is already a member of this team",
        )
    member = TeamMember(team_id=team_id, agent_id=member_in.agent_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    
    return member


@router.delete("/{team_id}/members/{agent_id}", response_model=TeamMemberSchema)
async def remove_team_member(
    team_id: int,
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager), 
) -> Any:
    """
    Remove a member from a team
    """
    member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.agent_id == agent_id
    ).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team member not found",
        )
    
    db.delete(member)
    db.commit()
    
    return member

@router.get("/agent/{agent_id}", response_model=List[TeamSchema])
async def read_agent_teams(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve teams for a specific agent with ticket counts.
    Admin/Manager users get ALL teams with ALL tickets. Regular agents get only their teams.
    """
    # Check if user is admin or manager
    is_admin_or_manager = current_user.role in ['admin', 'manager']
    
    if is_admin_or_manager:
        # Admin/Manager: Get ALL teams in workspace (same as /teams/ endpoint)
        agent_teams_query = db.query(Team).filter(
            Team.workspace_id == current_user.workspace_id
        ).order_by(Team.name).all()
    else:
        # Regular agent: Get only teams the agent belongs to
        agent_teams_query = db.query(Team).join(
            TeamMember, Team.id == TeamMember.team_id
        ).filter(
            TeamMember.agent_id == agent_id,
            Team.workspace_id == current_user.workspace_id
        ).order_by(Team.name).all()
    
    teams_with_counts = []
    
    for team in agent_teams_query:
        if is_admin_or_manager:
            # Admin/Manager: Count ALL tickets for this team without restrictions
            total_ticket_count = db.query(func.count(Task.id.distinct())).filter(
                or_(
                    # Direct team assignment
                    Task.team_id == team.id,
                    # Mailbox team assignment (only for tickets without direct team assignment)
                    and_(
                        Task.team_id.is_(None),  # Only count mailbox tickets that don't have team_id
                        Task.mailbox_connection_id.isnot(None),
                        Task.mailbox_connection_id.in_(
                            db.query(mailbox_team_assignments.c.mailbox_connection_id).filter(
                                mailbox_team_assignments.c.team_id == team.id
                            )
                        )
                    )
                ),
                Task.status.notin_(['Closed', 'Resolved']),
                Task.is_deleted == False,
                Task.workspace_id == current_user.workspace_id
            ).scalar() or 0
        else:
            # Regular agent: Use existing logic with team membership filtering
            total_ticket_count = db.query(func.count(Task.id.distinct())).filter(
                or_(
                    # Direct team assignment
                    Task.team_id == team.id,
                    # Mailbox team assignment (only for tickets without direct team assignment)
                    and_(
                        Task.team_id.is_(None),  # Only count mailbox tickets that don't have team_id
                        Task.mailbox_connection_id.isnot(None),
                        Task.mailbox_connection_id.in_(
                            db.query(mailbox_team_assignments.c.mailbox_connection_id).filter(
                                mailbox_team_assignments.c.team_id == team.id
                            )
                        )
                    )
                ),
                Task.status.notin_(['Closed', 'Resolved']),
                Task.is_deleted == False,
                Task.workspace_id == current_user.workspace_id
            ).scalar() or 0
        
        team_data = TeamSchema.from_orm(team)
        team_data.ticket_count = total_ticket_count
        teams_with_counts.append(team_data)
        
    return teams_with_counts
