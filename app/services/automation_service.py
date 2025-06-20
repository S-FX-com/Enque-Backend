from typing import Any, Dict, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from app.models.automation import Automation, AutomationCondition, AutomationAction, ConditionType, ConditionOperator, ActionType
from app.schemas.automation import AutomationCreate, AutomationUpdate
from app.models.task import Task
from app.models.agent import Agent
from app.models.team import Team
from app.utils.logger import logger


def create(db: Session, *, obj_in: AutomationCreate, created_by_agent_id: int) -> Automation:
    """Create a new automation in the database."""
    # Create the main automation
    db_obj = Automation(
        name=obj_in.name,
        workspace_id=obj_in.workspace_id,
        is_active=obj_in.is_active,
        created_by=created_by_agent_id,
    )
    db.add(db_obj)
    db.flush()  # Flush to get the ID
    
    # Create conditions
    for condition_data in obj_in.conditions:
        condition = AutomationCondition(
            automation_id=db_obj.id,
            condition_type=condition_data.condition_type,
            condition_operator=condition_data.condition_operator,
            condition_value=condition_data.condition_value,
        )
        db.add(condition)
    
    # Create actions
    for action_data in obj_in.actions:
        action = AutomationAction(
            automation_id=db_obj.id,
            action_type=action_data.action_type,
            action_value=action_data.action_value,
        )
        db.add(action)
    
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_by_id(db: Session, *, id: int) -> Optional[Automation]:
    """Get automation by ID."""
    return db.query(Automation).filter(Automation.id == id).first()


