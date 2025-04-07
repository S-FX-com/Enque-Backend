import os
import pymysql
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.security import get_password_hash

# Load environment variables
load_dotenv(".env.railway")

# Database configuration
MYSQL_HOST = os.getenv("MYSQL_HOST", "hopper.proxy.rlwy.net")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "railway")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "40531"))

# URL of the database
DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

def create_admin_user():
    """Create default admin user"""
    # Import models
    from app.models.agent import Agent
    
    # Create motor and session
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Check if admin already exists
        admin = db.query(Agent).filter(Agent.email == "admin@example.com").first()
        if admin:
            print("Admin user already exists.")
            return True
        
        # Create admin user
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

def check_database_connection():
    """Verify database connection"""
    global MYSQL_HOST, MYSQL_PORT, DATABASE_URL
    
    try:
        # Direct MySQL connection to verify
        connection = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            port=MYSQL_PORT,
            database=MYSQL_DATABASE,
            connect_timeout=10
        )
        connection.close()
        print(f"Database connection established successfully with {MYSQL_HOST}:{MYSQL_PORT}.")
        return True
    except Exception as e:
        print(f"Error connecting to database with {MYSQL_HOST}:{MYSQL_PORT} - {e}")
        
        # Try alternative host if external fails
        if MYSQL_HOST == "hopper.proxy.rlwy.net":
            print("Trying with internal host...")
            try:
                alt_host = "mysql.railway.internal"
                alt_port = 3306
                connection = pymysql.connect(
                    host=alt_host,
                    user=MYSQL_USER,
                    password=MYSQL_PASSWORD,
                    port=alt_port,
                    database=MYSQL_DATABASE,
                    connect_timeout=10
                )
                connection.close()
                print(f"Connection established using internal host: {alt_host}:{alt_port}")
                
                # Update variables for future uses
                MYSQL_HOST = alt_host
                MYSQL_PORT = alt_port
                DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
                
                return True
            except Exception as e2:
                print(f"Error with internal host: {e2}")
                print("Could not establish connection with any host. Check configuration.")
                return False
        return False

if __name__ == "__main__":
    print("Setting up Railway environment...")
    print(f"Using configuration: {MYSQL_HOST}:{MYSQL_PORT} - DB:{MYSQL_DATABASE}")
    
    # Check connection
    if check_database_connection():
        # Create admin user
        create_admin_user()
            
    print("Setup completed.") 