from typing import Any, List, Optional
import time
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session, noload
from sqlalchemy import or_, and_, func, String

from app.api.dependencies import get_current_active_user
from app.database.session import get_db
from app.models.task import Task
from app.models.agent import Agent
from app.schemas.task import Task as TaskSchema, TaskWithDetails, TicketUpdate
from app.models.microsoft import mailbox_team_assignments

logger = logging.getLogger(__name__)
router = APIRouter()
@router.get("/", response_model=List[TaskSchema])
async def read_tasks_optimized_default(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    team_id: Optional[int] = Query(None),
    assignee_id: Optional[int] = Query(None),
    priority: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
) -> Any:

    return await read_tasks_optimized(
        db=db, skip=skip, limit=limit, current_user=current_user,
        subject=subject, status=status, team_id=team_id,
        assignee_id=assignee_id, priority=priority, category_id=category_id
    )
@router.get("/fast", response_model=List[TaskSchema])
async def read_tasks_optimized(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    team_id: Optional[int] = Query(None),
    assignee_id: Optional[int] = Query(None),
    priority: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
) -> Any:

    start_time = time.time()

    query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(

        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.user),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.category)
    )
    if subject:
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if team_id:
        query = query.filter(
            or_(
                Task.team_id == team_id,
                and_(
                    Task.team_id.is_(None),
                    Task.mailbox_connection_id.isnot(None),
                    Task.mailbox_connection_id.in_(
                        db.query(mailbox_team_assignments.c.mailbox_connection_id).filter(
                            mailbox_team_assignments.c.team_id == team_id
                        )
                    )
                )
            )
        )
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if priority:
        query = query.filter(Task.priority == priority)
    if category_id:
        query = query.filter(Task.category_id == category_id)

    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    return tasks


@router.get("/assignee/{agent_id}/fast", response_model=List[TaskSchema])
async def read_assigned_tasks_optimized(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
    subject: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
) -> Any:

    start_time = time.time()
    
    query = db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(

        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.user),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.category)
    )

    if subject:
        query = query.filter(Task.title.ilike(f"%{subject}%"))
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)

    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    query_time = time.time() - start_time
    
    return tasks


@router.get("/assignee/{agent_id}", response_model=List[TaskSchema])
async def read_assignee_tasks_optimized(
    agent_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    start_time = time.time()
    
    query = db.query(Task).filter(
        Task.assignee_id == agent_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(

        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.user),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.category)
    )

    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    
    query_time = time.time() - start_time
    
    return tasks


@router.get("/team/{team_id}", response_model=List[TaskSchema])
async def read_team_tasks_optimized(
    team_id: int,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:
    """
    ENDPOINT OPTIMIZADO: Tasks asignadas a un equipo específico
    """
    start_time = time.time()

    query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(
        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.user),
        noload(Task.category),
        noload(Task.comments),
    )

    from app.models.agent import Agent
    from app.models.team import TeamMember
    query = query.join(Agent, Task.assignee_id == Agent.id).join(TeamMember, Agent.id == TeamMember.agent_id).filter(
        TeamMember.team_id == team_id
    )
    
    query = query.offset(skip).limit(limit)
    
    query_start = time.time()
    tasks = query.all()
    query_time = time.time() - query_start
    
    total_time = time.time() - start_time
    
    return tasks


@router.get("/search", response_model=List[TaskSchema])
async def search_tasks_optimized(
    q: str = Query(..., description="Término de búsqueda"),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 30,
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    start_time = time.time()
    
    # Consulta optimizada de búsqueda
    query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False,
        or_(
            Task.title.ilike(f"%{q}%"),
            Task.description.ilike(f"%{q}%"),
            Task.body.ilike(f"%{q}%"),
            func.cast(Task.id, String).ilike(f"%{q}%")
        )
    ).options(
        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.user),
        noload(Task.category),
        noload(Task.comments),
    ).offset(skip).limit(limit)
    
    query_start = time.time()
    tasks = query.all()
    query_time = time.time() - query_start
    
    total_time = time.time() - start_time
    
    return tasks


@router.get("/count")
async def get_tasks_count(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    status: Optional[str] = Query(None),
    assignee_id: Optional[int] = Query(None),
) -> dict:

    start_time = time.time()
    
    query = db.query(func.count(Task.id)).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    )
    
    if status:
        query = query.filter(Task.status == status)
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    
    count = query.scalar()
    
    query_time = time.time() - start_time
    logger.info(f"FAST COUNT: {count} tasks contados en {query_time*1000:.2f}ms")
    
    return {"count": count, "query_time_ms": round(query_time * 1000, 2)}


