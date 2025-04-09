import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Create logs directory if it doesn't exist
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Configure logger
logger = logging.getLogger("obiDesk")
logger.setLevel(logging.INFO)

# Format for logs - Simplified format for logs
log_format = logging.Formatter(
    "%(levelname)s - %(message)s"
)

# Console handler - Only show WARNING and above to reduce verbosity
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_format)
console_handler.setLevel(logging.WARNING)  # Set console logging to WARNING level
logger.addHandler(console_handler)

# File handler - We keep the complete format for log files
file_format = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

file_handler = RotatingFileHandler(
    logs_dir / "obiDesk.log",
    maxBytes=10485760,  # 10MB
    backupCount=10
)
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)

# Create specific logger for Microsoft integration
ms_logger = logging.getLogger("obiDesk.microsoft")
ms_logger.setLevel(logging.INFO)

# File handler for Microsoft integration
ms_file_handler = RotatingFileHandler(
    logs_dir / "microsoft.log",
    maxBytes=10485760,  # 10MB
    backupCount=5
)
ms_file_handler.setFormatter(file_format)
ms_logger.addHandler(ms_file_handler)

# Also log to console but with reduced verbosity 
ms_console_handler = logging.StreamHandler(sys.stdout)
ms_console_handler.setFormatter(log_format)
ms_console_handler.setLevel(logging.WARNING)  # Set console logging to WARNING level
ms_logger.addHandler(ms_console_handler)

# Special handler for important INFO events that should still be shown in console
important_console_handler = logging.StreamHandler(sys.stdout)
important_console_handler.setFormatter(logging.Formatter("IMPORTANT - %(message)s"))
important_console_handler.setLevel(logging.INFO)

# Create a special logger for important events
important_logger = logging.getLogger("obiDesk.important")
important_logger.setLevel(logging.INFO)
important_logger.addHandler(important_console_handler)
important_logger.addHandler(file_handler)  # Also log to main log file

def log_important(message: str) -> None:
    """Log important events that should be visible in console even at INFO level"""
    important_logger.info(message) 