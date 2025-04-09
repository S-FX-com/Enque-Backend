#!/usr/bin/env python3
"""
Script for migrating the database to support the Workspace model and multi-tenant architecture.
This script will:
1. Create the workspaces table
2. Add workspace_id to all existing tables
3. Create a default workspace and associate all existing records with it
4. Update the status enum in the tickets table

Run this script directly to perform the migration:
python backend/migrate_to_workspace.py
"""

import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, ForeignKey, DateTime, func, inspect
from sqlalchemy.exc import SQLAlchemyError

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
if os.path.exists("backend/.env.railway"):
    load_dotenv("backend/.env.railway")
else:
    load_dotenv("backend/.env")

# Database configuration
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "obiedesk")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))

# URL of the database
DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

# Create engine
engine = create_engine(DATABASE_URL)
metadata = MetaData()
metadata.bind = engine
inspector = inspect(engine)

def execute_sql(sql, params=None):
    """Execute SQL with proper error handling"""
    try:
        with engine.connect() as conn:
            if params:
                result = conn.execute(text(sql), params)
            else:
                result = conn.execute(text(sql))
            conn.commit()
            return result
    except SQLAlchemyError as e:
        print(f"Error executing SQL: {e}")
        return None

def table_exists(table_name):
    """Check if a table exists"""
    return inspector.has_table(table_name)

def column_exists(table_name, column_name):
    """Check if a column exists in a table"""
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in columns

def create_workspaces_table():
    """Create workspaces table if it doesn't exist"""
    if not table_exists('workspaces'):
        print("Creating workspaces table...")
        sql = """
        CREATE TABLE workspaces (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            local_subdomain VARCHAR(255) NOT NULL UNIQUE,
            email_domain VARCHAR(255) NOT NULL,
            logo_url VARCHAR(1024),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """
        execute_sql(sql)
        print("Workspaces table created successfully.")
    else:
        print("Workspaces table already exists.")

def create_default_workspace():
    """Create a default workspace"""
    # Check if there are any workspaces
    result = execute_sql("SELECT COUNT(*) as count FROM workspaces")
    row = result.fetchone()
    if row[0] == 0:
        print("Creating default workspace...")
        sql = """
        INSERT INTO workspaces (name, local_subdomain, email_domain) 
        VALUES (:name, :subdomain, :email_domain)
        """
        params = {
            "name": "Default Workspace",
            "subdomain": "default",
            "email_domain": "obiedesk.com"
        }
        execute_sql(sql, params)
        print("Default workspace created successfully.")
    else:
        print("Default workspace already exists.")
    
    # Get the default workspace ID
    result = execute_sql("SELECT id FROM workspaces ORDER BY id LIMIT 1")
    row = result.fetchone()
    return row[0]

def add_workspace_id_to_table(table_name, default_workspace_id):
    """Add workspace_id column to a table and set default value"""
    if not column_exists(table_name, 'workspace_id'):
        print(f"Adding workspace_id to {table_name}...")
        
        # Add the column
        sql = f"""
        ALTER TABLE {table_name}
        ADD COLUMN workspace_id INT
        """
        execute_sql(sql)
        
        # Update existing records to use default workspace
        sql = f"""
        UPDATE {table_name}
        SET workspace_id = :workspace_id
        """
        execute_sql(sql, {"workspace_id": default_workspace_id})
        
        # Make the column NOT NULL
        sql = f"""
        ALTER TABLE {table_name}
        MODIFY COLUMN workspace_id INT NOT NULL
        """
        execute_sql(sql)
        
        # Add foreign key constraint
        sql = f"""
        ALTER TABLE {table_name}
        ADD CONSTRAINT fk_{table_name}_workspace
        FOREIGN KEY (workspace_id)
        REFERENCES workspaces(id)
        """
        execute_sql(sql)
        
        print(f"workspace_id added to {table_name} successfully.")
    else:
        print(f"workspace_id already exists in {table_name}.")

def update_status_enum():
    """Update the task_status enum to use the new values"""
    # Check if task_status enum exists
    result = execute_sql("""
    SELECT COUNT(*) as count 
    FROM information_schema.columns 
    WHERE table_schema = DATABASE() 
    AND table_name = 'tickets' 
    AND column_name = 'status'
    """)
    
    if result and result.fetchone()[0] > 0:
        print("Updating status enum...")
        
        # First rename the table from tasks to tickets if needed
        if table_exists('tasks') and not table_exists('tickets'):
            execute_sql("RENAME TABLE tasks TO tickets")
            print("Renamed tasks table to tickets")

        # Create a temporary status column with the new enum
        sql = """
        ALTER TABLE tickets
        ADD COLUMN new_status ENUM('Pending', 'In progress', 'Completed') NOT NULL DEFAULT 'Pending'
        """
        execute_sql(sql)
        
        # Map old status values to new ones
        sql = """
        UPDATE tickets
        SET new_status = CASE
            WHEN status = 'Unread' THEN 'Pending'
            WHEN status = 'Open' THEN 'In progress'
            WHEN status = 'Closed' THEN 'Completed'
            ELSE 'Pending' END
        """
        execute_sql(sql)
        
        # Drop the old status column
        sql = """
        ALTER TABLE tickets
        DROP COLUMN status
        """
        execute_sql(sql)
        
        # Rename the new column to status
        sql = """
        ALTER TABLE tickets
        CHANGE COLUMN new_status status ENUM('Pending', 'In progress', 'Completed') NOT NULL DEFAULT 'Pending'
        """
        execute_sql(sql)
        
        print("Status enum updated successfully.")
    else:
        print("Status column not found or already updated.")