@router.get("/stats")
async def get_tasks_stats(
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> dict:

    start_time = time.time()
    
    stats = db.query(
        Task.status,
        func.count(Task.id).label('count')
    ).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).group_by(Task.status).all()
    
    result = {
        "stats": {stat.status: stat.count for stat in stats},
        "total": sum(stat.count for stat in stats)
    }
    
    query_time = time.time() - start_time
    logger.info(f"FAST STATS: Estadísticas generadas en {query_time*1000:.2f}ms")
    
    return {**result, "query_time_ms": round(query_time * 1000, 2)}


@router.get("/{task_id}/fast", response_model=TaskWithDetails)
async def read_single_task_optimized(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    start_time = time.time()
    
    exists_start = time.time()
    from sqlalchemy import exists as sql_exists
    
    ticket_exists = db.query(
        sql_exists().where(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        )
    ).scalar()
    
    exists_time = time.time() - exists_start

    if exists_time > 0.005:  
        pass
    
    if not ticket_exists:
        total_time = time.time() - start_time
        raise HTTPException(status_code=404, detail="Task not found")
    
    query_start = time.time()
    
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(

        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.user),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.category),
        noload(Task.merged_by_agent)
    ).first()
    
    query_time = time.time() - query_start
    
    if not task:
        total_time = time.time() - start_time
        raise HTTPException(status_code=404, detail="Task not found")

    content_analysis_start = time.time()
    title_size = len(task.title) if task.title else 0
    description_size = len(task.description) if task.description else 0
    content_analysis_time = time.time() - content_analysis_start
    
    total_time = time.time() - start_time
    
    return TaskWithDetails.from_orm(task)


@router.get("/{task_id}/cached", response_model=TaskWithDetails)
async def read_single_task_with_cache(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
    force_refresh: bool = False
) -> Any:

    start_time = time.time()
    logger.info(f"🎯 CACHED: Iniciando carga con caché para ticket {task_id} (force_refresh={force_refresh})")

    cached_data = None
    if not force_refresh:
        try:
            from app.services.cache_service import cache_service
            cache_start = time.time()
            cached_data = await cache_service.get_cached_ticket_data(task_id, current_user.workspace_id)
            cache_time = time.time() - cache_start
            
            if cached_data:
                total_time = time.time() - start_time
                pass
                
                task = Task(**cached_data)

                return TaskWithDetails.from_orm(task)
                
        except Exception as e:
            logger.warning(f"Error accediendo caché para ticket {task_id}: {e}")

    logger.info(f"💫 CACHE MISS: Consultando base de datos para ticket {task_id}")
    
    db_start = time.time()
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).options(

        noload(Task.workspace),
        noload(Task.assignee),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.user),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.category),
        noload(Task.merged_by_agent)
    ).first()
    
    db_time = time.time() - db_start
    
    if not task:
        total_time = time.time() - start_time
        logger.warning(f"❌ CACHED: Ticket {task_id} no encontrado en {total_time*1000:.2f}ms")
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        from app.services.cache_service import cache_service
        cache_start = time.time()

        task_dict = {
            'id': task.id,
            'title': task.title,
            'description': task.description,
            'status': task.status,
            'priority': task.priority,
            'assignee_id': task.assignee_id,
            'team_id': task.team_id,
            'due_date': task.due_date,
            'created_at': task.created_at,
            'updated_at': task.updated_at,
            'last_update': task.last_update,
            'sent_from_id': task.sent_from_id,
            'sent_to_id': task.sent_to_id,
            'user_id': task.user_id,
            'company_id': task.company_id,
            'workspace_id': task.workspace_id,
            'is_deleted': task.is_deleted,
            'deleted_at': task.deleted_at,
            'is_read': task.is_read,
            'mailbox_connection_id': task.mailbox_connection_id,
            'category_id': task.category_id,
            'email_message_id': task.email_message_id,
            'email_conversation_id': task.email_conversation_id,
            'email_sender': task.email_sender
        }
        
        await cache_service.cache_ticket_data(task_id, current_user.workspace_id, task_dict, ttl=300)
        cache_time = time.time() - cache_start
        
        logger.info(f"💾 CACHED: Ticket {task_id} almacenado en caché")
        
    except Exception as e:
        logger.warning(f"Error cacheando ticket {task_id}: {e}")
        cache_time = 0

    total_time = time.time() - start_time
    pass

    return TaskWithDetails.from_orm(task)


