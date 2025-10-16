class EnqueException(Exception):
    """Base exception for the application."""
    pass

class DatabaseException(EnqueException):
    """For database-related errors."""
    pass

class MicrosoftAPIException(EnqueException):
    """For Microsoft Graph API errors."""
    pass
