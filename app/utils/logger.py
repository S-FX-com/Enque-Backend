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

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_format)
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
ms_logger.addHandler(console_handler)  # Also log to console 