from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# Get database URL from environment variables
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

try:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        print("Successful connection to the database")
except Exception as e:
    print(f"Error connecting to the database: {e}")
    engine = None

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None
Base = declarative_base()

# Dependency to get DB session
def get_db():
    if SessionLocal is None:
        raise RuntimeError("Database engine is not initialized")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
