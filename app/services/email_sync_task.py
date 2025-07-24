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
        total_tickets = 0
        total_comments = 0
        
        # Primero revisar si hay actividad antes de mostrar logs
        for i in range(0, len(configs), batch_size):
            batch = configs[i:i + batch_size]
            
            for config in batch:
                try:
                    result = sync_single_config(config)
                    if result >= 0:
                        successful_syncs += 1
                        if result > 0:
                            total_tickets += result
                    else:
                        failed_syncs += 1
                except Exception as e:
                    logger.error(f"❌ Error syncing config #{config.id}: {e}")
                    failed_syncs += 1
        
        # Solo mostrar logs si hay actividad real
        if total_tickets > 0 or total_comments > 0:
            logger.info(f"📧 Email sync found activity: {total_tickets} tickets, {total_comments} comments")
        
        if failed_syncs > 0:
            logger.warning(f"⚠️ Sync issues: {successful_syncs} OK, {failed_syncs} failed")
                    
    except Exception as e:
        logger.error(f"❌ Critical error in email sync job: {e}")
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
            logger.warning(f"⚠️ No active integration found for sync config #{config.id}")
            return -1
            
        token = config_db.query(MicrosoftToken).filter(
            MicrosoftToken.integration_id == integration.id,
            MicrosoftToken.mailbox_connection_id == config.mailbox_connection_id
        ).first()
        
        if not token:
            logger.warning(f"⚠️ No token found for integration #{integration.id}")
            return -1
            

            
        service = MicrosoftGraphService(config_db)
        
        # Initialize cache if available (safe sync call)
        service._init_cache_if_needed()
        
        # Use the existing sync_emails method (it's already optimized with cache)
        created_tasks = service.sync_emails(config)
        
        tickets_created = created_tasks or 0
        if tickets_created > 0:
            logger.info(f"📧 Config {config.id}: {tickets_created} new tickets created")
        
        return tickets_created
        
    except Exception as e:
        logger.error(f"❌ Error syncing emails for config #{config.id}: {e}")
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
    import asyncio
    
    logger.info("Starting token refresh job")
    db = None
    
    try:
        db = SessionLocal()
        service = MicrosoftGraphService(db)
    
        # Create event loop for async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(service.check_and_refresh_all_tokens_async())
        finally:
            loop.close()
        
        logger.info("Token refresh job completed")
    except Exception as e:
        logger.error(f"Error refreshing tokens: {e}")
    finally:
        if db is not None:
            db.close()


def weekly_agent_summary_job():
    """
    Background job to send weekly summaries to agents every Friday at 3pm ET
    """
    import asyncio
    from app.services.email_service import process_weekly_agent_summaries
    
    logger.info("Starting weekly agent summary job")
    db = None
    
    try:
        # Check if it's Friday (weekday 4 = Friday, 0 = Monday) in ET timezone
        import pytz
        et_timezone = pytz.timezone("America/New_York")
        now_et = datetime.now(et_timezone)
        
        if now_et.weekday() != 4:  # Not Friday
            logger.info(f"Today is not Friday (weekday: {now_et.weekday()}) in ET, skipping weekly summary")
            return
        
        # Check if it's approximately 3pm ET (15:00)
        current_hour_et = now_et.hour
        current_minute_et = now_et.minute
        
        # Allow 3-4pm ET range for flexibility (15:00-15:59)
        if current_hour_et != 15:
            logger.info(f"Current time {current_hour_et}:{current_minute_et:02d} ET is not 3pm hour, skipping weekly summary")
            return
            
        logger.info(f"Current time {current_hour_et}:{current_minute_et:02d} ET is in the 3pm range, proceeding with weekly summary")
        
        db = SessionLocal()
        
        # Create event loop for async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(process_weekly_agent_summaries(db))
            
            if result["success"]:
                logger.info(f"✅ Weekly agent summaries completed: {result['summaries_sent']}/{result['total_agents']} sent")
                if result["errors"]:
                    logger.warning(f"⚠️ Some errors occurred: {result['errors']}")
            else:
                logger.info(f"Weekly agent summaries skipped: {result.get('message', 'Unknown reason')}")
                
        finally:
            loop.close()
        
    except Exception as e:
        logger.error(f"❌ Error in weekly agent summary job: {str(e)}", exc_info=True)
    finally:
        if db is not None:
            db.close()


def start_scheduler():
    """
    ⚡ Start the optimized background scheduler for email sync
    """
    
    if not scheduler_available:
        logger.warning("❌ Schedule library is not available. Email synchronization scheduler will not run.")
        logger.warning("💡 Install with: pip install schedule")
        return
    
    # More intelligent scheduling based on load
    schedule.every(30).seconds.do(sync_emails_job)  # Optimized frequency
    schedule.every(3).hours.do(refresh_tokens_job)  # More frequent token refresh
    
    # Weekly agent summary - check every hour on Fridays for the 3pm window
    schedule.every().hour.do(weekly_agent_summary_job)
    
    # Run in a separate thread with better error handling
    def run_scheduler():

        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                logger.error(f"❌ Scheduler error: {e}")
                time.sleep(5)  # Wait before retrying
            
    scheduler_thread = threading.Thread(target=run_scheduler, name="EmailSyncScheduler")
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    logger.info("📅 Scheduler started with jobs:")
    logger.info("  - Email sync: every 30 seconds")
    logger.info("  - Token refresh: every 3 hours") 
    logger.info("  - Weekly agent summaries: every hour (executes only on Fridays at 3pm)")
    


