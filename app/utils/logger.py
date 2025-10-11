"""
Simple logging wrapper - console only, no files
"""
import logging


# Configure basic logging for the entire app
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s"
)

# Pre-configured loggers for backwards compatibility
logger = logging.getLogger("enque")
ms_logger = logging.getLogger("enque.microsoft")
important_logger = logging.getLogger("enque.important")

def log_important(message: str) -> None:
    """Log important events"""
    important_logger.info(f"IMPORTANT - {message}")
