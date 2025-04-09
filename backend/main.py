#!/usr/bin/env python3
import os
import sys
import uvicorn
import pymysql
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add the project path to make imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the application from the app module
from app.main import app
from app.core.security import get_password_hash

def check_database_connection():
    """Check database connection"""
    # Load environment variables
    if os.path.exists(".env.railway"):
        load_dotenv(".env.railway")
    else:
        load_dotenv()
    
    # Database configuration
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "obiedesk")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    
    # Database URL
    DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
    
    print(f"Checking database connection: {MYSQL_HOST}:{MYSQL_PORT}")
    
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
        print(f"Successfully connected to database at {MYSQL_HOST}:{MYSQL_PORT}.")
        return DATABASE_URL
    except Exception as e:
        print(f"Error connecting to database at {MYSQL_HOST}:{MYSQL_PORT} - {e}")
        
        # Try alternative host if external fails (for Railway)
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
                print(f"Successfully connected using internal host: {alt_host}:{alt_port}")
                
                # Update URL for future use
                DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{alt_host}:{alt_port}/{MYSQL_DATABASE}"
                
                return DATABASE_URL
            except Exception as e2:
                print(f"Error with internal host: {e2}")
                print("Could not establish connection with any host. Check your configuration.")
                return None
        return None

def create_admin_user(database_url):
    """Create default admin user"""
    # Import models
    from app.models.agent import Agent
    
    # Create engine and session
    engine = create_engine(database_url)
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

if __name__ == "__main__":
    print("Starting ObieDesk...")
    
    # Check database connection and perform initial setup
    database_url = check_database_connection()
    if database_url:
        create_admin_user(database_url)
    
    # Use port provided by environment (PORT) or 8000 by default
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting server on port {port}...")
    
    # Start the application
    uvicorn.run("app.main:app", host="0.0.0.0", port=port) 