@router.get("/{task_id}/essential", response_model=TaskWithDetails)
async def read_single_task_essential_relations(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    start_time = time.time()
    exists_start = time.time()
    ticket_exists = db.query(Task.id).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first() is not None
    exists_time = time.time() - exists_start
    
    if not ticket_exists:
        raise HTTPException(status_code=404, detail="Task not found")

    from sqlalchemy.orm import joinedload
    
    task = db.query(Task).options(
        joinedload(Task.assignee),  
        joinedload(Task.user),      
        joinedload(Task.category),  
        noload(Task.workspace),
        noload(Task.sent_from),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.merged_by_agent)
    ).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskWithDetails.from_orm(task)


@router.put("/{task_id}/refresh", response_model=TaskWithDetails)
async def update_task_optimized_for_refresh(
    task_id: int,
    task_in: TicketUpdate, 
    request: Request,  
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    from fastapi import Request as FastAPIRequest
    from app.core.config import settings
    from sqlalchemy.orm import joinedload
    
    refresh_start_time = time.time()

    update_fields = [field for field, value in task_in.dict(exclude_unset=True).items() if value is not None]

    fetch_start = time.time()
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first()
    fetch_time = time.time() - fetch_start
    
    if not task:
        total_time = time.time() - refresh_start_time
        raise HTTPException(status_code=404, detail="Task not found")

    service_start = time.time()
    origin = request.headers.get("origin") or settings.FRONTEND_URL
    from app.services.task_service import update_task
    updated_task_dict = update_task(db=db, task_id=task_id, task_in=task_in, request_origin=origin)
    service_time = time.time() - service_start
    
    if not updated_task_dict:
        total_time = time.time() - refresh_start_time
        raise HTTPException(status_code=400, detail="Task update failed")

    reload_start = time.time()
    updated_task = db.query(Task).filter(Task.id == task_id).options(

        joinedload(Task.assignee),  
        joinedload(Task.user),      
        joinedload(Task.sent_from), 
        joinedload(Task.category),  

        noload(Task.workspace),
        noload(Task.sent_to),
        noload(Task.team),
        noload(Task.company),
        noload(Task.comments),
        noload(Task.email_mappings),
        noload(Task.body),
        noload(Task.mailbox_connection),
        noload(Task.merged_by_agent)
    ).first()
    reload_time = time.time() - reload_start
    
    # 4. Socket.IO (más rápido)
    socketio_start = time.time()
    try:
        task_data = {
            'id': updated_task.id,
            'title': updated_task.title,
            'status': updated_task.status,
            'priority': updated_task.priority,
            'workspace_id': updated_task.workspace_id,
            'assignee_id': updated_task.assignee_id,
            'team_id': updated_task.team_id,
            'user_id': updated_task.user_id,
            'updated_at': updated_task.updated_at.isoformat() if updated_task.updated_at else None
        }
        
        from app.core.socketio import emit_ticket_update_sync
        emit_ticket_update_sync(updated_task.workspace_id, task_data)
        socketio_time = time.time() - socketio_start
        
    except Exception as e:
        socketio_time = time.time() - socketio_start
        logger.warning(f"Socket.IO error en refresh optimizado: {e}")
    
    # 5. 📊 Performance summary
    total_time = time.time() - refresh_start_time
    
    # 🔧 CORREGIDO: Retornar schema con relaciones expandidas para mostrar contacto
    return TaskWithDetails.from_orm(updated_task)


@router.get("/{task_id}/performance-test")
async def performance_comparison_test(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    results = {}
    
    # Verificar que el ticket existe primero
    exists_start = time.time()
    ticket_exists = db.query(Task.id).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first() is not None
    exists_time = time.time() - exists_start
    
    if not ticket_exists:
        raise HTTPException(status_code=404, detail="Task not found")
    

    try:
        method1_start = time.time()
        task_fast = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).options(
            noload(Task.workspace), noload(Task.assignee), noload(Task.sent_from),
            noload(Task.sent_to), noload(Task.team), noload(Task.user),
            noload(Task.company), noload(Task.comments), noload(Task.email_mappings),
            noload(Task.body), noload(Task.mailbox_connection), noload(Task.category),
            noload(Task.merged_by_agent)
        ).first()
        method1_time = time.time() - method1_start
        results['fast_no_relations'] = {
            'time_ms': round(method1_time * 1000, 2),
            'relations_loaded': 0,
            'method': 'SIN relaciones (máxima velocidad)'
        }
        logger.info(f"✅ MÉTODO 1 (FAST): {method1_time*1000:.2f}ms - Sin relaciones")
    except Exception as e:
        logger.error(f"❌ MÉTODO 1 falló: {e}")
        results['fast_no_relations'] = {'error': str(e)}

    try:
        method2_start = time.time()
        task_essential = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).options(
            joinedload(Task.assignee), joinedload(Task.user), joinedload(Task.category),
            noload(Task.workspace), noload(Task.sent_from), noload(Task.sent_to),
            noload(Task.team), noload(Task.company), noload(Task.comments),
            noload(Task.email_mappings), noload(Task.body), noload(Task.mailbox_connection),
            noload(Task.merged_by_agent)
        ).first()
        method2_time = time.time() - method2_start
        results['essential_relations'] = {
            'time_ms': round(method2_time * 1000, 2),
            'relations_loaded': 3,
            'method': '3 relaciones esenciales (híbrido)'
        }
        logger.info(f"✅ MÉTODO 2 (ESSENTIAL): {method2_time*1000:.2f}ms - 3 relaciones")
    except Exception as e:
        logger.error(f"❌ MÉTODO 2 falló: {e}")
        results['essential_relations'] = {'error': str(e)}

    try:
        method3_start = time.time()
        task_full = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).options(
            joinedload(Task.workspace), joinedload(Task.sent_from), 
            joinedload(Task.sent_to), joinedload(Task.assignee),
            joinedload(Task.user), joinedload(Task.team),
            joinedload(Task.company), joinedload(Task.category),
            joinedload(Task.body), joinedload(Task.merged_by_agent)
        ).first()
        method3_time = time.time() - method3_start
        results['full_relations'] = {
            'time_ms': round(method3_time * 1000, 2),
            'relations_loaded': 10,
            'method': 'TODAS las relaciones (completo)'
        }
        logger.info(f"✅ MÉTODO 3 (FULL): {method3_time*1000:.2f}ms - 10 relaciones")
    except Exception as e:
        logger.error(f"❌ MÉTODO 3 falló: {e}")
        results['full_relations'] = {'error': str(e)}

    test_total_time = time.time() - exists_start
    
    pass
    
    valid_results = {k: v for k, v in results.items() if 'error' not in v}
    if valid_results:
        sorted_methods = sorted(valid_results.items(), key=lambda x: x[1]['time_ms'])
        fastest_method, fastest_data = sorted_methods[0]
        slowest_method, slowest_data = sorted_methods[-1]
        
        logger.info(f"🏆 FASTEST: {fastest_method} = {fastest_data['time_ms']}ms ({fastest_data['method']})")
        logger.info(f"🐌 SLOWEST: {slowest_method} = {slowest_data['time_ms']}ms ({slowest_data['method']})")
        
        if len(sorted_methods) > 1:
            improvement = ((slowest_data['time_ms'] - fastest_data['time_ms']) / slowest_data['time_ms']) * 100
        
        # Recomendaciones
        if fastest_data['time_ms'] < 30:
            pass
        if slowest_data['time_ms'] > 150:
            pass
        
        results['comparison_summary'] = {
            'fastest_method': fastest_method,
            'fastest_time_ms': fastest_data['time_ms'],
            'slowest_method': slowest_method,
            'slowest_time_ms': slowest_data['time_ms'],
            'performance_improvement_percent': round(improvement, 1) if len(sorted_methods) > 1 else 0,
            'recommendation': fastest_method
        }
    
    results['test_metadata'] = {
        'ticket_id': task_id,
        'user_id': current_user.id,
        'workspace_id': current_user.workspace_id,
        'test_duration_ms': round(test_total_time * 1000, 2),
        'timestamp': datetime.utcnow().isoformat()
    }
    
    return {
        'status': 'completed',
        'ticket_id': task_id,
        'results': results,
        'message': 'Performance comparison test completed successfully'
    } 


