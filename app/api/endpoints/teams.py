from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, and_, select

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
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve teams for the current user's workspace with ticket counts.
    """
    teams_with_counts = []
    result = await db.execute(
        select(Team).filter(
            Team.workspace_id == current_user.workspace_id
        ).order_by(Team.name).offset(skip).limit(limit)
    )
    teams_query = result.scalars().all()
    
    is_admin_or_manager = current_user.role in ['admin', 'manager']

    for team in teams_query:
        total_ticket_count = 0
        if is_admin_or_manager:
            subquery = select(mailbox_team_assignments.c.mailbox_connection_id).filter(
                mailbox_team_assignments.c.team_id == team.id
            )
            count_query = select(func.count(Task.id.distinct())).filter(
                or_(
                    Task.team_id == team.id,
                    and_(
                        Task.team_id.is_(None),
                        Task.mailbox_connection_id.isnot(None),
                        Task.mailbox_connection_id.in_(subquery)
                    )
                ),
                Task.status != 'Closed',
                Task.is_deleted == False,
                Task.workspace_id == current_user.workspace_id
            )
            count_result = await db.execute(count_query)
            total_ticket_count = count_result.scalar() or 0
        else:
            direct_count_result = await db.execute(
                select(func.count(Task.id)).filter(
                    Task.team_id == team.id,
                    Task.status != 'Closed',
                    Task.is_deleted == False,
                    Task.workspace_id == current_user.workspace_id
                )
            )
            direct_ticket_count = direct_count_result.scalar() or 0
            
            member_result = await db.execute(
                select(TeamMember).filter(
                    TeamMember.team_id == team.id,
                    TeamMember.agent_id == current_user.id
                )
            )
            is_team_member = member_result.scalars().first() is not None
            
            mailbox_ticket_count = 0
            if is_team_member:
                mailbox_count_result = await db.execute(
                    select(func.count(Task.id)).join(
                        MailboxConnection, Task.mailbox_connection_id == MailboxConnection.id
                    ).join(
                        mailbox_team_assignments, MailboxConnection.id == mailbox_team_assignments.c.mailbox_connection_id
                    ).filter(
                        mailbox_team_assignments.c.team_id == team.id,
                        Task.team_id.is_(None),
                        Task.status != 'Closed',
                        Task.is_deleted == False,
                        Task.workspace_id == current_user.workspace_id
                    )
                )
                mailbox_ticket_count = mailbox_count_result.scalar() or 0
            
            total_ticket_count = direct_ticket_count + mailbox_ticket_count
        
        team_data = TeamSchema.from_orm(team)
        team_data.ticket_count = total_ticket_count
        teams_with_counts.append(team_data)
        
    return teams_with_counts


@router.post("/", response_model=TeamSchema)
async def create_team(
    team_in: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager),
) -> Any:
    """
    Create a new team
    """
    team = Team(**team_in.dict())
    db.add(team)
    await db.commit()
    await db.refresh(team)
    
    return team


@router.get("/{team_id}", response_model=TeamSchema)
async def read_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Get team by ID
    """
    result = await db.execute(select(Team).filter(Team.id == team_id))
    team = result.scalars().first()
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
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager), 
) -> Any:
    """
    Update a team
    """
    result = await db.execute(select(Team).filter(Team.id == team_id))
    team = result.scalars().first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    update_data = team_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(team, field, value)
    
    await db.commit()
    await db.refresh(team)
    
    return team


@router.delete("/{team_id}", response_model=TeamSchema)
async def delete_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager), 
) -> Any:
    """
    Delete a team
    """
    result = await db.execute(select(Team).filter(Team.id == team_id))
    team = result.scalars().first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    await db.delete(team)
    await db.commit()
    
    return team

@router.get("/{team_id}/members", response_model=List[TeamMemberSchema])
async def read_team_members(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve all members of a team
    """
    result = await db.execute(select(Team).filter(Team.id == team_id))
    team = result.scalars().first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )
    
    result = await db.execute(select(TeamMember).filter(TeamMember.team_id == team_id))
    members = result.scalars().all()
    return members


@router.post("/{team_id}/members", response_model=TeamMemberSchema)
async def add_team_member(
    team_id: int,
    member_in: TeamMemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager), 
) -> Any:
    """
    Add a member to a team
    """
    team_result = await db.execute(select(Team).filter(Team.id == team_id))
    if not team_result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    agent_result = await db.execute(select(Agent).filter(Agent.id == member_in.agent_id))
    if not agent_result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    existing_member_result = await db.execute(
        select(TeamMember).filter(
            TeamMember.team_id == team_id,
            TeamMember.agent_id == member_in.agent_id
        )
    )
    if existing_member_result.scalars().first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent is already a member of this team")

    member = TeamMember(team_id=team_id, agent_id=member_in.agent_id)
    db.add(member)
    await db.commit()
    await db.refresh(member)
    
    return member


@router.delete("/{team_id}/members/{agent_id}", response_model=TeamMemberSchema)
async def remove_team_member(
    team_id: int,
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin_or_manager), 
) -> Any:
    """
    Remove a member from a team
    """
    result = await db.execute(
        select(TeamMember).filter(
            TeamMember.team_id == team_id,
            TeamMember.agent_id == agent_id
        )
    )
    member = result.scalars().first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team member not found",
        )
    
    await db.delete(member)
    await db.commit()
    
    return member

@router.get("/agent/{agent_id}", response_model=List[TeamSchema])
async def read_agent_teams(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    Retrieve teams for a specific agent with ticket counts.
    """
    is_admin_or_manager = current_user.role in ['admin', 'manager']
    
    if is_admin_or_manager:
        query = select(Team).filter(Team.workspace_id == current_user.workspace_id).order_by(Team.name)
    else:
        query = select(Team).join(
            TeamMember, Team.id == TeamMember.team_id
        ).filter(
            TeamMember.agent_id == agent_id,
            Team.workspace_id == current_user.workspace_id
        ).order_by(Team.name)
    
    result = await db.execute(query)
    agent_teams_query = result.scalars().all()
    
    teams_with_counts = []
    
    for team in agent_teams_query:
        subquery = select(mailbox_team_assignments.c.mailbox_connection_id).filter(
            mailbox_team_assignments.c.team_id == team.id
        )
        count_query = select(func.count(Task.id.distinct())).filter(
            or_(
                Task.team_id == team.id,
                and_(
                    Task.team_id.is_(None),
                    Task.mailbox_connection_id.isnot(None),
                    Task.mailbox_connection_id.in_(subquery)
                )
            ),
            Task.status != 'Closed',
            Task.is_deleted == False,
            Task.workspace_id == current_user.workspace_id
        )
        count_result = await db.execute(count_query)
        total_ticket_count = count_result.scalar() or 0
        
        team_data = TeamSchema.from_orm(team)
        team_data.ticket_count = total_ticket_count
        teams_with_counts.append(team_data)
        
    return teams_with_counts
