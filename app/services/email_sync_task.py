import time
import threading
import asyncio
from datetime import datetime, timedelta
try:
    import schedule
    scheduler_available = True
except ImportError:
    scheduler_available = False

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select
from sqlalchemy import text

from app.database.session import get_async_driver
from app.models.microsoft import EmailSyncConfig, MicrosoftIntegration, MicrosoftToken
from app.services.cache_service import cache_service
from app.services.microsoft_service import MicrosoftGraphService
from app.utils.logger import logger
from app.core.config import settings
from app.core.exceptions import DatabaseException, MicrosoftAPIException

class EmailSyncCircuitBreaker:
    def __init__(self):
        self.failure_count = 0
        self.last_failure_time = None
        self.failure_threshold = 5
        self.recovery_timeout = 60
    
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

email_sync_circuit_breaker = EmailSyncCircuitBreaker()

def reset_email_sync_circuit_breaker():
    global email_sync_circuit_breaker
    email_sync_circuit_breaker.failure_count = 0
    email_sync_circuit_breaker.last_failure_time = None
    logger.info("🚑 EMERGENCY RESET: Email sync circuit breaker has been manually reset")
    return {"status": "success", "message": "Circuit breaker reset successfully"}

async def sync_emails_job():
    if not email_sync_circuit_breaker.can_execute():
        logger.debug("🚨 Email sync skipped due to circuit breaker (DB issues detected)")
        return

    local_engine = create_async_engine(get_async_driver(settings.DATABASE_URI), pool_pre_ping=True)
    JobSessionLocal = sessionmaker(bind=local_engine, class_=AsyncSession, autocommit=False, autoflush=False, expire_on_commit=False)
    
    async with JobSessionLocal() as db:
        try:
            stmt = select(EmailSyncConfig).filter(EmailSyncConfig.is_active == True)
            result = await db.execute(stmt)
            configs = result.scalars().all()
            
            # Detach configs from the session to prevent lazy loading issues
            # This ensures all necessary data is loaded and accessible without further DB calls
            for config in configs:
                await db.refresh(config)
                db.expunge(config)
            
            if not configs:
                email_sync_circuit_breaker.record_success()
                return

            successful_syncs, failed_syncs, total_tickets = 0, 0, 0
            logger.info(f"📧 Starting email sync for {len(configs)} configs")

            for config in configs:
                # Save ID before any operation that might fail
                config_id = config.id if hasattr(config, 'id') else None
                try:
                    res = await sync_single_config(db, config)
                    if res >= 0:
                        successful_syncs += 1
                        if res > 0: total_tickets += res
                    else:
                        failed_syncs += 1
                except Exception as e:
                    logger.error(f"Error syncing config #{config_id}: {e}", extra={"config_id": config_id}, exc_info=True)
                    failed_syncs += 1
            
            email_sync_circuit_breaker.record_success()

            if total_tickets > 0:
                logger.info(f"📧 Email sync completed: {total_tickets} tickets created")
            if failed_syncs > 0:
                logger.warning(f"⚠️ Email sync issues: {successful_syncs} successful, {failed_syncs} failed")
            elif successful_syncs > 0:
                logger.info(f"✅ Email sync completed successfully: {successful_syncs} configs processed")
                        
        except Exception as e:
            logger.error("Critical error in email sync job", extra={"error": str(e)}, exc_info=True)
            email_sync_circuit_breaker.record_failure()
        finally:
            await local_engine.dispose()

async def sync_single_config(db: AsyncSession, config: EmailSyncConfig) -> int:
    # Save ID before any operation that might fail
    config_id = config.id if hasattr(config, 'id') else None
    try:
        await db.execute(text("SELECT 1"))

        stmt = select(MicrosoftIntegration).filter(
            MicrosoftIntegration.id == config.integration_id,
            MicrosoftIntegration.is_active == True
        )
        result = await db.execute(stmt)
        integration = result.scalars().first()
        
        if not integration:
            logger.warning(f"⚠️ No active integration found for sync config #{config.id}")
            return -1
            
        stmt = select(MicrosoftToken).filter(
            MicrosoftToken.integration_id == integration.id,
            MicrosoftToken.mailbox_connection_id == config.mailbox_connection_id
        )
        result = await db.execute(stmt)
        token = result.scalars().first()
        
        if not token:
            logger.warning(f"⚠️ No token found for integration #{integration.id}")
            return -1
            
        service = MicrosoftGraphService(db)
        created_tasks = await service.sync_emails(config)
        
        tickets_created = created_tasks or 0
        if tickets_created > 0:
            logger.info(f"📧 Config {config.id}: {tickets_created} new tickets created")
        
        return tickets_created

    except Exception as e:
        logger.error(f"Error syncing emails for config #{config_id}: {e}", extra={"config_id": config_id}, exc_info=True)
        return -1

async def refresh_tokens_job():
    logger.info("Starting token refresh job")
    local_engine = create_async_engine(get_async_driver(settings.DATABASE_URI), pool_pre_ping=True)
    JobSessionLocal = sessionmaker(bind=local_engine, class_=AsyncSession, autocommit=False, autoflush=False, expire_on_commit=False)

    async with JobSessionLocal() as db:
        try:
            service = MicrosoftGraphService(db)
            await service.check_and_refresh_all_tokens_async()
            logger.info("Token refresh job completed")
        except Exception as e:
            logger.error(f"Error in token refresh job: {e}", exc_info=True)
        finally:
            await local_engine.dispose()

def run_scheduler_job(loop, job_func):
    """Schedules an async job to be run in the provided event loop."""
    async def job_wrapper():
        try:
            await job_func()
        except Exception as e:
            logger.error(f"Error running async job {job_func.__name__}: {e}", exc_info=True)
    
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(job_wrapper(), loop)
    else:
        logger.error("Event loop is not running. Cannot schedule async job.")

def start_scheduler(loop: asyncio.AbstractEventLoop):
    if not scheduler_available:
        logger.warning("❌ Schedule library is not available. Email synchronization scheduler will not run.")
        return

    sync_frequency = getattr(settings, 'EMAIL_SYNC_FREQUENCY_SECONDS', 180)
    
    # Schedule jobs to run in the provided event loop
    schedule.every(sync_frequency).seconds.do(run_scheduler_job, loop, sync_emails_job)
    schedule.every(3).hours.do(run_scheduler_job, loop, refresh_tokens_job)
    
    def run_scheduler_pending():
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                time.sleep(5)
            
    pending_thread = threading.Thread(target=run_scheduler_pending, name="SchedulerPendingChecker")
    pending_thread.daemon = True
    pending_thread.start()
    
    logger.info("📅 Scheduler started with jobs:")
    logger.info(f"  - Email sync: every {sync_frequency} seconds")
    logger.info("  - Token refresh: every 3 hours")
