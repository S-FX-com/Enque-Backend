import socketio
from typing import Dict, Set
import logging
import json
from app.utils.logger import logger

# Configurar Socket.IO server con configuración PERFECTA
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True,
    ping_timeout=20,
    ping_interval=10
)

# Almacenar conexiones por workspace
workspace_connections: Dict[int, Set[str]] = {}

@sio.event
async def connect(sid, environ, auth):
    """Manejar nueva conexión"""
    try:
        logger.info(f"🔌 Socket connection attempt: {sid}")
        
        # Obtener workspace_id del auth o query params
        workspace_id = None
        if auth and isinstance(auth, dict):
            workspace_id = auth.get('workspace_id')
        
        # También intentar obtener del query string
        if not workspace_id and 'QUERY_STRING' in environ:
            query_string = environ['QUERY_STRING']
            if 'workspace_id=' in query_string:
                try:
                    workspace_id = int(query_string.split('workspace_id=')[1].split('&')[0])
                except (ValueError, IndexError):
                    pass
        
        if workspace_id:
            # Agregar conexión al workspace
            if workspace_id not in workspace_connections:
                workspace_connections[workspace_id] = set()
            workspace_connections[workspace_id].add(sid)
            
            # Unir al room del workspace
            sio.enter_room(sid, f'workspace_{workspace_id}')
            
            logger.info(f"✅ Socket {sid} connected to workspace {workspace_id}")
            logger.info(f"📊 Workspace {workspace_id} now has {len(workspace_connections[workspace_id])} connections")
        else:
            logger.warning(f"⚠️ Socket {sid} connected without workspace_id")
            
    except Exception as e:
        logger.error(f"❌ Error in socket connect: {str(e)}")

@sio.event
async def disconnect(sid):
    """Manejar desconexión"""
    try:
        logger.info(f"🔌 Socket disconnect: {sid}")
        
        # Remover de todos los workspaces
        for workspace_id, connections in workspace_connections.items():
            if sid in connections:
                connections.remove(sid)
                sio.leave_room(sid, f'workspace_{workspace_id}')
                logger.info(f"📊 Workspace {workspace_id} now has {len(connections)} connections")
                break
                
    except Exception as e:
        logger.error(f"❌ Error in socket disconnect: {str(e)}")

# Funciones para emitir eventos
async def emit_new_ticket(workspace_id: int, ticket_data: dict):
    """Emitir evento de nuevo ticket"""
    try:
        room = f'workspace_{workspace_id}'
        await sio.emit('new_ticket', ticket_data, room=room)
        logger.info(f"📤 Emitted new_ticket to workspace {workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error emitting new_ticket: {str(e)}")

async def emit_ticket_update(workspace_id: int, ticket_data: dict):
    """Emitir evento de actualización de ticket"""
    try:
        room = f'workspace_{workspace_id}'
        await sio.emit('ticket_updated', ticket_data, room=room)
        logger.info(f"📤 Emitted ticket_updated to workspace {workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error emitting ticket_updated: {str(e)}")

async def emit_ticket_deleted(workspace_id: int, ticket_id: int):
    """Emitir evento de ticket eliminado"""
    try:
        room = f'workspace_{workspace_id}'
        await sio.emit('ticket_deleted', {'ticket_id': ticket_id}, room=room)
        logger.info(f"📤 Emitted ticket_deleted to workspace {workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error emitting ticket_deleted: {str(e)}")

async def emit_comment_update(workspace_id: int, comment_data: dict):
    """Emitir evento de actualización de comentario"""
    try:
        room = f'workspace_{workspace_id}'
        await sio.emit('comment_updated', comment_data, room=room)
        logger.info(f"📤 Emitted comment_updated to workspace {workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error emitting comment_updated: {str(e)}")

async def emit_team_update(workspace_id: int, team_data: dict):
    """Emitir evento de actualización de equipo"""
    try:
        room = f'workspace_{workspace_id}'
        await sio.emit('team_updated', team_data, room=room)
        logger.info(f"📤 Emitted team_updated to workspace {workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error emitting team_updated: {str(e)}")

# Evento de debug para verificar conexión
@sio.event
async def ping(sid, data):
    """Responder a ping del cliente"""
    await sio.emit('pong', {'message': 'Connection is working!'}, room=sid)

def get_workspace_connections_count(workspace_id: int) -> int:
    """Obtener número de conexiones activas para un workspace"""
    return len(workspace_connections.get(workspace_id, set()))

# ✅ FUNCIÓN SÍNCRONA para usar en contextos como email sync
def emit_comment_update_sync(workspace_id: int, comment_data: dict):
    """Emitir evento de comentario de forma síncrona (para email sync)"""
    try:
        import asyncio
        
        # Intentar obtener el event loop actual
        try:
            loop = asyncio.get_running_loop()
            # Si hay un loop corriendo, usar create_task
            loop.create_task(emit_comment_update(workspace_id, comment_data))
        except RuntimeError:
            # No hay loop corriendo, crear uno nuevo
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(emit_comment_update(workspace_id, comment_data))
            finally:
                loop.close()
                
        logger.info(f"📤 Sync emit comment_updated queued for workspace {workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error in sync emit comment_updated: {str(e)}")

def emit_new_ticket_sync(workspace_id: int, ticket_data: dict):
    """Emitir evento de nuevo ticket de forma síncrona (para email sync)"""
    try:
        import asyncio
        
        # Intentar obtener el event loop actual
        try:
            loop = asyncio.get_running_loop()
            # Si hay un loop corriendo, usar create_task
            loop.create_task(emit_new_ticket(workspace_id, ticket_data))
        except RuntimeError:
            # No hay loop corriendo, crear uno nuevo
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(emit_new_ticket(workspace_id, ticket_data))
            finally:
                loop.close()
                
        logger.info(f"📤 Sync emit new_ticket queued for workspace {workspace_id}")
    except Exception as e:
        logger.error(f"❌ Error in sync emit new_ticket: {str(e)}") 