@router.get("/{task_id}/smart")
async def read_task_smart_optimization(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_active_user),
) -> Any:

    smart_start = time.time()
    logger.info(f"🧠 SMART OPTIMIZATION: Iniciando análisis inteligente para ticket {task_id}")

    analysis_start = time.time()
    
    # Verificar existencia con EXISTS optimizado
    from sqlalchemy import exists as sql_exists
    ticket_exists = db.query(
        sql_exists().where(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        )
    ).scalar()
    
    if not ticket_exists:
        total_time = time.time() - smart_start
        logger.warning(f"❌ SMART: Ticket {task_id} no encontrado en {total_time*1000:.2f}ms")
        raise HTTPException(status_code=404, detail="Task not found")

    basic_data = db.query(
        Task.id, Task.title, Task.description, 
        Task.assignee_id, Task.user_id, Task.category_id,
        Task.created_at
    ).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first()
    
    analysis_time = time.time() - analysis_start
    
    # 2. 🧠 DECISIÓN INTELIGENTE basada en análisis
    decision_start = time.time()
    
    # Calcular métricas para decisión
    title_size = len(basic_data.title) if basic_data.title else 0
    desc_size = len(basic_data.description) if basic_data.description else 0
    total_content = title_size + desc_size
    
    has_assignee = basic_data.assignee_id is not None
    has_user = basic_data.user_id is not None  
    has_category = basic_data.category_id is not None
    
    relations_needed = sum([has_assignee, has_user, has_category])
    
    # 🎯 ALGORITMO DE DECISIÓN INTELIGENTE
    if total_content < 100 and relations_needed == 0:
        strategy = "ULTRA_FAST"
        method = "Sin relaciones (contenido mínimo, sin datos relacionados)"
    elif total_content < 500 and relations_needed <= 1:
        strategy = "FAST"  
        method = "Sin relaciones (contenido pequeño, pocas relaciones)"
    elif relations_needed <= 3:
        strategy = "ESSENTIAL"
        method = "Relaciones esenciales (balance óptimo)"
    else:
        strategy = "SELECTIVE"
        method = "Relaciones selectivas (muchas relaciones detectadas)"
    
    decision_time = time.time() - decision_start
    
    pass

    execution_start = time.time()
    
    if strategy == "ULTRA_FAST":
        # Máxima velocidad - sin relaciones
        task = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).options(
            noload(Task.workspace), noload(Task.assignee), noload(Task.sent_from),
            noload(Task.sent_to), noload(Task.team), noload(Task.user),
            noload(Task.company), noload(Task.comments), noload(Task.email_mappings),
            noload(Task.body), noload(Task.mailbox_connection), noload(Task.category),
            noload(Task.merged_by_agent)
        ).first()
        
    elif strategy == "FAST":
        task = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).options(
            noload(Task.workspace), noload(Task.assignee), noload(Task.sent_from),
            noload(Task.sent_to), noload(Task.team), noload(Task.user),
            noload(Task.company), noload(Task.comments), noload(Task.email_mappings),
            noload(Task.body), noload(Task.mailbox_connection), noload(Task.category),
            noload(Task.merged_by_agent)
        ).first()
        
    elif strategy == "ESSENTIAL":
        from sqlalchemy.orm import joinedload
        task = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).options(
            joinedload(Task.assignee) if has_assignee else noload(Task.assignee),
            joinedload(Task.user) if has_user else noload(Task.user),
            joinedload(Task.category) if has_category else noload(Task.category),
            noload(Task.workspace), noload(Task.sent_from), noload(Task.sent_to),
            noload(Task.team), noload(Task.company), noload(Task.comments),
            noload(Task.email_mappings), noload(Task.body), noload(Task.mailbox_connection),
            noload(Task.merged_by_agent)
        ).first()
        
    else:  
        from sqlalchemy.orm import joinedload
        task = db.query(Task).filter(
            Task.id == task_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False
        ).options(
            joinedload(Task.assignee), joinedload(Task.user), joinedload(Task.category),
            noload(Task.workspace), noload(Task.sent_from), noload(Task.sent_to),
            noload(Task.team), noload(Task.company), noload(Task.comments),
            noload(Task.email_mappings), noload(Task.body), noload(Task.mailbox_connection),
            noload(Task.merged_by_agent)
        ).first()
    
    execution_time = time.time() - execution_start
    
    total_time = time.time() - smart_start
    
    pass
    
    return TaskWithDetails.from_orm(task) 


