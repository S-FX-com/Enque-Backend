import asyncio
import threading
import time
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.models.agent import Agent
from app.utils.logger import logger
from app.services.automation_service import get_due_automations, run_automation

# Intervalo en segundos para comprobar automatizaciones (cada minuto)
CHECK_INTERVAL = 60

async def process_automations():
    """
    Procesa todas las automatizaciones pendientes de ejecución.
    Esta función es asíncrona para poder llamar a run_automation.
    """
    try:
        now = datetime.now()
        logger.info(f"Checking for automations due at {now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        db = SessionLocal()
        try:
            # Obtener todas las automatizaciones que deben ejecutarse ahora
            due_automations = get_due_automations(db)
            
            if due_automations:
                logger.info(f"Found {len(due_automations)} automations due for execution: {[a.id for a in due_automations]}")
                logger.info(f"Automation details: {[(a.id, a.name, a.schedule) for a in due_automations]}")
                
                # Obtener un agente administrador para ejecutar las automatizaciones
                admin_agent = db.query(Agent).filter(Agent.role == "admin").first()
                
                if not admin_agent:
                    logger.error("No admin agent found to execute scheduled automations")
                    # Intentar con un agente manager si no hay admin
                    admin_agent = db.query(Agent).filter(Agent.role == "manager").first()
                    if admin_agent:
                        logger.info(f"Using manager agent (ID: {admin_agent.id}) to execute automations")
                    else:
                        logger.error("No admin or manager agent found. Cannot execute automations.")
                        return
                else:
                    logger.info(f"Using admin agent (ID: {admin_agent.id}) to execute automations")
                
                # Ejecutar cada automatización
                for automation in due_automations:
                    try:
                        logger.info(f"Executing scheduled automation: {automation.name} (ID: {automation.id})")
                        logger.info(f"Automation details: Type={automation.type}, Schedule={automation.schedule}")
                        logger.info(f"Automation filters: {automation.filters}")
                        
                        result = await run_automation(db, automation, admin_agent)
                        
                        if result.success:
                            logger.info(f"✅ Automation {automation.id} executed successfully: {result.message}")
                        else:
                            logger.error(f"❌ Automation {automation.id} failed: {result.message}")
                    except Exception as e:
                        logger.error(f"Error executing automation {automation.id}: {str(e)}", exc_info=True)
            else:
                logger.info("No automations due for execution at this time")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error in process_automations: {str(e)}", exc_info=True)

def automations_loop():
    """
    Bucle principal que se ejecuta en un hilo separado.
    Comprueba periódicamente las automatizaciones pendientes.
    """
    logger.info("Automation scheduler started")
    
    while True:
        try:
            # Obtener la hora actual
            now = datetime.now()
            logger.info(f"Automation scheduler tick at {now.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Crear un nuevo bucle de eventos para este hilo
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Ejecutar la función asíncrona
            loop.run_until_complete(process_automations())
            loop.close()
            
            # Calcular cuánto tiempo esperar hasta el próximo minuto
            next_minute = 60 - now.second
            if next_minute == 0:
                next_minute = 60
            
            logger.info(f"Next check in {next_minute} seconds")
            
            # Esperar hasta el próximo minuto o el intervalo establecido, lo que sea menor
            sleep_time = min(next_minute, CHECK_INTERVAL)
            time.sleep(sleep_time)
        except Exception as e:
            logger.error(f"Error in automations_loop: {str(e)}", exc_info=True)
            # Si hay un error, esperar un poco antes de intentarlo de nuevo
            time.sleep(10)

def start_automation_scheduler():
    """
    Inicia el programador de automatizaciones en un hilo separado.
    """
    thread = threading.Thread(target=automations_loop, daemon=True)
    thread.start()
    logger.info("Automation scheduler thread started") 