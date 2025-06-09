from app.utils.logger import logger
from app.database.session import engine
from app.models.microsoft import MicrosoftIntegration
from app.core.config import settings

async def initialize_services():
    """Initialize all required services on startup"""
    try:
        # Initialize Microsoft integration if configured
        # await initialize_microsoft_integration()
        
        # Initialize cache service
        await initialize_cache()
        
        # Initialize email scheduler if available
        # await initialize_email_scheduler()
        
        logger.info("All services initialized successfully")
    except Exception as e:
        logger.error(f"Error during service initialization: {e}")

async def initialize_microsoft_integration():
    """Initialize Microsoft integration from environment variables"""
    if not engine:
        logger.warning("Skipping Microsoft integration - no database configured")
        return

    if not all([
        settings.MICROSOFT_CLIENT_ID,
        settings.MICROSOFT_CLIENT_SECRET,
        settings.MICROSOFT_TENANT_ID
    ]):
        logger.warning("Microsoft integration environment variables missing")
        return

    from sqlalchemy.orm import Session
    db = Session(engine)
    
    try:
        if not db.query(MicrosoftIntegration).filter_by(is_active=True).first():
            new_integration = MicrosoftIntegration(
                tenant_id=settings.MICROSOFT_TENANT_ID,
                client_id=settings.MICROSOFT_CLIENT_ID,
                client_secret=settings.MICROSOFT_CLIENT_SECRET,
                redirect_uri=settings.MICROSOFT_REDIRECT_URI,
                scope=settings.MICROSOFT_SCOPE,
                is_active=True
            )
            db.add(new_integration)
            db.commit()
            logger.info("Microsoft integration initialized from environment")
    finally:
        db.close()

async def initialize_cache():
    """Initialize cache service if available"""
    try:
        from app.services.cache_service import cache_service
        # Cache will initialize when first used
        logger.debug("Cache service available")
    except ImportError:
        logger.warning("Cache service not available")

async def initialize_email_scheduler():
    """Initialize email scheduler if available"""
    try:
        from app.services.email_sync_task import start_scheduler
        if engine:
            start_scheduler()
            logger.info("Email scheduler initialized")
    except ImportError:
        logger.debug("Email sync scheduler not loaded - missing dependencies")