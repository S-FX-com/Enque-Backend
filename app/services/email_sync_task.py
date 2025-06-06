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
from app.core.config import settings


def sync_emails_job():
    """
    ⚡ Optimized email sync job with better error handling
    """
    # Starting email sync
    db = None
    
    try:
        db = SessionLocal()
        
        configs = db.query(EmailSyncConfig).filter(
            EmailSyncConfig.is_active == True
        ).all()
        
        if not configs:
            return
        
        # Process configs with better batching
        batch_size = settings.EMAIL_SYNC_BATCH_SIZE if hasattr(settings, 'EMAIL_SYNC_BATCH_SIZE') else 25
        successful_syncs = 0
        failed_syncs = 0
        
        for i in range(0, len(configs), batch_size):
            batch = configs[i:i + batch_size]
            # Processing batch
            
            for config in batch:
                try:
                    result = sync_single_config(config)
                    if result >= 0:
                        successful_syncs += 1
                        # Config synced successfully
                    else:
                        failed_syncs += 1
                except Exception as e:
                    logger.error(f"Error syncing config #{config.id}: {e}")
                    failed_syncs += 1
        
        if failed_syncs > 0:
            logger.info(f"📧 Sync: {successful_syncs} OK, {failed_syncs} failed")
                    
    except Exception as e:
        logger.error(f"Error in email sync job: {e}")
    finally:
        if db is not None:
            db.close()

def sync_single_config(config: EmailSyncConfig) -> int:
    """Sync emails for a single configuration with optimizations"""
    config_db = SessionLocal()
    try:
        integration = config_db.query(MicrosoftIntegration).filter(
            MicrosoftIntegration.id == config.integration_id,
            MicrosoftIntegration.is_active == True
        ).first()
        
        if not integration:
            logger.warning(f"No active integration found for sync config #{config.id}")
            return -1
            
        token = config_db.query(MicrosoftToken).filter(
            MicrosoftToken.integration_id == integration.id
        ).first()
        
        if not token:
            logger.warning(f"No token found for integration #{integration.id}")
            return -1
            
        service = MicrosoftGraphService(config_db)
        
        # Initialize cache if available (safe sync call)
        service._init_cache_if_needed()
        
        # Use the existing sync_emails method (it's already optimized with cache)
        created_tasks = service.sync_emails(config)
        return created_tasks or 0
        
    except Exception as e:
        logger.error(f"Error syncing emails for config #{config.id}: {e}")
        return -1
    finally:
        config_db.close()

def sync_emails_job_legacy():
    """
    Legacy sync job as fallback
    """
    logger.info("Starting legacy email sync job")
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
                config_db.close()
                
    except Exception as e:
        logger.error(f"Error in email sync job: {e}")
    finally:
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
    ⚡ Start the optimized background scheduler for email sync
    """
    if not scheduler_available:
        logger.warning("Schedule library is not available. Email synchronization scheduler will not run.")
        return
    
    # More intelligent scheduling based on load
    schedule.every(30).seconds.do(sync_emails_job)  # Optimized frequency
    schedule.every(3).hours.do(refresh_tokens_job)  # More frequent token refresh
    
    # Run in a separate thread with better error handling
    def run_scheduler():
        # Starting email sync scheduler
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                time.sleep(5)  # Wait before retrying
            
    scheduler_thread = threading.Thread(target=run_scheduler, name="EmailSyncScheduler")
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    logger.info("Email sync started")
