from app.libs.database import engine
from app.models.agent import Base as AgentBase
from app.models.workspace import Base as WorkspaceBase
from app.models.ticket import Base as TicketBase
from app.models.team import Base as TeamBase
from app.models.comment import Base as CommentBase
from app.models.activity import Base as ActivityBase
from app.models.user import Base as UserBase
from app.models.company import Base as CompanyBase
from app.models.microsoft import Base as MicrosoftBase

def init_db():
    WorkspaceBase.metadata.create_all(bind=engine)
    AgentBase.metadata.create_all(bind=engine)
    TicketBase.metadata.create_all(bind=engine)
    TeamBase.metadata.create_all(bind=engine)
    CommentBase.metadata.create_all(bind=engine)
    ActivityBase.metadata.create_all(bind=engine)
    UserBase.metadata.create_all(bind=engine)
    CompanyBase.metadata.create_all(bind=engine)
    MicrosoftBase.metadata.create_all(bind=engine)
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db()

