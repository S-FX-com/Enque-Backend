import socketio
from typing import Dict, Set
import logging
import json
from app.utils.logger import logger
from app.core.config import settings
async_mgr = None
sync_mgr = None
if settings.REDIS_URL:
    async_mgr = socketio.AsyncRedisManager(settings.REDIS_URL, channel='socketio')
    sync_mgr = socketio.RedisManager(settings.REDIS_URL, channel='socketio', write_only=True)
    logger.info("✅ Socket.IO configured with RedisManager for scaling.")
else:
    logger.warning("⚠️ REDIS_URL not set. Socket.IO will not scale across multiple workers.")

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*",
    client_manager=async_mgr,
    logger=False,
    engineio_logger=False,
    ping_timeout=20,
    ping_interval=10
)

@sio.event
async def connect(sid, environ, auth):
    """Handle new connection and assign to workspace room."""
    try:
        workspace_id = None
        if auth and isinstance(auth, dict):
            workspace_id = auth.get('workspace_id')
        
        if not workspace_id and 'QUERY_STRING' in environ:
            query_string = environ['QUERY_STRING']
            if 'workspace_id=' in query_string:
                try:
                    workspace_id = int(query_string.split('workspace_id=')[1].split('&')[0])
                except (ValueError, IndexError):
                    pass
        
        if workspace_id:
            sio.enter_room(sid, f'workspace_{workspace_id}')
            logger.debug(f"Socket {sid} connected and joined workspace {workspace_id}")
        else:
            logger.warning(f"Socket {sid} connected without a workspace_id.")
            
    except Exception as e:
        logger.error(f"Error in socket connect: {e}", exc_info=True)

@sio.event
async def disconnect(sid):
    """Handle disconnection."""
    logger.debug(f"Socket {sid} disconnected.")
async def emit_new_ticket(workspace_id: int, ticket_data: dict):
    """Emitir evento de nuevo ticket"""
    try:
        room = f'workspace_{workspace_id}'
        await sio.emit('new_ticket', ticket_data, room=room)

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
@sio.event
async def ping(sid, data):
    """Responder a ping del cliente"""
    await sio.emit('pong', {'message': 'Connection is working!'}, room=sid)

def emit_comment_update_sync(workspace_id: int, comment_data: dict):
    """Emit comment update event from a synchronous context."""
    if not sync_mgr:
        logger.warning("Cannot emit sync event: RedisManager not configured.")
        return
    try:
        room = f'workspace_{workspace_id}'
        sync_mgr.emit('comment_updated', comment_data, room=room)
        logger.info(f"📤 Queued sync emit 'comment_updated' to workspace {workspace_id}")
    except Exception as e:
        logger.error(f"Error in sync emit comment_updated: {e}", exc_info=True)

def emit_new_ticket_sync(workspace_id: int, ticket_data: dict):
    """Emit new ticket event from a synchronous context."""
    if not sync_mgr:
        logger.warning("Cannot emit sync event: RedisManager not configured.")
        return
    try:
        room = f'workspace_{workspace_id}'
        sync_mgr.emit('new_ticket', ticket_data, room=room)
        logger.info(f"📤 Queued sync emit 'new_ticket' to workspace {workspace_id}")
    except Exception as e:
        logger.error(f"Error in sync emit new_ticket: {e}", exc_info=True)

def emit_ticket_update_sync(workspace_id: int, ticket_data: dict):
    """Emit ticket update event from a synchronous context."""
    if not sync_mgr:
        logger.warning("Cannot emit sync event: RedisManager not configured.")
        return
    try:
        room = f'workspace_{workspace_id}'
        sync_mgr.emit('ticket_updated', ticket_data, room=room)
        logger.info(f"📤 Queued sync emit 'ticket_updated' to workspace {workspace_id}")
    except Exception as e:
        logger.error(f"Error in sync emit ticket_updated: {e}", exc_info=True)
