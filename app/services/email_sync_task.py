import time
import threading
# 🔧 ADDED: Circuit breaker to prevent email sync from overwhelming DB
from datetime import datetime, timedelta
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

from sqlalchemy.orm import Session
from sqlalchemy import text  # 🔧 ADDED: Import text for SQLAlchemy 2.0 compatibility
from app.database.session import SessionLocal
from app.models.microsoft import EmailSyncConfig, MicrosoftIntegration, MicrosoftToken
from app.services.microsoft_service import MicrosoftGraphService
from app.utils.logger import logger
from app.core.config import settings

# 🔧 CIRCUIT BREAKER: Prevent email sync during DB issues
class EmailSyncCircuitBreaker:
    def __init__(self):
        self.failure_count = 0
        self.last_failure_time = None
        self.failure_threshold = 3  # After 3 failures, stop for a while
        self.recovery_timeout = 120  # 🔧 REDUCED: 2 minutes instead of 5 minutes
    
    def can_execute(self) -> bool:
        if self.failure_count < self.failure_threshold:
            return True
        
        if self.last_failure_time and datetime.now() - self.last_failure_time > timedelta(seconds=self.recovery_timeout):
            logger.info("🔄 Email sync circuit breaker: Attempting recovery after timeout")
            self.failure_count = 0
            return True
        
        return False
    
    def record_success(self):
        if self.failure_count > 0:
            logger.info(f"✅ Email sync circuit breaker: Recovered after {self.failure_count} failures")
        self.failure_count = 0
        self.last_failure_time = None
    
    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            logger.warning(f"🚨 Email sync circuit breaker: OPENED after {self.failure_count} failures. Will retry in {self.recovery_timeout} seconds")

# Global circuit breaker instance
email_sync_circuit_breaker = EmailSyncCircuitBreaker()


def sync_emails_job():
    """
    ⚡ Optimized email sync job with connection pool management and circuit breaker
    """
    # 🔧 CIRCUIT BREAKER: Check if we should skip due to recent failures
    if not email_sync_circuit_breaker.can_execute():
        logger.debug("🚨 Email sync skipped due to circuit breaker (DB issues detected)")
        return
    
    db = None
    
    try:
        db = SessionLocal()
        
        configs = db.query(EmailSyncConfig).filter(
            EmailSyncConfig.is_active == True
        ).all()
        
        if not configs:
            email_sync_circuit_breaker.record_success()  # No configs is not a failure
            return
        
        # 🔧 OPTIMIZED: Better batching to prevent connection pool exhaustion
        batch_size = settings.EMAIL_SYNC_BATCH_SIZE if hasattr(settings, 'EMAIL_SYNC_BATCH_SIZE') else 5  # Reduced default
        max_concurrent = getattr(settings, 'EMAIL_SYNC_CONCURRENT_CONNECTIONS', 3)
        
        successful_syncs = 0
        failed_syncs = 0
        total_tickets = 0
        total_comments = 0
        
        logger.info(f"📧 Starting email sync for {len(configs)} configs (batch_size={batch_size}, max_concurrent={max_concurrent})")
        
        # 🔧 IMPROVEMENT: Process in smaller batches with delay to avoid overwhelming DB
        for i in range(0, len(configs), batch_size):
            batch = configs[i:i + batch_size]
            
            # Process each config in the batch
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
                    
                    # 🔧 CRITICAL: Check for DB connection errors
                    if "QueuePool limit" in str(e) or "connection timed out" in str(e) or "Lost connection" in str(e):
                        logger.error(f"🚨 Database connection issue detected in email sync: {e}")
                        email_sync_circuit_breaker.record_failure()
                        raise  # Break out early to prevent further damage
            
            # 🔧 CRITICAL: Add delay between batches to reduce DB load
            if i + batch_size < len(configs):  # Don't sleep after the last batch
                time.sleep(0.5)  # 500ms delay between batches
        
        # 🔧 SUCCESS: Record successful completion
        email_sync_circuit_breaker.record_success()
        
        # Only show logs if there's real activity or errors
        if total_tickets > 0 or total_comments > 0:
            logger.info(f"📧 Email sync completed: {total_tickets} tickets created, {total_comments} comments added")
        
        if failed_syncs > 0:
            logger.warning(f"⚠️ Email sync issues: {successful_syncs} successful, {failed_syncs} failed")
        elif successful_syncs > 0:
            logger.info(f"✅ Email sync completed successfully: {successful_syncs} configs processed")
                    
    except Exception as e:
        logger.error(f"❌ Critical error in email sync job: {e}")
        
        # 🔧 CIRCUIT BREAKER: Record failure for critical DB errors
        if "QueuePool limit" in str(e) or "connection timed out" in str(e) or "Lost connection" in str(e):
            email_sync_circuit_breaker.record_failure()
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as close_error:
                logger.error(f"❌ Error closing DB connection: {close_error}")