def rename_columns():
    """Rename columns to match the new model structure"""
    if table_exists('tickets') and column_exists('tickets', 'user_id'):
        # Check if task_id and user_id columns exist in comments
        if table_exists('comments') and column_exists('comments', 'task_id'):
            print("Renaming task_id to ticket_id in comments...")
            sql = """
            ALTER TABLE comments
            CHANGE COLUMN task_id ticket_id INT NOT NULL
            """
            execute_sql(sql)
            print("Renamed task_id to ticket_id in comments.")
            
        # Check if user_id column exists in comments
        if table_exists('comments') and column_exists('comments', 'user_id'):
            print("Renaming user_id to agent_id in comments...")
            sql = """
            ALTER TABLE comments
            CHANGE COLUMN user_id agent_id INT NOT NULL
            """
            execute_sql(sql)
            print("Renamed user_id to agent_id in comments.")
            
        # Check if user_id column exists in activities
        if table_exists('activities') and column_exists('activities', 'user_id'):
            print("Renaming user_id to agent_id in activities...")
            sql = """
            ALTER TABLE activities
            CHANGE COLUMN user_id agent_id INT
            """
            execute_sql(sql)
            print("Renamed user_id to agent_id in activities.")
            
        # Check if task_id column exists in activities
        if table_exists('activities') and column_exists('activities', 'task_id'):
            print("Adding source_type and source_id to activities...")
            
            # Add source_type column
            if not column_exists('activities', 'source_type'):
                sql = """
                ALTER TABLE activities
                ADD COLUMN source_type ENUM('Workspace', 'Ticket', 'Team', 'Company', 'User') NOT NULL DEFAULT 'Ticket'
                """
                execute_sql(sql)
                
            # Add source_id column
            if not column_exists('activities', 'source_id'):
                sql = """
                ALTER TABLE activities
                ADD COLUMN source_id INT NOT NULL DEFAULT 0
                """
                execute_sql(sql)
                
                # Update existing records to use task_id as source_id
                sql = """
                UPDATE activities
                SET source_id = task_id, source_type = 'Ticket'
                WHERE task_id IS NOT NULL
                """
                execute_sql(sql)
                
                # Drop the task_id column
                sql = """
                ALTER TABLE activities
                DROP COLUMN task_id
                """
                execute_sql(sql)
                
            print("Added source_type and source_id to activities successfully.")
    else:
        print("Tables or columns don't exist, skipping rename operations.")

def add_missing_columns():
    """Add new columns that were added to the models"""
    # Add is_active to agents
    if table_exists('agents') and not column_exists('agents', 'is_active'):
        print("Adding is_active to agents...")
        sql = """
        ALTER TABLE agents
        ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE
        """
        execute_sql(sql)
        print("Added is_active to agents successfully.")
    
    # Add sent_to_id to tickets
    if table_exists('tickets') and not column_exists('tickets', 'sent_to_id'):
        print("Adding sent_to_id to tickets...")
        sql = """
        ALTER TABLE tickets
        ADD COLUMN sent_to_id INT,
        ADD CONSTRAINT fk_tickets_sent_to
        FOREIGN KEY (sent_to_id)
        REFERENCES agents(id)
        """
        execute_sql(sql)
        print("Added sent_to_id to tickets successfully.")
    
    # Add logo_url to teams
    if table_exists('teams') and not column_exists('teams', 'logo_url'):
        print("Adding logo_url to teams...")
        sql = """
        ALTER TABLE teams
        ADD COLUMN logo_url VARCHAR(255)
        """
        execute_sql(sql)
        print("Added logo_url to teams successfully.")
    
    # Add description to companies
    if table_exists('companies') and not column_exists('companies', 'description'):
        print("Adding description to companies...")
        sql = """
        ALTER TABLE companies
        ADD COLUMN description VARCHAR(1024)
        """
        execute_sql(sql)
        print("Added description to companies successfully.")
    
    # Add updated_at to comments
    if table_exists('comments') and not column_exists('comments', 'updated_at'):
        print("Adding updated_at to comments...")
        sql = """
        ALTER TABLE comments
        ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        """
        execute_sql(sql)
        print("Added updated_at to comments successfully.")
    
    # Add updated_at to activities
    if table_exists('activities') and not column_exists('activities', 'updated_at'):
        print("Adding updated_at to activities...")
        sql = """
        ALTER TABLE activities
        ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        """
        execute_sql(sql)
        print("Added updated_at to activities successfully.")

def main():
    print("Starting migration to workspace model...")
    
    # Step 1: Create workspaces table
    create_workspaces_table()
    
    # Step 2: Create default workspace
    default_workspace_id = create_default_workspace()
    print(f"Default workspace ID: {default_workspace_id}")
    
    # Step 3: Add workspace_id to all tables
    tables = ['agents', 'teams', 'companies', 'users', 'tasks', 'comments', 'activities']
    for table in tables:
        if table_exists(table):
            add_workspace_id_to_table(table, default_workspace_id)
    
    # Step 4: Update status enum in tickets table
    update_status_enum()
    
    # Step 5: Rename columns
    rename_columns()
    
    # Step 6: Add missing columns
    add_missing_columns()
    
    print("Migration completed successfully!")
    print("You may need to restart your application for the changes to take effect.")
    
if __name__ == "__main__":
    main() 