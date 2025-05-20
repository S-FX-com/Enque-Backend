# Import all models here to ensure they are registered with SQLAlchemy
from app.models.workspace import Workspace
from app.models.agent import Agent  
from app.models.team import Team, TeamMember
from app.models.company import Company
from app.models.user import User, UnassignedUser
from app.models.task import Task
from app.models.comment import Comment
from app.models.activity import Activity
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig 
from .ticket_attachment import TicketAttachment 
from app.models.global_signature import GlobalSignature 