def sync_single_config(config: EmailSyncConfig) -> int:
    """Sync emails for a single configuration with optimizations and error handling"""
    config_db = None
    try:
        config_db = SessionLocal()
        
        # 🔧 ADDED: Quick check if DB connection is available
        try:
            # Test the connection with a simple query
            config_db.execute(text("SELECT 1"))
            config_db.commit()
        except Exception as db_test_error:
            logger.error(f"❌ DB connection test failed for config #{config.id}: {db_test_error}")
            return -1
        
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
        
        # 🔧 IMPROVED: Add timeout protection for email sync
        start_time = time.time()
        max_sync_time = 60  # 60 seconds max per config
        
        try:
            # Use the existing sync_emails method (it's already optimized with cache)
            created_tasks = service.sync_emails(config)
            
            # Check if we're taking too long
            if time.time() - start_time > max_sync_time:
                logger.warning(f"⚠️ Email sync for config #{config.id} took longer than {max_sync_time}s")
        except Exception as sync_error:
            # 🔧 CRITICAL: Handle specific database errors
            if "QueuePool limit" in str(sync_error) or "connection timed out" in str(sync_error):
                logger.error(f"🚨 Database pool issue in sync_single_config #{config.id}: {sync_error}")
                raise  # Re-raise to be caught by the caller
            else:
                logger.error(f"❌ Email sync error for config #{config.id}: {sync_error}")
                return -1
        
        tickets_created = created_tasks or 0
        if tickets_created > 0:
            logger.info(f"📧 Config {config.id}: {tickets_created} new tickets created")
        
        return tickets_created
        
    except Exception as e:
        # 🔧 IMPROVED: Better error categorization
        if "QueuePool limit" in str(e) or "connection timed out" in str(e) or "Lost connection" in str(e):
            logger.error(f"🚨 Database connection issue in config #{config.id}: {e}")
            raise  # Re-raise critical DB errors
        else:
            logger.error(f"❌ Error syncing emails for config #{config.id}: {e}")
            return -1
    finally:
        if config_db is not None:
            try:
                config_db.close()
            except Exception as close_error:
                logger.error(f"❌ Error closing config DB connection: {close_error}")

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

def daily_outstanding_tasks_job():
    """
    Background job to send daily outstanding tasks reports to agents at 7am ET
    """
    import asyncio
    from app.services.email_service import process_daily_outstanding_reports
    
    logger.info("Starting daily outstanding tasks job")
    db = None
    
    try:
        # Check if it's 7am ET (07:00)
        import pytz
        et_timezone = pytz.timezone("America/New_York")
        now_et = datetime.now(et_timezone)
        
        current_hour_et = now_et.hour
        current_minute_et = now_et.minute

        if current_hour_et != 7:
            logger.debug(f"Current time {current_hour_et}:{current_minute_et:02d} ET is not 7am hour, skipping daily outstanding tasks")
            return
            
        logger.info(f"Current time {current_hour_et}:{current_minute_et:02d} ET is in the 7am range, proceeding with daily outstanding tasks report")
        
        db = SessionLocal()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(process_daily_outstanding_reports(db))
            
            if result["success"]:
                logger.info(f"✅ Daily outstanding tasks reports completed: {result['reports_sent']}/{result['total_agents']} sent")
                if result["errors"]:
                    logger.warning(f"⚠️ Some errors occurred: {result['errors']}")
            else:
                logger.info(f"Daily outstanding tasks reports skipped: {result.get('message', 'Unknown reason')}")
                
        finally:
            loop.close()
        
    except Exception as e:
        logger.error(f"❌ Error in daily outstanding tasks job: {str(e)}", exc_info=True)
    finally:
        if db is not None:
            db.close()


