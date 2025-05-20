import time
import threading
try:
    import schedule
    scheduler_available = True
except ImportError:
    scheduler_available = False
    class DummyScheduler:
        def __init__(self):
            self.jobs = []
        
        def every(self, interval):
            return self
        
        def minutes(self):
            return self
        
        def do(self, func):
            return func
        
        def run_pending(self):
            pass
    
    schedule = DummyScheduler()

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.models.microsoft import EmailSyncConfig, MicrosoftIntegration, MicrosoftToken
from app.services.microsoft_service import MicrosoftGraphService
from app.utils.logger import logger


def sync_emails_job():
    """
    Background job to sync emails from Microsoft based on active configurations
    """
    logger.info("Starting email sync job")
    db = None
    
    try:
        db = SessionLocal()
        
        configs = db.query(EmailSyncConfig).filter(
            EmailSyncConfig.is_active == True
        ).all()
        
        if not configs:
            logger.info("No active email sync configurations found")
            return
            
        for config in configs:
            # Create a separate session for each configuration to avoid
            # holding connections open for too long
            config_db = SessionLocal()
            try:
                integration = config_db.query(MicrosoftIntegration).filter(
                    MicrosoftIntegration.id == config.integration_id,
                    MicrosoftIntegration.is_active == True
                ).first()
                
                if not integration:
                    logger.warning(f"No active integration found for sync config #{config.id}")
                    continue
                token = config_db.query(MicrosoftToken).filter(
                    MicrosoftToken.integration_id == integration.id
                ).first()
                
                if not token:
                    logger.warning(f"No token found for integration #{integration.id}")
                    continue
                    
                try:
                    service = MicrosoftGraphService(config_db)
                    created_tasks = service.sync_emails(config)
                except Exception as e:
                    logger.error(f"Error syncing emails for config #{config.id}: {e}")
            finally:
                # Ensure we close the config-specific database session
                config_db.close()
                
    except Exception as e:
        logger.error(f"Error in email sync job: {e}")
    finally:
        # Ensure we close the main database session
        if db is not None:
            db.close()


def refresh_tokens_job():
    """
    Background job to check and renew Microsoft tokens before they expire
    """
    logger.info("Starting token refresh job")
    db = None
    
    try:
        db = SessionLocal()
        service = MicrosoftGraphService(db)
    
        service.check_and_refresh_all_tokens()
        
        logger.info("Token refresh job completed")
    except Exception as e:
        logger.error(f"Error refreshing tokens: {e}")
    finally:
        if db is not None:
            db.close()


def start_scheduler():
    """
    Start the background scheduler for email sync
    """
    if not scheduler_available:
        logger.warning("Schedule library is not available. Email synchronization scheduler will not run.")
        return
    # Configura la frecuencia de sincronización a 15 segundos para mayor rapidez
    schedule.every(30).seconds.do(sync_emails_job)
    schedule.every(4).hours.do(refresh_tokens_job)
    
    # Run in a separate thread
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(1)
            
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    logger.info("Email sync (every 15s) and token refresh scheduler started")
