from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.task import Task
from app.models.comment import Comment
from app.models.agent import Agent
from app.models.activity import Activity
from app.utils.logger import logger
from app.core.socketio import emit_ticket_update


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
 
        target_ticket = db.query(Task).filter(
            Task.id == target_ticket_id,
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False,
            Task.is_merged == False
        ).first()
        
        if not target_ticket:
            errors.append(f"Main ticket {target_ticket_id} not found or invalid")
            return {"valid": False, "errors": errors, "target_ticket": None}
 
        tickets_to_merge = db.query(Task).filter(
            Task.id.in_(ticket_ids_to_merge),
            Task.workspace_id == current_user.workspace_id,
            Task.is_deleted == False,
            Task.is_merged == False,
            Task.id != target_ticket_id 
        ).all()
        
        found_ids = [t.id for t in tickets_to_merge]
        missing_ids = set(ticket_ids_to_merge) - set(found_ids)
        
        if missing_ids:
            errors.append(f"Tickets not found or invalid: {list(missing_ids)}")
        
        if len(tickets_to_merge) == 0:
            errors.append("No valid tickets to merge")
 
        already_merged = [t.id for t in tickets_to_merge if t.is_merged]
        if already_merged:
            errors.append(f"The following tickets are already merged: {already_merged}")
        
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
                    # Transfer comments
                    comments = db.query(Comment).filter(Comment.ticket_id == ticket.id).all()
                    
                    for comment in comments:
                        merge_note = f"[MERGED from Ticket #{ticket.id}] "
                        comment.content = merge_note + comment.content
                        comment.ticket_id = target_ticket_id
                        db.add(comment)
                        comments_transferred += 1

                    if ticket.email_mappings:
                        for mapping in ticket.email_mappings:
                            mapping.ticket_id = target_ticket_id
                            db.add(mapping)

                    if ticket.body and ticket.body.email_body:
                        if not target_ticket.body:
                            ticket.body.ticket_id = target_ticket_id
                            db.add(ticket.body)
                        else:
                            merge_comment = Comment(
                                content=f"[MERGED CONTENT from Ticket #{ticket.id}]\n\n{ticket.body.email_body}",
                                ticket_id=target_ticket_id,
                                agent_id=current_user.id,
                                workspace_id=current_user.workspace_id,
                                is_private=True,
                                created_at=merge_timestamp
                            )
                            db.add(merge_comment)
                            comments_transferred += 1
                    ticket.is_merged = True
                    ticket.merged_to_ticket_id = target_ticket_id
                    ticket.merged_at = merge_timestamp
                    ticket.merged_by_agent_id = current_user.id
                    ticket.status = "Closed"  
                    
                    db.add(ticket)
                    merged_ticket_ids.append(ticket.id)
                    activity = Activity(
                        agent_id=current_user.id,
                        action="ticket_merged",
                        source_type="Ticket",
                        source_id=ticket.id,
                        workspace_id=current_user.workspace_id
                    )
                    db.add(activity)
                    
                    logger.info(f"Ticket {ticket.id} successfully merged with {target_ticket_id}")
                    
                except Exception as e:
                    logger.error(f"Error merging ticket {ticket.id}: {str(e)}")
                    raise e
  
            target_ticket.last_update = merge_timestamp
            target_ticket.updated_at = merge_timestamp
            db.add(target_ticket)
 
            target_activity = Activity(
                agent_id=current_user.id,
                action="tickets_merged_into",
                source_type="Ticket",
                source_id=target_ticket_id,
                workspace_id=current_user.workspace_id
            )
            db.add(target_activity)
            summary_comment = Comment(
                content=f"🔀 **Tickets Merged**\n\nThe following tickets have been merged into this ticket:\n" +
                        "\n".join([f"- Ticket #{tid}" for tid in merged_ticket_ids]) +
                        f"\n\nTotal comments transferred: {comments_transferred}\n" +
                        f"Merged by: {current_user.name}",
                ticket_id=target_ticket_id,
                agent_id=current_user.id,
                workspace_id=current_user.workspace_id,
                is_private=True,
                created_at=merge_timestamp
            )
            db.add(summary_comment)

            db.commit()
            try:
                emit_ticket_update(target_ticket_id)
                for merged_id in merged_ticket_ids:
                    emit_ticket_update(merged_id)
            except Exception as e:
                logger.error(f"Error emitting socket events: {str(e)}")
            
            return {
                "success": True,
                "target_ticket_id": target_ticket_id,
                "merged_ticket_ids": merged_ticket_ids,
                "comments_transferred": comments_transferred,
                "message": f"Successfully merged {len(merged_ticket_ids)} tickets"
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error in merge_tickets: {str(e)}", exc_info=True)
            return {
                "success": False,
                "errors": [f"Internal error: {str(e)}"],
                "target_ticket_id": target_ticket_id,
                "merged_ticket_ids": [],
                "comments_transferred": 0
            }
    
    @staticmethod
    def get_mergeable_tickets(
        db: Session,
        workspace_id: int,
        exclude_ticket_id: Optional[int] = None,
        search_term: Optional[str] = None,
        limit: int = 50
    ) -> List[Task]:
        """
        Get tickets that can be merged (not deleted, not already merged)
        """
        query = db.query(Task).filter(
            Task.workspace_id == workspace_id,
            Task.is_deleted == False,
            Task.is_merged == False
        )
        
        if exclude_ticket_id:
            query = query.filter(Task.id != exclude_ticket_id)
        
        if search_term:
            search_pattern = f"%{search_term}%"
            query = query.filter(
                Task.title.ilike(search_pattern)
            )
        
        return query.order_by(Task.created_at.desc()).limit(limit).all()
    
    @staticmethod
    def get_merged_tickets_for_ticket(
        db: Session,
        ticket_id: int,
        workspace_id: int
    ) -> List[Task]:
        """
        Get all tickets that were merged into this ticket
        """
        return db.query(Task).filter(
            Task.merged_to_ticket_id == ticket_id,
            Task.workspace_id == workspace_id,
            Task.is_merged == True
        ).order_by(Task.merged_at.desc()).all() 