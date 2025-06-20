from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.task import Task
from app.models.comment import Comment
from app.models.agent import Agent
from app.models.activity import Activity
from app.utils.logger import logger
from app.core.socketio import emit_ticket_update_sync


class TicketMergeService:
    """Service for handling ticket merge operations"""
    
    @staticmethod
    def validate_merge_request(
        db: Session,
        target_ticket_id: int,
        ticket_ids_to_merge: List[int],
        current_user: Agent
    ) -> Dict[str, Any]:
        """
        Validate that the merge request is valid
        Returns dict with 'valid' boolean and 'errors' list
        """
        errors = []
        
        # Verificar que el ticket principal existe y pertenece al workspace del usuario
        target_ticket = db.query(Task).filter(
            Task.id == target_ticket_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False,
            Task.is_merged == False
        ).first()
        
        if not target_ticket:
            errors.append(f"Ticket principal {target_ticket_id} no encontrado o no válido")
            return {"valid": False, "errors": errors, "target_ticket": None}
        
        # Verificar que los tickets a fusionar existen y son válidos
        tickets_to_merge = db.query(Task).filter(
            Task.id.in_(ticket_ids_to_merge),
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False,
            Task.is_merged == False,
            Task.id != target_ticket_id  # No permitir fusionar consigo mismo
        ).all()
        
        found_ids = [t.id for t in tickets_to_merge]
        missing_ids = set(ticket_ids_to_merge) - set(found_ids)
        
        if missing_ids:
            errors.append(f"Tickets no encontrados o no válidos: {list(missing_ids)}")
        
        if len(tickets_to_merge) == 0:
            errors.append("No hay tickets válidos para fusionar")
        
        # Verificar que ningún ticket ya está fusionado
        already_merged = [t.id for t in tickets_to_merge if t.is_merged]
        if already_merged:
            errors.append(f"Los siguientes tickets ya están fusionados: {already_merged}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "target_ticket": target_ticket,
            "tickets_to_merge": tickets_to_merge
        }
    
    @staticmethod
    def merge_tickets(
        db: Session,
        target_ticket_id: int,
        ticket_ids_to_merge: List[int],
        current_user: Agent
    ) -> Dict[str, Any]:
        """
        Merge multiple tickets into a target ticket
        """
        try:
            # Validar la solicitud
            validation = TicketMergeService.validate_merge_request(
                db, target_ticket_id, ticket_ids_to_merge, current_user
            )
            
            if not validation["valid"]:
                return {
                    "success": False,
                    "errors": validation["errors"],
                    "target_ticket_id": target_ticket_id,
                    "merged_ticket_ids": [],
                    "comments_transferred": 0
                }
            
            target_ticket = validation["target_ticket"]
            tickets_to_merge = validation["tickets_to_merge"]
            
            comments_transferred = 0
            merged_ticket_ids = []
            merge_timestamp = datetime.utcnow()
            
            for ticket in tickets_to_merge:
                try:
                    # Transferir comentarios
                    comments = db.query(Comment).filter(Comment.ticket_id == ticket.id).all()
                    
                    logger.info(f"🔄 [MERGE] Transferring {len(comments)} comments from ticket {ticket.id} to {target_ticket_id}")
                    
                    for comment in comments:
                        # Crear un comentario indicando el origen del merge
                        merge_note = f"[FUSIONADO desde Ticket #{ticket.id}] "
                        original_content = comment.content or ""
                        comment.content = merge_note + original_content
                        comment.ticket_id = target_ticket_id
                        
                        logger.info(f"   📝 Comment {comment.id}: moved to ticket {target_ticket_id}, has_s3={bool(comment.s3_html_url)}")
                        
                        db.add(comment)
                        comments_transferred += 1
                    
                    # Transferir mappings de email si existen
                    if ticket.email_mappings:
                        for mapping in ticket.email_mappings:
                            mapping.ticket_id = target_ticket_id
                            db.add(mapping)
                    
                    # Transferir el body del ticket si existe
                    if ticket.body and ticket.body.email_body:
                        # Si el ticket principal no tiene body, usar el del secundario
                        if not target_ticket.body:
                            ticket.body.ticket_id = target_ticket_id
                            db.add(ticket.body)
                        else:
                            # Si ya tiene body, agregar el contenido como comentario
                            merge_comment = Comment(
                                content=f"[CONTENIDO FUSIONADO desde Ticket #{ticket.id}]\n\n{ticket.body.email_body}",
                                ticket_id=target_ticket_id,
                                agent_id=current_user.id,
                                workspace_id=current_user.workspace_id,
                                is_private=True,
                                created_at=merge_timestamp
                            )
                            db.add(merge_comment)
                            comments_transferred += 1
                    
                    # Marcar el ticket como fusionado
                    ticket.is_merged = True
                    ticket.merged_to_ticket_id = target_ticket_id
                    ticket.merged_at = merge_timestamp
                    ticket.merged_by_agent_id = current_user.id
                    ticket.status = "Closed"  # Cerrar el ticket fusionado
                    
                    db.add(ticket)
                    merged_ticket_ids.append(ticket.id)
                    
                    # Registrar actividad
                    activity = Activity(
                        agent_id=current_user.id,
                        action="ticket_merged",
                        source_type="Ticket",
                        source_id=ticket.id,
                        workspace_id=current_user.workspace_id
                    )
                    db.add(activity)
                    
                    logger.info(f"Ticket {ticket.id} fusionado exitosamente con {target_ticket_id}")
                    
                except Exception as e:
                    logger.error(f"Error fusionando ticket {ticket.id}: {str(e)}")
                    raise e
            
            # Actualizar el ticket principal
            target_ticket.last_update = merge_timestamp
            target_ticket.updated_at = merge_timestamp
            db.add(target_ticket)
            
            # Registrar actividad en el ticket principal
            target_activity = Activity(
                agent_id=current_user.id,
                action="tickets_merged_into",
                source_type="Ticket",
                source_id=target_ticket_id,
                workspace_id=current_user.workspace_id
            )
            db.add(target_activity)
            
            # Commit todos los cambios
            db.commit()
            
            # Emitir eventos de actualización
            try:
                # Preparar datos del ticket principal para Socket.IO
                target_ticket_data = {
                    'id': target_ticket.id,
                    'title': target_ticket.title,
                    'status': target_ticket.status,
                    'priority': target_ticket.priority,
                    'workspace_id': target_ticket.workspace_id,
                    'assignee_id': target_ticket.assignee_id,
                    'team_id': target_ticket.team_id,
                    'user_id': target_ticket.user_id,
                    'updated_at': target_ticket.updated_at.isoformat() if target_ticket.updated_at else None,
                    'merged_tickets_count': len(merged_ticket_ids),
                    'was_merged_target': True,  # Indica que este ticket recibió comentarios fusionados
                    'invalidate_html_cache': True  # Señal para invalidar cache de HTML content
                }
                
                # Emitir actualización del ticket principal
                emit_ticket_update_sync(target_ticket.workspace_id, target_ticket_data)
                
                # Emitir actualización de cada ticket fusionado
                for ticket in tickets_to_merge:
                    merged_ticket_data = {
                        'id': ticket.id,
                        'title': ticket.title,
                        'status': ticket.status,
                        'priority': ticket.priority,
                        'workspace_id': ticket.workspace_id,
                        'assignee_id': ticket.assignee_id,
                        'team_id': ticket.team_id,
                        'user_id': ticket.user_id,
                        'updated_at': ticket.updated_at.isoformat() if ticket.updated_at else None,
                        'is_merged': ticket.is_merged,
                        'merged_to_ticket_id': ticket.merged_to_ticket_id
                    }
                    emit_ticket_update_sync(ticket.workspace_id, merged_ticket_data)
                
            except Exception as e:
                logger.error(f"Error emitiendo eventos de socket: {str(e)}")
            
            return {
                "success": True,
                "target_ticket_id": target_ticket_id,
                "merged_ticket_ids": merged_ticket_ids,
                "comments_transferred": comments_transferred,
                "message": f"Se fusionaron exitosamente {len(merged_ticket_ids)} tickets"
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error en merge_tickets: {str(e)}", exc_info=True)
            return {
                "success": False,
                "errors": [f"Error interno: {str(e)}"],
                "target_ticket_id": target_ticket_id,
                "merged_ticket_ids": [],
                "comments_transferred": 0
            } 