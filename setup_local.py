import os
import pymysql
from dotenv import load_dotenv
from app.database.session import engine
from app.models.agent import Base as AgentBase
from app.models.team import Base as TeamBase
from app.models.task import Base as TaskBase
from app.models.company import Base as CompanyBase
from app.models.user import Base as UserBase
from app.models.comment import Base as CommentBase
from app.models.activity import Base as ActivityBase
from app.core.security import get_password_hash

# Cargar variables de entorno
load_dotenv()

def create_database():
    """Create the database if it doesn't exist"""
    try:
        # Connect to MySQL without specifying database
        connection = pymysql.connect(
            host=os.getenv("MYSQL_HOST"),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # Create database if it doesn't exist
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {os.getenv('MYSQL_DATABASE')}")
            print(f"Base de datos '{os.getenv('MYSQL_DATABASE')}' creada o ya existente.")
            
            # Seleccionar la base de datos
            cursor.execute(f"USE {os.getenv('MYSQL_DATABASE')}")
            
        connection.commit()
        connection.close()
        return True
    except Exception as e:
        print(f"Error creating database: {e}")
        return False

def init_db():
    """Create all tables in the database"""
    try:
        # Crear todas las tablas
        AgentBase.metadata.create_all(bind=engine)
        TeamBase.metadata.create_all(bind=engine)
        TaskBase.metadata.create_all(bind=engine)
        CompanyBase.metadata.create_all(bind=engine)
        UserBase.metadata.create_all(bind=engine)
        CommentBase.metadata.create_all(bind=engine)
        ActivityBase.metadata.create_all(bind=engine)
        print("Tablas de la base de datos creadas correctamente!")
        return True
    except Exception as e:
        print(f"Error creating tables: {e}")
        return False

def create_admin_user():
    """Create default admin user"""
    from sqlalchemy.orm import sessionmaker
    from app.models.agent import Agent
    
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Verificar si ya existe un admin
        admin = db.query(Agent).filter(Agent.email == "admin@example.com").first()
        if admin:
            print("Admin user already exists.")
            return True
        
        # Crear usuario administrador
        admin = Agent(
            name="Admin",
            email="admin@example.com",
            password=get_password_hash("admin123"),
            role="admin"
        )
        db.add(admin)
        db.commit()
        print("Admin user created successfully.")
        return True
    except Exception as e:
        db.rollback()
        print(f"Error creating admin user: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("Setting up local environment...")
    
    # Crear base de datos
    if create_database():
        # Inicializar tablas
        if init_db():
            # Crear usuario administrador
            create_admin_user()
            
    print("Setup completed.") 