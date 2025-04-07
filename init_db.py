from app.database.session import engine
from app.models.agent import Base as AgentBase
from app.models.team import Base as TeamBase
from app.models.task import Base as TaskBase
from app.models.company import Base as CompanyBase
from app.models.user import Base as UserBase
from app.models.comment import Base as CommentBase
from app.models.activity import Base as ActivityBase

def init_db():
    """
    Initialize database tables based on SQLAlchemy models
    """
    AgentBase.metadata.create_all(bind=engine)
    TeamBase.metadata.create_all(bind=engine)
    TaskBase.metadata.create_all(bind=engine)
    CompanyBase.metadata.create_all(bind=engine)
    UserBase.metadata.create_all(bind=engine)
    CommentBase.metadata.create_all(bind=engine)
    ActivityBase.metadata.create_all(bind=engine)
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db() 