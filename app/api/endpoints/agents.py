from typing import Any, List, Optional 
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func 

from app.api.dependencies import get_current_active_user, get_current_active_admin, get_current_workspace
from app.database.session import get_db
import secrets # For generating secure tokens
from datetime import datetime, timedelta # For token expiration
from typing import Dict # For returning a simple message or token
from typing import Dict # For returning a simple message or token
from app.models.agent import Agent
from app.models.team import Team, TeamMember
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.microsoft import MailboxConnection, MicrosoftToken # Import MailboxConnection and MicrosoftToken
from app.schemas.agent import Agent as AgentSchema, AgentCreate, AgentUpdate, AgentInviteCreate, AgentAcceptInvitation 
from app.schemas.team import Team as TeamSchema
from app.schemas.token import Token 
from app.core.security import get_password_hash, create_access_token 
from app.utils.logger import logger
from app.core.config import settings 
from app.services.email_service import send_agent_invitation_email
from app.services.microsoft_service import MicrosoftGraphService # To refresh token if needed

router = APIRouter()

@router.get("/", response_model=List[AgentSchema])
async def read_agents(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0), 
    limit: int = Query(100, ge=1, le=200), 
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve agents for the current workspace with pagination.
    """
    logger.info(f"Fetching agents for workspace {current_workspace.id} with skip={skip}, limit={limit}")
    agents = db.query(Agent).filter(
        Agent.workspace_id == current_workspace.id
    ).order_by(Agent.name).offset(skip).limit(limit).all()
    logger.info(f"Retrieved {len(agents)} agents.")
    return agents


@router.post("/", response_model=AgentSchema)
async def create_agent(
    agent_in: AgentCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Create a new agent (admin only)
    """
    agent = db.query(Agent).filter(
        Agent.email == agent_in.email,
        Agent.workspace_id == current_workspace.id
    ).first()
    if agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in this workspace",
        )

    agent = Agent(
        name=agent_in.name,
        email=agent_in.email,
        password=get_password_hash(agent_in.password),
        role=agent_in.role,
        workspace_id=current_workspace.id,
        is_active=True,
        job_title=agent_in.job_title,
        phone_number=agent_in.phone_number,
        email_signature=agent_in.email_signature
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    return agent


@router.get("/{agent_id}", response_model=AgentSchema)
async def read_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Get agent by ID
    """
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return agent


@router.put("/{agent_id}", response_model=AgentSchema)
async def update_agent(
    agent_id: int,
    agent_in: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Update an agent (admin only)
    """
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    update_data = agent_in.dict(exclude_unset=True)

    if "password" in update_data and update_data["password"]:
        update_data["password"] = get_password_hash(update_data["password"])
    elif "password" in update_data:
         del update_data["password"]


    for field, value in update_data.items():
        setattr(agent, field, value)

    db.commit()
    db.refresh(agent)

    return agent


@router.delete("/{agent_id}", response_model=AgentSchema)
async def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Delete an agent (admin only)
    """
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    if agent.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    db.delete(agent)
    db.commit()

    return agent


@router.post("/invite", response_model=AgentSchema) # Or a different response model like a status message
async def invite_agent(
    agent_invite_in: AgentInviteCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin), # Ensure only admins can invite
    current_workspace: Workspace = Depends(get_current_workspace), # Get current workspace from dependency
):
    """
    Invite a new agent to the current workspace.
    Creates an inactive agent record and sends an invitation email using any active mailbox in the workspace.
    """
    # Validate that agent_invite_in.workspace_id matches current_workspace.id
    if agent_invite_in.workspace_id != current_workspace.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace ID in request does not match current admin's workspace."
        )

    # Check if agent already exists in the target workspace
    existing_agent = db.query(Agent).filter(
        Agent.email == agent_invite_in.email,
        Agent.workspace_id == agent_invite_in.workspace_id
    ).first()
    if existing_agent:
        # If agent exists and is active, it's an error or a re-invite scenario (handle as needed)
        # If agent exists but is inactive (e.g. pending invitation), could resend invitation or error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent with email {agent_invite_in.email} already exists in this workspace.",
        )

    # Generate invitation token
    invitation_token = secrets.token_urlsafe(32)
    token_expires_at = datetime.utcnow() + timedelta(hours=settings.AGENT_INVITATION_TOKEN_EXPIRE_HOURS)

    # Create the agent with inactive status and invitation token
    # Use AgentCreate schema, but override/set specific fields for invitation
    new_agent_data = AgentCreate(
        name=agent_invite_in.name,
        email=agent_invite_in.email,
        role=agent_invite_in.role,
        workspace_id=agent_invite_in.workspace_id,
        is_active=False, # Agent is inactive until they accept the invitation
        password=None, # Password will be set by the agent upon accepting invitation
        invitation_token=invitation_token,
        invitation_token_expires_at=token_expires_at,
        # job_title, phone_number, email_signature can be None by default from AgentBase
    )
    
    db_agent = Agent(**new_agent_data.dict()) # Create model instance

    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)

    # Construct invitation link
    invitation_link = f"{settings.FRONTEND_URL}/accept-invitation?token={invitation_token}"

    # Find any active mailbox connection in the workspace, prioritizing mailboxes connected by admins
    # First try to find the current admin's mailbox
    admin_mailbox_connection = db.query(MailboxConnection).filter(
        MailboxConnection.created_by_agent_id == current_user.id,
        MailboxConnection.workspace_id == current_workspace.id,
        MailboxConnection.is_active == True
    ).first()
    
    # If current admin doesn't have a mailbox, try to find any active mailbox in the workspace
    if not admin_mailbox_connection:
        logger.info(f"Admin {current_user.email} has no active mailbox. Looking for any active mailbox in workspace {current_workspace.id}.")
        # Find any mailbox connected by an admin in this workspace
        admin_agents = db.query(Agent.id).filter(
            Agent.workspace_id == current_workspace.id,
            Agent.role == "admin",
            Agent.is_active == True
        ).all()
        admin_ids = [admin.id for admin in admin_agents]
        
        admin_mailbox_connection = db.query(MailboxConnection).filter(
            MailboxConnection.created_by_agent_id.in_(admin_ids),
            MailboxConnection.workspace_id == current_workspace.id,
            MailboxConnection.is_active == True
        ).first()
        
        # If still no mailbox found, try any active mailbox in the workspace
        if not admin_mailbox_connection:
            admin_mailbox_connection = db.query(MailboxConnection).filter(
                MailboxConnection.workspace_id == current_workspace.id,
                MailboxConnection.is_active == True
            ).first()

    if not admin_mailbox_connection:
        logger.error(f"No active mailbox connection found in workspace {current_workspace.id} to send invitation from.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active mailbox found in this workspace. Please connect a mailbox to send invitations."
        )

    # Get a valid token for this mailbox connection
    ms_token = db.query(MicrosoftToken).filter(
        MicrosoftToken.mailbox_connection_id == admin_mailbox_connection.id
    ).order_by(MicrosoftToken.created_at.desc()).first()

    if not ms_token:
        logger.error(f"No Microsoft token found for mailbox {admin_mailbox_connection.email} (ID: {admin_mailbox_connection.id}).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No token found for the connected mailbox {admin_mailbox_connection.email}. Please re-authenticate."
        )

    # Check if token is expired and try to refresh if necessary
    graph_service = MicrosoftGraphService(db=db)
    if ms_token.expires_at < datetime.utcnow():
        try:
            logger.info(f"Token for {admin_mailbox_connection.email} expired, attempting refresh.")
            ms_token = graph_service.refresh_token(ms_token)
        except HTTPException as e:
            logger.error(f"Failed to refresh token for {admin_mailbox_connection.email}: {e.detail}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not refresh token for mailbox {admin_mailbox_connection.email}. Please re-authenticate. Error: {e.detail}"
            )
    
    # Send invitation email using the mailbox and token
    email_sent = await send_agent_invitation_email(
        db=db,
        to_email=db_agent.email,
        agent_name=db_agent.name,
        invitation_link=invitation_link,
        sender_mailbox_email=admin_mailbox_connection.email,
        user_access_token=ms_token.access_token
    )

    if not email_sent:
        logger.error(f"Failed to send invitation email to {db_agent.email} from {admin_mailbox_connection.email} for agent ID {db_agent.id}. Agent created but invitation not sent.")
        # Depending on how critical email sending is, you might raise an exception here
        # For now, we proceed, but the admin should be notified if possible through the response or UI.
        # Consider adding a specific error message or status to the response if email fails.
        # For example, you could modify the response model or add a message field.
        # For simplicity, we'll still return the agent, but with a severe log.
        # raise HTTPException(status_code=500, detail="Agent created, but failed to send invitation email.")
    
    logger.info(f"Agent {db_agent.name} ({db_agent.email}) invited to workspace {current_workspace.name} by {current_user.email}. Invitation sent from {admin_mailbox_connection.email}. Token: {invitation_token}")
    
    # The AgentSchema by default might try to hide invitation_token.
    # If you need to return it (e.g., for testing), ensure the schema allows it or use a different one.
    return db_agent


@router.post("/accept-invitation", response_model=Token) # Responds with a JWT token upon successful activation
async def accept_agent_invitation(
    invitation_data: AgentAcceptInvitation,
    db: Session = Depends(get_db),
):
    """
    Allows an agent to accept an invitation, set their password, and activate their account.
    """
    agent = db.query(Agent).filter(Agent.invitation_token == invitation_data.token).first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation token.",
        )
    
    if agent.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already active.",
        )

    if agent.invitation_token_expires_at and agent.invitation_token_expires_at < datetime.utcnow():
        # Optionally, clean up the expired token here or have a separate cleanup job
        # agent.invitation_token = None 
        # agent.invitation_token_expires_at = None
        # db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation token has expired.",
        )

    # Activate agent and set password
    agent.password = get_password_hash(invitation_data.password)
    agent.is_active = True
    agent.invitation_token = None # Invalidate the token
    agent.invitation_token_expires_at = None # Clear expiration
    
    db.add(agent)
    db.commit()
    db.refresh(agent)

    logger.info(f"Agent {agent.email} (ID: {agent.id}) accepted invitation and activated account.")

    # Generate JWT token for the newly activated agent to log them in
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {
        "role": agent.role,
        "workspace_id": str(agent.workspace_id),
        "name": agent.name, # Add agent's name
        "email": agent.email # Add agent's email
    }
    access_token = create_access_token(
        subject=str(agent.id),  # Pass agent.id as the subject
        extra_data=token_payload, # Pass additional claims here
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/{agent_id}/teams", response_model=List[TeamSchema])
async def read_agent_teams(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user), 
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Retrieve teams that a specific agent belongs to within the current workspace.
    """
    target_agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    if not target_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found in this workspace",
        )
    teams_query = db.query(Team).join(TeamMember).filter(
        TeamMember.agent_id == agent_id,
        Team.workspace_id == current_workspace.id
    ).all()

    teams_with_counts = []
    for team_model in teams_query:

        ticket_count = db.query(func.count(Task.id)).filter(
            Task.team_id == team_model.id,
            Task.status.notin_(['Closed', 'Resolved']) 
        ).scalar() or 0
        
        team_schema = TeamSchema.from_orm(team_model)
        team_schema.ticket_count = ticket_count
        teams_with_counts.append(team_schema)
        
    return teams_with_counts
