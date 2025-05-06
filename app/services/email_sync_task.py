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
    db = SessionLocal()
    
    try:
        configs = db.query(EmailSyncConfig).filter(
            EmailSyncConfig.is_active == True
        ).all()
        
        if not configs:
            logger.info("No active email sync configurations found")
            return
            
        for config in configs:
            if config.last_sync_time:
                next_sync_time = config.last_sync_time + timedelta(minutes=config.sync_interval)
                if datetime.utcnow() < next_sync_time:
                    logger.info(f"Skipping sync for config #{config.id} - not yet time")
                    continue
                
            integration = db.query(MicrosoftIntegration).filter(
                MicrosoftIntegration.id == config.integration_id,
                MicrosoftIntegration.is_active == True
            ).first()
            
            if not integration:
                logger.warning(f"No active integration found for sync config #{config.id}")
                continue
            token = db.query(MicrosoftToken).filter(
                MicrosoftToken.integration_id == integration.id
            ).first()
            
            if not token:
                logger.warning(f"No token found for integration #{integration.id}")
                continue
                
            try:
                service = MicrosoftGraphService(db)
                created_tasks = service.sync_emails(config)
            except Exception as e:
                logger.error(f"Error syncing emails for config #{config.id}: {e}")
                
    except Exception as e:
        logger.error(f"Error in email sync job: {e}")
    finally:
        db.close()


def refresh_tokens_job():
    """
    Background job to check and renew Microsoft tokens before they expire
    """
    logger.info("Starting token refresh job")
    db = SessionLocal()
    
    try:
        service = MicrosoftGraphService(db)
    
        service.check_and_refresh_all_tokens()
        
        logger.info("Token refresh job completed")
    except Exception as e:
        logger.error(f"Error refreshing tokens: {e}")
    finally:
        db.close()


def start_scheduler():
    """
    Start the background scheduler for email sync
    """
    if not scheduler_available:
        logger.warning("Schedule library is not available. Email synchronization scheduler will not run.")
        return
    schedule.every(20).seconds.do(sync_emails_job)
    schedule.every(4).hours.do(refresh_tokens_job)
    
    # Run in a separate thread
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(1)
            
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    logger.info("Email sync and token refresh scheduler started")
