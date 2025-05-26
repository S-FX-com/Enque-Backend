# Import base classes
from app.database.base_class import Base

# Import all models to ensure they are registered with SQLAlchemy
# These imports must be done after Base is defined in base_class.py

# Import all models here - they will be detected by SQLAlchemy
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.team import Team, TeamMember
from app.models.company import Company 
from app.models.user import User, UnassignedUser
from app.models.task import Task
from app.models.comment import Comment
from app.models.activity import Activity
from app.models.microsoft import MicrosoftIntegration, MicrosoftToken, EmailTicketMapping, EmailSyncConfig
from app.models.canned_reply import CannedReply
from app.models.global_signature import GlobalSignature
from app.models.notification import NotificationTemplate, NotificationSetting
from app.models.automation import Automation
from app.models.workflow import Workflow

# Define all models in their own files and import them in app/models/__init__.py
# DO NOT import models here to avoid circular imports 