@router.get("/{task_id}/ultra-smart", response_model=TaskWithDetails)
async def get_task_ultra_smart_optimized(
    task_id: int,
    current_user: Agent = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:

    import time
    from app.services.cache_service import cached_ticket_exists_check
    from sqlalchemy.orm import joinedload, noload
    
    ultra_start = time.time()
    
    permissions_start = time.time()
    
    try:  
        ticket_exists = await cached_ticket_exists_check(
            db, task_id, current_user.workspace_id, current_user.id
        )
    except Exception as e:

        logger.warning(f"⚠️ Cache fallback: {e}")
        from sqlalchemy import exists as sql_exists
        ticket_exists = db.query(
            sql_exists().where(
                Task.id == task_id,
                Task.workspace_id == current_user.workspace_id,
                Task.is_deleted == False
            )
        ).scalar()
    
    if not ticket_exists:
        raise HTTPException(status_code=404, detail="Task not found")
    
    permissions_time = time.time() - permissions_start
    
    analysis_start = time.time()
    
    basic_query = db.query(Task.title, Task.description, Task.assignee_id, Task.user_id, Task.category_id).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).first()
    
    if not basic_query:
        raise HTTPException(status_code=404, detail="Task not found")
    
    title, description, assignee_id, user_id, category_id = basic_query
    
    title_size = len(title) if title else 0
    desc_size = len(description) if description else 0
    total_content = title_size + desc_size
    
    relations_count = sum([bool(assignee_id), bool(user_id), bool(category_id)])
    
    if total_content < 50 and relations_count == 0:
        strategy = "MINIMAL"
        expected_time = "~5-10ms"
    elif total_content < 200 and relations_count <= 1:
        strategy = "ESSENTIAL_LITE"  
        expected_time = "~10-20ms"
    elif total_content < 1000 and relations_count <= 2:
        strategy = "BALANCED"
        expected_time = "~20-35ms"
    else:
        strategy = "COMPLETE"
        expected_time = "~35-50ms"
    
    analysis_time = time.time() - analysis_start
    
    execution_start = time.time()
    
    base_query = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == current_user.workspace_id,
        Task.is_deleted == False
    ).execution_options(
        compiled_cache={},
        autoflush=False,
        autocommit=False
    )

    if strategy == "MINIMAL":
        task = base_query.options(
            joinedload(Task.user),      
            joinedload(Task.sent_from), 
            noload(Task.workspace), noload(Task.assignee), noload(Task.category),
            noload(Task.sent_to), noload(Task.team), noload(Task.company), 
            noload(Task.comments), noload(Task.body), noload(Task.merged_by_agent)
        ).first()
        
    elif strategy == "ESSENTIAL_LITE":

        options = [

            joinedload(Task.user),      
            joinedload(Task.sent_from), 
        ]

        if assignee_id:
            options.append(joinedload(Task.assignee))
            options.append(noload(Task.category))
        elif category_id:
            options.append(noload(Task.assignee))
            options.append(joinedload(Task.category))
        else:
            options.extend([noload(Task.assignee), noload(Task.category)])
        options.extend([
            noload(Task.workspace), noload(Task.sent_to), noload(Task.team), 
            noload(Task.company), noload(Task.comments), noload(Task.body), 
            noload(Task.merged_by_agent)
        ])
            
        task = base_query.options(*options).first()
        
    elif strategy == "BALANCED":
        task = base_query.options(
            joinedload(Task.user),      
            joinedload(Task.sent_from), 
            joinedload(Task.assignee) if assignee_id else noload(Task.assignee),
            joinedload(Task.category) if category_id else noload(Task.category),
            noload(Task.workspace), noload(Task.sent_to),
            noload(Task.team), noload(Task.company), noload(Task.comments),
            noload(Task.body), noload(Task.merged_by_agent)
        ).first()
        
    else:  
        task = base_query.options(
            joinedload(Task.assignee),
            joinedload(Task.user), 
            joinedload(Task.category),
            joinedload(Task.workspace),
            joinedload(Task.sent_from),
            noload(Task.sent_to), noload(Task.team), noload(Task.company), 
            noload(Task.comments), noload(Task.body), noload(Task.merged_by_agent)
        ).first()
    
    execution_time = time.time() - execution_start
    return TaskWithDetails.from_orm(task) 