from typing import Any, List, Optional 
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func 
from sqlalchemy.exc import IntegrityError  # Añadimos la importación para el manejo del error

from app.api.dependencies import get_current_active_user, get_current_active_admin, get_current_workspace
from app.database.session import get_db
import secrets 
from datetime import datetime, timedelta 
from typing import Dict 
from typing import Dict 
from app.models.agent import Agent
from app.models.team import Team, TeamMember
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.microsoft import MailboxConnection, MicrosoftToken # Import MailboxConnection and MicrosoftToken
from app.schemas.agent import Agent as AgentSchema, AgentCreate, AgentUpdate, AgentInviteCreate, AgentAcceptInvitation
from pydantic import BaseModel
from app.schemas.team import Team as TeamSchema
from app.schemas.token import Token 
from app.core.security import get_password_hash, create_access_token 
from app.utils.logger import logger
from app.core.config import settings 
from app.services.email_service import send_agent_invitation_email
from app.services.microsoft_service import MicrosoftGraphService 

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
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
) -> Any:
    """
    Update an agent. Users can update their own profiles, admins can update any profile.
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

    # Check permissions: users can only update their own profile, admins can update any
    if current_user.role != "admin" and current_user.id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this agent profile",
        )

    update_data = agent_in.dict(exclude_unset=True)

    # If user is not admin and trying to update someone else's profile (already caught above)
    # or trying to change sensitive fields, restrict it
    if current_user.role != "admin" and current_user.id == agent_id:
        # Non-admin users can only update certain fields on their own profile
        restricted_fields = ["role", "is_active", "workspace_id"]
        for field in restricted_fields:
            if field in update_data:
                # For role specifically, allow if it's the same as current role (no change)
                if field == "role" and update_data[field] == agent.role:
                    continue
                # Otherwise, remove the restricted field
                del update_data[field]

    # Hash password if it's being updated
    if "password" in update_data and update_data["password"]:
        update_data["password"] = get_password_hash(update_data["password"])
    elif "password" in update_data:
         del update_data["password"]

    # Apply updates
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
    if agent_invite_in.workspace_id != current_workspace.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace ID in request does not match current admin's workspace."
        )
    
    # Primero verificamos si el agente ya existe en este workspace
    existing_agent_in_workspace = db.query(Agent).filter(
        Agent.email == agent_invite_in.email,
        Agent.workspace_id == agent_invite_in.workspace_id
    ).first()
    
    if existing_agent_in_workspace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent with email {agent_invite_in.email} already exists in this workspace.",
        )

    # Luego verificamos si el agente existe en cualquier otro workspace
    existing_agent = db.query(Agent).filter(
        Agent.email == agent_invite_in.email
    ).first()

    invitation_token = secrets.token_urlsafe(32)
    token_expires_at = datetime.utcnow() + timedelta(hours=settings.AGENT_INVITATION_TOKEN_EXPIRE_HOURS)
    
    # Si el agente ya existe en otro workspace, creamos uno nuevo solo para este workspace
    # pero mantenemos la referencia al mismo email
    if existing_agent:
        logger.info(f"Agent with email {agent_invite_in.email} already exists in another workspace. Creating a new record for current workspace.")
        
    # Creamos el nuevo agente para este workspace
    new_agent_data = AgentCreate(
        name=agent_invite_in.name,
        email=agent_invite_in.email,
        role=agent_invite_in.role,
        workspace_id=agent_invite_in.workspace_id,
        job_title=agent_invite_in.job_title,
        is_active=False, 
        password=None, 
        invitation_token=invitation_token,
        invitation_token_expires_at=token_expires_at,
    )
    
    # Crear agente con campos explícitos para evitar problemas de compatibilidad
    db_agent = Agent(
        name=new_agent_data.name,
        email=new_agent_data.email,
        role=new_agent_data.role,
        auth_method=new_agent_data.auth_method,
        workspace_id=new_agent_data.workspace_id,
        job_title=new_agent_data.job_title,
        is_active=new_agent_data.is_active,
        password=new_agent_data.password,
        invitation_token=new_agent_data.invitation_token,
        invitation_token_expires_at=new_agent_data.invitation_token_expires_at,
    ) 

    try:
        db.add(db_agent)
        db.commit()
        db.refresh(db_agent)
    except IntegrityError as e:
        db.rollback()
        logger.error(f"IntegrityError while inviting agent {agent_invite_in.email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Database error: {str(e)}. The agent may already exist in this workspace."
        )
    
    invitation_link = f"https://{current_workspace.subdomain}.enque.cc/accept-invitation?token={invitation_token}"

    admin_mailbox_connection = db.query(MailboxConnection).filter(
        MailboxConnection.created_by_agent_id == current_user.id,
        MailboxConnection.workspace_id == current_workspace.id,
        MailboxConnection.is_active == True
    ).first()

    if not admin_mailbox_connection:
        logger.info(f"Admin {current_user.email} has no active mailbox. Looking for any active mailbox in workspace {current_workspace.id}.")
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
    ms_token = db.query(MicrosoftToken).filter(
        MicrosoftToken.mailbox_connection_id == admin_mailbox_connection.id
    ).order_by(MicrosoftToken.created_at.desc()).first()

    if not ms_token:
        logger.error(f"No Microsoft token found for mailbox {admin_mailbox_connection.email} (ID: {admin_mailbox_connection.id}).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No token found for the connected mailbox {admin_mailbox_connection.email}. Please re-authenticate."
        )
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

    email_sent = await send_agent_invitation_email(
        db=db,
        to_email=db_agent.email,
        agent_name=db_agent.name,
        invitation_link=invitation_link,
        sender_mailbox_email=admin_mailbox_connection.email,
        user_access_token=ms_token.access_token,
        workspace_name=current_workspace.subdomain
    )

    if not email_sent:
        logger.error(f"Failed to send invitation email to {db_agent.email} from {admin_mailbox_connection.email} for agent ID {db_agent.id}. Agent created but invitation not sent.")
    
    logger.info(f"Agent {db_agent.name} ({db_agent.email}) invited to workspace {current_workspace.subdomain} by {current_user.email}. Invitation sent from {admin_mailbox_connection.email}. Token: {invitation_token}")
    
    # The AgentSchema by default might try to hide invitation_token.
    # If you need to return it (e.g., for testing), ensure the schema allows it or use a different one.
    return db_agent


@router.post("/{agent_id}/resend-invite", response_model=AgentSchema)
async def resend_agent_invitation(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_admin), # Ensure only admins can resend invitations
    current_workspace: Workspace = Depends(get_current_workspace),
):
    """
    Resend an invitation to an inactive agent.
    Generates a new invitation token and sends a new invitation email.
    """
    # Find the agent to resend invitation to
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.workspace_id == current_workspace.id
    ).first()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found in this workspace",
        )
    
    # Check if agent is already active
    if agent.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent is already active. Cannot resend invitation to active agents.",
        )
    
    # Generate new invitation token
    invitation_token = secrets.token_urlsafe(32)
    token_expires_at = datetime.utcnow() + timedelta(hours=settings.AGENT_INVITATION_TOKEN_EXPIRE_HOURS)
    
    # Update agent with new token
    agent.invitation_token = invitation_token
    agent.invitation_token_expires_at = token_expires_at
    
    db.add(agent)
    db.commit()
    db.refresh(agent)
    
    # Create invitation link
    invitation_link = f"https://{current_workspace.subdomain}.enque.cc/accept-invitation?token={invitation_token}"
    
    # Find an active mailbox to send from (same logic as original invite)
    admin_mailbox_connection = db.query(MailboxConnection).filter(
        MailboxConnection.created_by_agent_id == current_user.id,
        MailboxConnection.workspace_id == current_workspace.id,
        MailboxConnection.is_active == True
    ).first()

    if not admin_mailbox_connection:
        logger.info(f"Admin {current_user.email} has no active mailbox. Looking for any active mailbox in workspace {current_workspace.id}.")
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
    
    # Get Microsoft token for the mailbox
    ms_token = db.query(MicrosoftToken).filter(
        MicrosoftToken.mailbox_connection_id == admin_mailbox_connection.id
    ).order_by(MicrosoftToken.created_at.desc()).first()

    if not ms_token:
        logger.error(f"No Microsoft token found for mailbox {admin_mailbox_connection.email} (ID: {admin_mailbox_connection.id}).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No token found for the connected mailbox {admin_mailbox_connection.email}. Please re-authenticate."
        )
    
    # Refresh token if expired
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

    # Send the invitation email
    email_sent = await send_agent_invitation_email(
        db=db,
        to_email=agent.email,
        agent_name=agent.name,
        invitation_link=invitation_link,
        sender_mailbox_email=admin_mailbox_connection.email,
        user_access_token=ms_token.access_token,
        workspace_name=current_workspace.subdomain
    )

    if not email_sent:
        logger.error(f"Failed to resend invitation email to {agent.email} from {admin_mailbox_connection.email} for agent ID {agent.id}.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send invitation email. Please try again later."
        )
    
    logger.info(f"Invitation resent to agent {agent.name} ({agent.email}) in workspace {current_workspace.subdomain} by {current_user.email}. Sent from {admin_mailbox_connection.email}. New token: {invitation_token}")
    
    return agent


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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation token has expired.",
        )
    agent.password = get_password_hash(invitation_data.password)
    agent.is_active = True
    agent.invitation_token = None 
    agent.invitation_token_expires_at = None 
    
    db.add(agent)
    db.commit()
    db.refresh(agent)

    logger.info(f"Agent {agent.email} (ID: {agent.id}) accepted invitation and activated account.")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {
        "role": agent.role,
        "workspace_id": str(agent.workspace_id),
        "name": agent.name, 
        "email": agent.email 
    }
    access_token = create_access_token(
        subject=str(agent.id),  
        extra_data=token_payload, 
        expires_delta=access_token_expires
    )
    
    # Get workspace information to include subdomain in response
    workspace = db.query(Workspace).filter(Workspace.id == agent.workspace_id).first()
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "workspace_subdomain": workspace.subdomain if workspace else None
    }


class TeamsNotificationSettings(BaseModel):
    enabled: bool

@router.put("/{agent_id}/teams-notifications", response_model=AgentSchema)
async def update_teams_notification_settings(
    agent_id: int,
    settings: TeamsNotificationSettings,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    current_workspace: Workspace = Depends(get_current_workspace),
):
    """
    Update an agent's Microsoft Teams notification preference.
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

    # Permissions check: Admin can update anyone, users can only update themselves.
    if current_user.role != "admin" and current_user.id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this setting.",
        )

    agent.teams_notifications_enabled = settings.enabled
    db.commit()
    db.refresh(agent)
    logger.info(f"Agent {agent.id} Teams notification settings updated to: {settings.enabled} by user {current_user.id}")
    return agent


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
                            Task.status != 'Closed' 
        ).scalar() or 0
        
        team_schema = TeamSchema.from_orm(team_model)
        team_schema.ticket_count = ticket_count
        teams_with_counts.append(team_schema)
        
    return teams_with_counts
