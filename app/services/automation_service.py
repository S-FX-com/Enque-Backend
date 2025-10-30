from typing import Any, Dict, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, distinct, select
from app.models.automation import Automation, AutomationCondition, AutomationAction, ConditionType, ConditionOperator, ActionType, LogicalOperator
from app.schemas.automation import AutomationCreate, AutomationUpdate
from app.models.task import Task
from app.models.agent import Agent
from app.models.team import Team
from app.models.category import Category
from app.utils.logger import logger
import re


async def create(db: AsyncSession, *, obj_in: AutomationCreate, created_by_agent_id: int) -> Automation:
    """Create a new automation in the database."""
    db_obj = Automation(
        name=obj_in.name,
        workspace_id=obj_in.workspace_id,
        is_active=obj_in.is_active,
        created_by=created_by_agent_id,
    )
    db.add(db_obj)
    await db.flush()
    
    for condition_data in obj_in.conditions:
        condition = AutomationCondition(
            automation_id=db_obj.id,
            condition_type=condition_data.condition_type,
            condition_operator=condition_data.condition_operator,
            condition_value=condition_data.condition_value,
        )
        db.add(condition)
    
    for action_data in obj_in.actions:
        action = AutomationAction(
            automation_id=db_obj.id,
            action_type=action_data.action_type,
            action_value=action_data.action_value,
        )
        db.add(action)
    
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_by_id(db: AsyncSession, *, id: int) -> Optional[Automation]:
    """Get automation by ID."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Automation)
        .options(selectinload(Automation.conditions))
        .options(selectinload(Automation.actions))
        .filter(Automation.id == id)
    )
    return result.scalars().first()


async def get_by_workspace_id(
    db: AsyncSession, *, workspace_id: int, skip: int = 0, limit: int = 100
) -> List[Automation]:
    """Get all automations by workspace ID with pagination."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Automation)
        .options(selectinload(Automation.conditions))
        .options(selectinload(Automation.actions))
        .filter(Automation.workspace_id == workspace_id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def get_active_by_workspace_id(
    db: AsyncSession, *, workspace_id: int, skip: int = 0, limit: int = 100
) -> List[Automation]:
    """Get active automations by workspace ID with pagination."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Automation)
        .options(selectinload(Automation.conditions))
        .options(selectinload(Automation.actions))
        .filter(
            Automation.workspace_id == workspace_id,
            Automation.is_active == True
        )
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def update(
    db: AsyncSession, *, db_obj: Automation, obj_in: AutomationUpdate
) -> Automation:
    """Update automation in the database."""
    update_data = obj_in.model_dump(exclude_unset=True)

    conditions_data = update_data.pop("conditions", None)
    actions_data = update_data.pop("actions", None)

    for field, value in update_data.items():
        setattr(db_obj, field, value)

    if conditions_data is not None:
        # Clear existing conditions (cascade will delete them)
        db_obj.conditions.clear()
        # Add new conditions
        for condition_data in conditions_data:
            condition = AutomationCondition(
                automation_id=db_obj.id,
                condition_type=condition_data.get('condition_type') if isinstance(condition_data, dict) else condition_data.condition_type,
                condition_operator=condition_data.get('condition_operator') if isinstance(condition_data, dict) else condition_data.condition_operator,
                condition_value=condition_data.get('condition_value') if isinstance(condition_data, dict) else condition_data.condition_value,
            )
            db_obj.conditions.append(condition)

    if actions_data is not None:
        # Clear existing actions (cascade will delete them)
        db_obj.actions.clear()
        # Add new actions
        for action_data in actions_data:
            action = AutomationAction(
                automation_id=db_obj.id,
                action_type=action_data.get('action_type') if isinstance(action_data, dict) else action_data.action_type,
                action_value=action_data.get('action_value') if isinstance(action_data, dict) else action_data.action_value,
            )
            db_obj.actions.append(action)

    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def delete(db: AsyncSession, *, db_obj: Automation) -> None:
    """Delete automation from the database."""
    await db.delete(db_obj)
    await db.commit()


async def count_by_workspace_id(db: AsyncSession, *, workspace_id: int) -> int:
    """Count total automations in a workspace."""
    result = await db.execute(
        select(func.count()).select_from(Automation).filter(Automation.workspace_id == workspace_id)
    )
    return result.scalar()


async def count_active_by_workspace_id(db: AsyncSession, *, workspace_id: int) -> int:
    """Count active automations in a workspace."""
    result = await db.execute(
        select(func.count()).select_from(Automation).filter(
            Automation.workspace_id == workspace_id,
            Automation.is_active == True
        )
    )
    return result.scalar()


async def get_stats(db: AsyncSession, *, workspace_id: int) -> Dict[str, Any]:
    """Get statistics for automations in a workspace."""
    total_count = await count_by_workspace_id(db=db, workspace_id=workspace_id)
    active_count = await count_active_by_workspace_id(db=db, workspace_id=workspace_id)
    
    return {
        "total_count": total_count,
        "active_count": active_count
    }


async def get_automations(db: AsyncSession, workspace_id: int, skip: int = 0, limit: int = 100) -> List[Automation]:
    """Get all automations for a workspace"""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Automation)
        .options(selectinload(Automation.conditions))
        .options(selectinload(Automation.actions))
        .filter(Automation.workspace_id == workspace_id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def get_automation(db: AsyncSession, automation_id: int) -> Optional[Automation]:
    """Get a specific automation by ID"""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Automation)
        .options(selectinload(Automation.conditions))
        .options(selectinload(Automation.actions))
        .filter(Automation.id == automation_id)
    )
    return result.scalars().first()


async def execute_automations_for_ticket(db: AsyncSession, ticket: Task) -> List[str]:
    """
    Execute all active automations for a ticket
    Returns list of actions that were executed
    """
    from sqlalchemy.orm import selectinload

    executed_actions = []

    result = await db.execute(
        select(Automation)
        .options(selectinload(Automation.conditions))
        .options(selectinload(Automation.actions))
        .filter(
            Automation.workspace_id == ticket.workspace_id,
            Automation.is_active == True
        )
    )
    automations = result.scalars().all()
    
    for automation in automations:
        try:
            if _check_automation_conditions(automation, ticket):
                actions_executed = await _execute_automation_actions(db, automation, ticket)
                executed_actions.extend(actions_executed)
                
        except Exception as e:
            logger.error(f"Error executing automation {automation.id} for ticket {ticket.id}: {str(e)}")
            continue
    
    if executed_actions:
        await db.commit()
        logger.info(f"Executed {len(executed_actions)} automation actions for ticket #{ticket.id}")
    
    return executed_actions


def _check_automation_conditions(automation: Automation, ticket: Task) -> bool:
    """Check if conditions of an automation match the ticket using logical operators"""
    if not automation.conditions:
        return False
    
    # Evaluate each condition
    condition_results = []
    for condition in automation.conditions:
        result = _check_single_condition(condition, ticket)
        condition_results.append(result)
    
    # Apply logical operator
    if automation.conditions_operator == LogicalOperator.OR:
        # At least one condition must be true
        return any(condition_results)
    else:  # Default to AND
        # All conditions must be true
        return all(condition_results)


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
        elif condition_type == ConditionType.TICKET_BODY:  # Changed from NOTE
            # For ticket body, we might need to check the description or first comment
            return ticket.description or ""
        elif condition_type == ConditionType.USER:
            return ticket.user.email if ticket.user else ""
        elif condition_type == ConditionType.USER_DOMAIN:  # New condition type
            if ticket.user and ticket.user.email:
                # Extract domain from email
                email_parts = ticket.user.email.split('@')
                return email_parts[1] if len(email_parts) > 1 else ""
            return ""
        elif condition_type == ConditionType.INBOX:  # New condition type
            # This would need to be implemented based on how inbox information is stored
            # For now, return empty string - this needs to be implemented based on your data model
            return ticket.mailbox_connection_id or "" if hasattr(ticket, 'mailbox_connection_id') else ""
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


async def _execute_automation_actions(db: AsyncSession, automation: Automation, ticket: Task) -> List[str]:
    """Execute actions of an automation on a ticket using logical operators"""
    executed_actions = []
    
    if automation.actions_operator == LogicalOperator.OR:
        for action in automation.actions:
            try:
                action_result = await _execute_single_action(db, action, ticket)
                if action_result:
                    executed_actions.append(f"Automation '{automation.name}': {action_result}")
                    break
            except Exception as e:
                logger.error(f"Error executing action {action.id}: {str(e)}")
                continue
    else:
        for action in automation.actions:
            try:
                action_result = await _execute_single_action(db, action, ticket)
                if action_result:
                    executed_actions.append(f"Automation '{automation.name}': {action_result}")
            except Exception as e:
                logger.error(f"Error executing action {action.id}: {str(e)}")
                continue
    
    return executed_actions


async def _execute_single_action(db: AsyncSession, action: AutomationAction, ticket: Task) -> Optional[str]:
    """Execute a single action on a ticket"""
    try:
        if action.action_type == ActionType.SET_AGENT:
            result = await db.execute(
                select(Agent).filter(
                    Agent.email == action.action_value,
                    Agent.workspace_id == ticket.workspace_id
                )
            )
            agent = result.scalars().first()
            
            if agent:
                old_assignee = ticket.assignee.email if ticket.assignee else "Unassigned"
                ticket.assignee_id = agent.id
                return f"Set agent from '{old_assignee}' to '{agent.email}'"
            else:
                logger.warning(f"Agent not found: '{action.action_value}' in workspace {ticket.workspace_id}")
                return None
                
        elif action.action_type == ActionType.SET_TEAM:
            result = await db.execute(
                select(Team).filter(
                    Team.name == action.action_value,
                    Team.workspace_id == ticket.workspace_id
                )
            )
            team = result.scalars().first()
            
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
            
        elif action.action_type == ActionType.SET_CATEGORY:
            result = await db.execute(
                select(Category).filter(
                    Category.name == action.action_value,
                    Category.workspace_id == ticket.workspace_id
                )
            )
            category = result.scalars().first()
            
            if category:
                old_category = ticket.category.name if ticket.category else "Unassigned"
                ticket.category_id = category.id
                return f"Set category from '{old_category}' to '{category.name}'"
            else:
                logger.warning(f"Category not found: '{action.action_value}' in workspace {ticket.workspace_id}")
                return None
                
        elif action.action_type == ActionType.ALSO_NOTIFY:
            result = await db.execute(
                select(Agent).filter(
                    Agent.email == action.action_value,
                    Agent.workspace_id == ticket.workspace_id
                )
            )
            agent = result.scalars().first()
            
            if agent:
                try:
                    from app.services.task_service import send_assignment_notification
                    
                    original_assignee_id = ticket.assignee_id
                    ticket.assignee_id = agent.id
                    ticket.assignee = agent
                    
                    await send_assignment_notification(db, ticket)
                    logger.info(f"Successfully sent notification email to agent {agent.email} about ticket #{ticket.id}")
                    
                    ticket.assignee_id = original_assignee_id
                    if original_assignee_id:
                        result = await db.execute(select(Agent).filter(Agent.id == original_assignee_id))
                        ticket.assignee = result.scalars().first()
                    else:
                        ticket.assignee = None
                    
                    return f"Also notified agent '{agent.email}' via email"
                except Exception as e:
                    logger.error(f"Error sending notification email to agent {agent.email}: {str(e)}")
                    return f"Failed to notify agent '{agent.email}' - {str(e)}"
            else:
                logger.warning(f"Agent not found for notification: '{action.action_value}' in workspace {ticket.workspace_id}")
                return None
            
        else:
            logger.warning(f"Unknown action type: {action.action_type}")
            return None
            
    except Exception as e:
        logger.error(f"Error executing action {action.id}: {str(e)}")
        return None