def get_by_workspace_id(
    db: Session, *, workspace_id: int, skip: int = 0, limit: int = 100
) -> List[Automation]:
    """Get all automations by workspace ID with pagination."""
    return (
        db.query(Automation)
        .filter(Automation.workspace_id == workspace_id)
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_active_by_workspace_id(
    db: Session, *, workspace_id: int, skip: int = 0, limit: int = 100
) -> List[Automation]:
    """Get active automations by workspace ID with pagination."""
    return (
        db.query(Automation)
        .filter(
            Automation.workspace_id == workspace_id,
            Automation.is_active == True
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def update(
    db: Session, *, db_obj: Automation, obj_in: AutomationUpdate
) -> Automation:
    """Update automation in the database."""
    update_data = obj_in.model_dump(exclude_unset=True)
    
    # Handle conditions and actions separately
    conditions_data = update_data.pop("conditions", None)
    actions_data = update_data.pop("actions", None)
    
    # Update basic fields
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    
    # Update conditions if provided
    if conditions_data is not None:
        # Delete existing conditions
        db.query(AutomationCondition).filter(
            AutomationCondition.automation_id == db_obj.id
        ).delete()
        
        # Create new conditions
        for condition_data in conditions_data:
            condition = AutomationCondition(
                automation_id=db_obj.id,
                condition_type=condition_data.get('condition_type') if isinstance(condition_data, dict) else condition_data.condition_type,
                condition_operator=condition_data.get('condition_operator') if isinstance(condition_data, dict) else condition_data.condition_operator,
                condition_value=condition_data.get('condition_value') if isinstance(condition_data, dict) else condition_data.condition_value,
            )
            db.add(condition)
    
    # Update actions if provided
    if actions_data is not None:
        # Delete existing actions
        db.query(AutomationAction).filter(
            AutomationAction.automation_id == db_obj.id
        ).delete()
        
        # Create new actions
        for action_data in actions_data:
            action = AutomationAction(
                automation_id=db_obj.id,
                action_type=action_data.get('action_type') if isinstance(action_data, dict) else action_data.action_type,
                action_value=action_data.get('action_value') if isinstance(action_data, dict) else action_data.action_value,
            )
            db.add(action)
    
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def delete(db: Session, *, db_obj: Automation) -> None:
    """Delete automation from the database."""
    db.delete(db_obj)
    db.commit()


def count_by_workspace_id(db: Session, *, workspace_id: int) -> int:
    """Count total automations in a workspace."""
    return db.query(Automation).filter(Automation.workspace_id == workspace_id).count()


def count_active_by_workspace_id(db: Session, *, workspace_id: int) -> int:
    """Count active automations in a workspace."""
    return (
        db.query(Automation)
        .filter(
            Automation.workspace_id == workspace_id,
            Automation.is_active == True
        )
        .count()
    )


def get_stats(db: Session, *, workspace_id: int) -> Dict[str, Any]:
    """Get statistics for automations in a workspace."""
    total_count = count_by_workspace_id(db=db, workspace_id=workspace_id)
    active_count = count_active_by_workspace_id(db=db, workspace_id=workspace_id)
    
    return {
        "total_count": total_count,
        "active_count": active_count
    }


def get_automations(db: Session, workspace_id: int, skip: int = 0, limit: int = 100) -> List[Automation]:
    """Get all automations for a workspace"""
    return db.query(Automation).filter(
        Automation.workspace_id == workspace_id
    ).offset(skip).limit(limit).all()


def get_automation(db: Session, automation_id: int) -> Optional[Automation]:
    """Get a specific automation by ID"""
    return db.query(Automation).filter(Automation.id == automation_id).first()


def execute_automations_for_ticket(db: Session, ticket: Task) -> List[str]:
    """
    Execute all active automations for a ticket
    Returns list of actions that were executed
    """
    executed_actions = []
    
    # Get all active automations for the workspace
    automations = db.query(Automation).filter(
        Automation.workspace_id == ticket.workspace_id,
        Automation.is_active == True
    ).all()
    
    for automation in automations:
        try:
            # Check if all conditions match
            if _check_automation_conditions(automation, ticket):
                # Execute all actions
                actions_executed = _execute_automation_actions(db, automation, ticket)
                executed_actions.extend(actions_executed)
                
        except Exception as e:
            logger.error(f"Error executing automation {automation.id} for ticket {ticket.id}: {str(e)}")
            continue
    
    if executed_actions:
        db.commit()
        logger.info(f"Executed {len(executed_actions)} automation actions for ticket #{ticket.id}")
    
    return executed_actions


def _check_automation_conditions(automation: Automation, ticket: Task) -> bool:
    """Check if all conditions of an automation match the ticket"""
    if not automation.conditions:
        return False
    
    for condition in automation.conditions:
        if not _check_single_condition(condition, ticket):
            return False
    
    return True


def _check_single_condition(condition: AutomationCondition, ticket: Task) -> bool:
    """Check if a single condition matches the ticket"""
    try:
        # Get the value from the ticket based on condition type
        ticket_value = _get_ticket_value(condition.condition_type, ticket)
        condition_value = condition.condition_value or ""
        
        if ticket_value is None:
            return False
        
        # Convert to strings for comparison
        ticket_value_str = str(ticket_value).strip()
        condition_value_str = str(condition_value).strip()
        
        # Apply the operator
        if condition.condition_operator == ConditionOperator.EQL:
            return ticket_value_str.lower() == condition_value_str.lower()
        elif condition.condition_operator == ConditionOperator.NEQL:
            return ticket_value_str.lower() != condition_value_str.lower()
        elif condition.condition_operator == ConditionOperator.CON:
            return condition_value_str.lower() in ticket_value_str.lower()
        elif condition.condition_operator == ConditionOperator.NCON:
            return condition_value_str.lower() not in ticket_value_str.lower()
        else:
            logger.warning(f"Unknown condition operator: {condition.condition_operator}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking condition {condition.id}: {str(e)}")
        return False


def _get_ticket_value(condition_type: ConditionType, ticket: Task) -> Optional[str]:
    """Get the value from the ticket based on the condition type"""
    try:
        if condition_type == ConditionType.DESCRIPTION:
            # DESCRIPTION en el frontend se mapea a "Subject", que corresponde al campo title del ticket
            return ticket.title or ""
        elif condition_type == ConditionType.NOTE:
            # For notes, we might need to check related comments/notes
            return ""  # TODO: Implement note checking if needed
        elif condition_type == ConditionType.USER:
            return ticket.user.email if ticket.user else ""
        elif condition_type == ConditionType.AGENT:
            return ticket.assignee.email if ticket.assignee else ""
        elif condition_type == ConditionType.COMPANY:
            return ticket.company.name if ticket.company else ""
        elif condition_type == ConditionType.PRIORITY:
            return ticket.priority or ""
        elif condition_type == ConditionType.CATEGORY:
            return ticket.category.name if ticket.category else ""
        else:
            logger.warning(f"Unknown condition type: {condition_type}")
            return None
    except Exception as e:
        logger.error(f"Error getting ticket value for condition type {condition_type}: {str(e)}")
        return None


def _execute_automation_actions(db: Session, automation: Automation, ticket: Task) -> List[str]:
    """Execute all actions of an automation on a ticket"""
    executed_actions = []
    
    for action in automation.actions:
        try:
            action_result = _execute_single_action(db, action, ticket)
            if action_result:
                executed_actions.append(f"Automation '{automation.name}': {action_result}")
        except Exception as e:
            logger.error(f"Error executing action {action.id}: {str(e)}")
            continue
    
    return executed_actions


def _execute_single_action(db: Session, action: AutomationAction, ticket: Task) -> Optional[str]:
    """Execute a single action on a ticket"""
    try:
        if action.action_type == ActionType.SET_AGENT:
            # Find agent by email
            agent = db.query(Agent).filter(
                Agent.email == action.action_value,
                Agent.workspace_id == ticket.workspace_id
            ).first()
            
            if agent:
                old_assignee = ticket.assignee.email if ticket.assignee else "Unassigned"
                ticket.assignee_id = agent.id
                return f"Set agent from '{old_assignee}' to '{agent.email}'"
            else:
                logger.warning(f"Agent not found: '{action.action_value}' in workspace {ticket.workspace_id}")
                return None
                
        elif action.action_type == ActionType.SET_TEAM:
            # Find team by name
            team = db.query(Team).filter(
                Team.name == action.action_value,
                Team.workspace_id == ticket.workspace_id
            ).first()
            
            if team:
                old_team = ticket.team.name if ticket.team else "Unassigned"
                ticket.team_id = team.id
                return f"Set team from '{old_team}' to '{team.name}'"
            else:
                logger.warning(f"Team not found: '{action.action_value}' in workspace {ticket.workspace_id}")
                return None
                
        elif action.action_type == ActionType.SET_PRIORITY:
            old_priority = ticket.priority or "Unassigned"
            ticket.priority = action.action_value
            return f"Set priority from '{old_priority}' to '{action.action_value}'"
            
        elif action.action_type == ActionType.SET_STATUS:
            old_status = ticket.status or "Unassigned"
            ticket.status = action.action_value
            return f"Set status from '{old_status}' to '{action.action_value}'"
            
        else:
            logger.warning(f"Unknown action type: {action.action_type}")
            return None
            
    except Exception as e:
        logger.error(f"Error executing action {action.id}: {str(e)}")
        return None 