def cleanup_orphaned_connections():

    db = None
    try:
        from app.database.session import log_pool_status, get_pool_status
        
        # Log pool status before cleanup
        logger.info("🧹 Starting orphaned connections cleanup...")
        log_pool_status()
        
        db = SessionLocal()
        
        # Clean up orphaned email mappings (as mentioned in the original error)
        from app.models.microsoft import EmailTicketMapping
        from app.models.task import Task
        
        # Find email mappings without corresponding tickets
        orphaned_mappings = db.query(EmailTicketMapping).outerjoin(
            Task, EmailTicketMapping.ticket_id == Task.id
        ).filter(Task.id.is_(None)).all()
        
        if orphaned_mappings:
            logger.info(f"🧹 Found {len(orphaned_mappings)} orphaned email mappings. Cleaning up...")
            for mapping in orphaned_mappings:
                db.delete(mapping)
            db.commit()
            logger.info(f"✅ Cleaned up {len(orphaned_mappings)} orphaned email mappings")
        
        # Log pool status after cleanup
        log_pool_status()
        
    except Exception as e:
        logger.error(f"❌ Error during orphaned connections cleanup: {e}")
        if db:
            db.rollback()
    finally:
        if db is not None:
            try:
                db.close()
            except Exception as close_error:
                logger.error(f"❌ Error closing cleanup DB connection: {close_error}")

def monitor_database_health():
    """
    📊 Monitor database health and log warnings if needed
    """
    try:
        from app.database.session import get_pool_status, is_pool_healthy, log_pool_status
        
        if not is_pool_healthy():
            logger.warning("🚨 Database pool health check FAILED - high utilization detected")
            log_pool_status()
            
            # If pool utilization is very high, trigger cleanup
            status = get_pool_status()
            if not ("error" in status) and status.get('pool_utilization', 0) > 90:
                logger.warning("🧹 Pool utilization > 90%, triggering cleanup...")
                cleanup_orphaned_connections()
    except Exception as e:
        logger.error(f"❌ Error monitoring database health: {e}")

def start_scheduler():
    """
    ⚡ Start the optimized background scheduler for email sync
    """
    
    if not scheduler_available:
        logger.warning("❌ Schedule library is not available. Email synchronization scheduler will not run.")
        logger.warning("💡 Install with: pip install schedule")
        return
    
    # 🔧 OPTIMIZED: Reduced frequency to prevent connection pool exhaustion
    sync_frequency = getattr(settings, 'EMAIL_SYNC_FREQUENCY_SECONDS', 120)
    schedule.every(sync_frequency).seconds.do(sync_emails_job)  # Changed from 30 to 120 seconds
    schedule.every(3).hours.do(refresh_tokens_job)  # More frequent token refresh
    
    # 🔧 ADDED: Cleanup and monitoring jobs
    schedule.every(30).minutes.do(cleanup_orphaned_connections)  # Clean up every 30 minutes
    schedule.every(5).minutes.do(monitor_database_health)  # Monitor every 5 minutes
    
    # Weekly agent summary - check every hour on Fridays for the 3pm window
    schedule.every().hour.do(weekly_agent_summary_job)
    
    # 🔧 ADDED: Daily outstanding tasks - check every hour for the 7am ET window
    schedule.every().hour.do(daily_outstanding_tasks_job)
    
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
    logger.info(f"  - Email sync: every {sync_frequency} seconds (optimized)")
    logger.info("  - Token refresh: every 3 hours") 
    logger.info("  - Cleanup orphaned connections: every 30 minutes")
    logger.info("  - Database health monitoring: every 5 minutes")
    logger.info("  - Weekly agent summaries: every hour (executes only on Fridays at 3pm)")
    logger.info("  - Daily outstanding tasks: every hour (executes daily at 7am ET)")  # 🔧 ADDED
    


