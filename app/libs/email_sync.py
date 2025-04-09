import time
import threading
import schedule

from datetime import datetime, timedelta
from app.libs.database import get_db
from app.models.microsoft import EmailSyncConfig, MicrosoftIntegration, MicrosoftToken
from app.services.microsoft import MicrosoftGraphService
from app.utils.logger import logger


def sync_emails_job():
    logger.info("Starting email sync job")
    db = get_db()
    
    try:
        # Get all active sync configurations
        configs = db.query(EmailSyncConfig).filter(
            EmailSyncConfig.is_active == True
        ).all()
        
        if not configs:
            logger.info("No active email sync configurations found")
            return
            
        for config in configs:
            # Check if it's time to sync based on the interval
            if config.last_sync_time:
                # The sync_interval is stored in minutes, so convert to minutes for the calculation
                next_sync_time = config.last_sync_time + timedelta(minutes=config.sync_interval)
                if datetime.utcnow() < next_sync_time:
                    logger.info(f"Skipping sync for config #{config.id} - not yet time")
                    continue
                    
            # Get the integration
            integration = db.query(MicrosoftIntegration).filter(
                MicrosoftIntegration.id == config.integration_id,
                MicrosoftIntegration.is_active == True
            ).first()
            
            if not integration:
                logger.warning(f"No active integration found for sync config #{config.id}")
                continue
                
            # Get a valid token
            token = db.query(MicrosoftToken).filter(
                MicrosoftToken.integration_id == integration.id
            ).first()
            
            if not token:
                logger.warning(f"No token found for integration #{integration.id}")
                continue
                
            try:
                # Initialize service
                service = MicrosoftGraphService(db)
                
                # Sync emails
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
    db = get_db()
    
    try:
        # Initialize service
        service = MicrosoftGraphService(db)
        
        # Check and renew all tokens
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
    # Schedule job to run every minute
    schedule.every(1).minutes.do(sync_emails_job)
    
    # Schedule job to refresh tokens every 4 hours
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