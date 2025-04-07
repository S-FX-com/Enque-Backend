#!/usr/bin/env python3

"""
Script to check the database connection and diagnose common issues.
"""

import os
import json
import mysql.connector
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("db_check")

# Load environment variables
try:
    load_dotenv()
    logger.info("Environment variables loaded from .env")
except Exception as e:
    logger.warning(f"Could not load .env: {e}")

# Print all MySQL-related environment variables
env_vars = {}
for key, value in os.environ.items():
    if "MYSQL" in key and "PASSWORD" not in key:
        env_vars[key] = value
    elif "MYSQL_PASSWORD" in key:
        env_vars[key] = "********"  # Hide password

logger.info("Available MySQL environment variables:")
for key, value in env_vars.items():
    logger.info(f"  {key}={value}")

# Define different connection configurations to try
configs = [
    {
        "name": "Configuration with main MYSQL_* variables",
        "host": os.getenv("MYSQL_HOST"),
        "port": os.getenv("MYSQL_PORT"),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE")
    },
    {
        "name": "Configuration with Railway external host",
        "host": "hopper.proxy.rlwy.net",
        "port": os.getenv("MYSQL_PORT"),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE")
    },
    {
        "name": "Configuration with Railway internal host",
        "host": "mysql.railway.internal",
        "port": "3306",
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE")
    },
    {
        "name": "Configuration with Railway MYSQL* variables",
        "host": os.getenv("MYSQLHOST"),
        "port": os.getenv("MYSQLPORT"),
        "user": os.getenv("MYSQLUSER"),
        "password": os.getenv("MYSQLPASSWORD"),
        "database": os.getenv("MYSQLDATABASE")
    }
]

# Test each configuration
successful_config = None

for config in configs:
    if not all([config["host"], config["user"], config["password"], config["database"]]):
        logger.warning(f"Incomplete configuration for {config['name']}, skipping...")
        continue
    
    logger.info(f"Testing {config['name']}...")
    try:
        connection = mysql.connector.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"]
        )
        
        if connection.is_connected():
            logger.info(f"Successfully connected to {config['name']}")
            db_info = connection.get_server_info()
            logger.info(f"MySQL Server version: {db_info}")
            
            cursor = connection.cursor()
            cursor.execute("SELECT DATABASE();")
            db_name = cursor.fetchone()[0]
            logger.info(f"Connected to database: {db_name}")
            cursor.close()
            connection.close()
            
            successful_config = config
            break
    except Exception as e:
        logger.error(f"Connection failed for {config['name']}: {str(e)}")

if successful_config:
    logger.info("Successfully connected to the database with the following configuration:")
    logger.info(f"- Host: {successful_config['host']}")
    logger.info(f"- Port: {successful_config['port']}")
    logger.info(f"- User: {successful_config['user']}")
    logger.info(f"- Database: {successful_config['database']}")
    
    # Create working configuration file
    with open(".env.working", "w") as f:
        f.write(f"MYSQL_HOST={successful_config['host']}\n")
        f.write(f"MYSQL_PORT={successful_config['port']}\n")
        f.write(f"MYSQL_USER={successful_config['user']}\n")
        f.write(f"MYSQL_PASSWORD={successful_config['password']}\n")
        f.write(f"MYSQL_DATABASE={successful_config['database']}\n")
    
    logger.info("A .env.working file has been created with the working configuration")
    logger.info("To use this configuration, run: cp .env.working .env")
else:
    logger.error("Could not connect to the database with any configuration") 