from sqlalchemy.orm import Session
from app.database.session import get_db, engine
from app.models.microsoft import MicrosoftIntegration
from app.core.config import settings
from app.utils.logger import logger

class StartupServices:
    def __init__(self):
        self._scheduler = None
        self._cache = None

    async def initialize(self):
        """Initialize all required services"""
        try:
            if engine:
                # await self._init_microsoft_integration()
                await self._init_cache()
                # await self._init_email_scheduler()
                
            logger.info("All services initialized successfully")
        except Exception as e:
            logger.error(f"Error during service initialization: {e}")

    async def shutdown(self):
        """Cleanup resources on shutdown"""
        if self._scheduler:
            await self._scheduler.shutdown()

    async def _init_microsoft_integration(self):
        """Initialize Microsoft integration"""
        if not all([
            settings.MICROSOFT_CLIENT_ID,
            settings.MICROSOFT_CLIENT_SECRET,
            settings.MICROSOFT_TENANT_ID
        ]):
            logger.warning("Microsoft integration environment variables missing")
            return

        db = next(get_db())
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
                logger.info("Microsoft integration initialized")
        finally:
            db.close()

    async def _init_cache(self):
        """Initialize cache service"""
        try:
            from app.services.cache_service import cache_service
            self._cache = cache_service
            logger.debug("Cache service available")
        except ImportError:
            logger.warning("Cache service not available")

    async def _init_email_scheduler(self):
        """Initialize email scheduler"""
        try:
            from app.services.email_sync_task import start_scheduler
            self._scheduler = start_scheduler()
            logger.info("Email scheduler initialized")
        except ImportError:
            logger.debug("Email sync scheduler not loaded - missing dependencies")

# Singleton instance
initialize = StartupServices()