from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException, status
import json
from datetime import datetime
import logging

from app.models.workflow import Workflow
from app.models.task import Task
from app.models.agent import Agent
from app.models.user import User
from app.models.comment import Comment
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate, WorkflowTriggerOption, WorkflowActionOption, MessageAnalysisRule, MessageAnalysisResult
from app.utils.logger import logger
from app.services.message_analysis_service import MessageAnalysisService
from app.core.exceptions import DatabaseException

logger = logging.getLogger(__name__)

class WorkflowService:
    
    def __init__(self, db: Session = None):
        """Initialize WorkflowService with optional database session"""
        self.db = db

    @staticmethod
    def get_workflows(db: Session, workspace_id: int, skip: int = 0, limit: int = 100) -> List[Workflow]:
        """Obtener todos los workflows de un workspace"""
        return db.query(Workflow).filter(
            Workflow.workspace_id == workspace_id
        ).offset(skip).limit(limit).all()

    @staticmethod
    def get_workflow(db: Session, workflow_id: int, workspace_id: int) -> Optional[Workflow]:
        """Obtener un workflow específico"""
        return db.query(Workflow).filter(
            and_(Workflow.id == workflow_id, Workflow.workspace_id == workspace_id)
        ).first()

    @staticmethod
    def get_default_message_analysis_rules():
        """Get default message analysis rules for content-based workflows"""
        return {
            "keywords": [],
            "language": "en",
            "min_confidence": 0.7,
            "urgency_keywords": {
                "high": [
                    "urgent", "asap", "emergency", "critical", "immediately", "now", "right now",
                    "crisis", "disaster", "broken", "down", "not working", "stopped working",
                    "can't access", "cannot access", "unable to", "blocked", "stuck", "frozen",
                    "error", "bug", "issue", "problem", "trouble", "difficulty", "struggling",
                    "deadline", "due today", "overdue", "time sensitive", "priority", "important",
                    "severe", "major", "serious", "crucial", "vital", "essential"
                ],
                "medium": [
                    "soon", "when possible", "at convenience", "sometime", "later today",
                    "this week", "next week", "follow up", "update", "status", "progress",
                    "question", "inquiry", "clarification", "information", "details",
                    "help", "assistance", "support", "guidance", "advice", "recommendation"
                ],
                "low": [
                    "no rush", "whenever", "no hurry", "take your time", "at your convenience",
                    "when you can", "if possible", "eventually", "in the future", "someday",
                    "suggestion", "idea", "proposal", "feedback", "comment", "opinion",
                    "general", "information", "fyi", "for your information", "heads up"
                ]
            },
            "categories": {
                "technical": [
                    "bug", "error", "issue", "problem", "trouble", "difficulty", "malfunction",
                    "not working", "broken", "down", "offline", "crashed", "freeze", "frozen",
                    "slow", "performance", "lag", "timeout", "connection", "network", "server",
                    "database", "api", "integration", "sync", "synchronization", "update",
                    "upgrade", "installation", "setup", "configuration", "settings", "access",
                    "login", "password", "authentication", "authorization", "permission",
                    "file", "upload", "download", "import", "export", "backup", "restore"
                ],
                "support": [
                    "help", "assistance", "support", "guidance", "how to", "tutorial", "guide",
                    "instruction", "steps", "process", "procedure", "workflow", "method",
                    "question", "inquiry", "ask", "wondering", "confused", "unclear", "explain",
                    "clarify", "demonstrate", "show", "example", "sample", "template",
                    "training", "learn", "understand", "knowledge", "documentation", "manual",
                    "faq", "frequently asked", "common", "typical", "usual", "standard"
                ],
                "account": [
                    "account", "profile", "user", "username", "email", "contact", "information",
                    "details", "data", "personal", "privacy", "security", "verification",
                    "activate", "deactivate", "enable", "disable", "suspend", "restore",
                    "delete", "remove", "add", "create", "register", "sign up", "sign in",
                    "logout", "session", "token", "key", "credential", "identity"
                ],
                "feature_request": [
                    "feature", "functionality", "capability", "enhancement", "improvement",
                    "suggestion", "idea", "proposal", "request", "add", "include", "implement",
                    "develop", "create", "build", "new", "additional", "extra", "more",
                    "better", "upgrade", "update", "modify", "change", "customize", "configure",
                    "option", "setting", "preference", "choice", "alternative", "variation",
                    "would like", "could you", "can you", "is it possible", "feasible"
                ],
                "feedback": [
                    "feedback", "review", "opinion", "comment", "thought", "experience",
                    "suggestion", "recommendation", "advice", "input", "perspective", "view",
                    "satisfaction", "rating", "score", "evaluation", "assessment", "report",
                    "testimonial", "complaint", "compliment", "praise", "criticism", "concern",
                    "impression", "observation", "note", "remark", "improvement", "better"
                ],
                "integration": [
                    "integration", "connect", "connection", "link", "sync", "synchronize",
                    "api", "webhook", "endpoint", "third party", "external", "plugin", "addon",
                    "extension", "app", "application", "service", "platform", "system",
                    "import", "export", "migrate", "transfer", "move", "copy", "share",
                    "embed", "widget", "iframe", "code", "snippet", "script", "automation"
                ]
            }
        }

    @staticmethod
    def create_workflow(db: Session, workflow_data: WorkflowCreate, workspace_id: int) -> Workflow:
        """Crear un nuevo workflow"""
        # Verificar que el nombre no esté en uso en este workspace
        existing = db.query(Workflow).filter(
            and_(Workflow.name == workflow_data.name, Workflow.workspace_id == workspace_id)
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A workflow with this name already exists in this workspace"
            )

        # For content-based triggers, ensure we have complete message analysis rules
        message_analysis_rules = None
        if workflow_data.trigger and workflow_data.trigger.startswith('message.'):
            if workflow_data.message_analysis_rules:
                # Use provided rules but ensure they're complete
                provided_rules = workflow_data.message_analysis_rules.dict()
                default_rules = WorkflowService.get_default_message_analysis_rules()
                
                # Merge with defaults for any missing fields
                for key, default_value in default_rules.items():
                    if key not in provided_rules or not provided_rules[key]:
                        provided_rules[key] = default_value
                
                message_analysis_rules = provided_rules
            else:
                # Use complete default rules
                message_analysis_rules = WorkflowService.get_default_message_analysis_rules()

        # Crear nuevo workflow
        db_workflow = Workflow(
            name=workflow_data.name,
            description=workflow_data.description,
            is_enabled=workflow_data.is_enabled,
            trigger=workflow_data.trigger,
            message_analysis_rules=message_analysis_rules,
            conditions=[condition.dict() for condition in workflow_data.conditions] if workflow_data.conditions else [],
            actions=[action.dict() for action in workflow_data.actions] if workflow_data.actions else [],
            workspace_id=workspace_id
        )
        
        db.add(db_workflow)
        db.commit()
        db.refresh(db_workflow)
        
        logger.info(f"Created workflow {db_workflow.name} for workspace {workspace_id}")
        return db_workflow

    @staticmethod
    def update_workflow(db: Session, workflow_id: int, workflow_data: WorkflowUpdate, workspace_id: int) -> Workflow:
        """Actualizar un workflow existente"""
        db_workflow = WorkflowService.get_workflow(db, workflow_id, workspace_id)
        
        if not db_workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )

        # Verificar nombre único si se está actualizando
        if workflow_data.name and workflow_data.name != db_workflow.name:
            existing = db.query(Workflow).filter(
                and_(
                    Workflow.name == workflow_data.name,
                    Workflow.workspace_id == workspace_id,
                    Workflow.id != workflow_id
                )
            ).first()
            
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A workflow with this name already exists in this workspace"
                )

        # Actualizar campos
        update_data = workflow_data.dict(exclude_unset=True)
        
        # Handle message_analysis_rules serialization
        if 'message_analysis_rules' in update_data and update_data['message_analysis_rules']:
            update_data['message_analysis_rules'] = update_data['message_analysis_rules'].dict()
        
        # Handle conditions serialization
        if 'conditions' in update_data and update_data['conditions']:
            update_data['conditions'] = [condition.dict() for condition in workflow_data.conditions]
        
        # Handle actions serialization  
        if 'actions' in update_data and update_data['actions']:
            update_data['actions'] = [action.dict() for action in workflow_data.actions]
        
        for field, value in update_data.items():
            setattr(db_workflow, field, value)

        db_workflow.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_workflow)
        
        logger.info(f"Updated workflow {db_workflow.name} for workspace {workspace_id}")
        return db_workflow

    @staticmethod
    def delete_workflow(db: Session, workflow_id: int, workspace_id: int) -> bool:
        """Eliminar un workflow"""
        db_workflow = WorkflowService.get_workflow(db, workflow_id, workspace_id)
        
        if not db_workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )

        db.delete(db_workflow)
        db.commit()
        
        logger.info(f"Deleted workflow {db_workflow.name} for workspace {workspace_id}")
        return True

    @staticmethod
    def toggle_workflow(db: Session, workflow_id: int, workspace_id: int, is_enabled: bool) -> Workflow:
        """Activar/desactivar un workflow"""
        db_workflow = WorkflowService.get_workflow(db, workflow_id, workspace_id)
        
        if not db_workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )

        db_workflow.is_enabled = is_enabled
        db_workflow.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_workflow)
        
        status_text = "enabled" if is_enabled else "disabled"
        logger.info(f"Workflow {db_workflow.name} {status_text} for workspace {workspace_id}")
        return db_workflow

    @staticmethod
    def duplicate_workflow(db: Session, workflow_id: int, workspace_id: int) -> Workflow:
        """Duplicar un workflow"""
        original_workflow = WorkflowService.get_workflow(db, workflow_id, workspace_id)
        
        if not original_workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )

        # Crear nombre único para la copia
        copy_name = f"{original_workflow.name} (Copy)"
        counter = 1
        
        while db.query(Workflow).filter(
            and_(Workflow.name == copy_name, Workflow.workspace_id == workspace_id)
        ).first():
            counter += 1
            copy_name = f"{original_workflow.name} (Copy {counter})"

        # Crear duplicado
        duplicate_workflow = Workflow(
            name=copy_name,
            description=original_workflow.description,
            is_enabled=False,  # Las copias se crean desactivadas por seguridad
            trigger=original_workflow.trigger,
            message_analysis_rules=original_workflow.message_analysis_rules,
            conditions=original_workflow.conditions.copy() if original_workflow.conditions else [],
            actions=original_workflow.actions.copy() if original_workflow.actions else [],
            workspace_id=workspace_id
        )
        
        db.add(duplicate_workflow)
        db.commit()
        db.refresh(duplicate_workflow)
        
        logger.info(f"Duplicated workflow {original_workflow.name} as {copy_name} for workspace {workspace_id}")
        return duplicate_workflow

    @staticmethod
    def get_available_triggers(workspace_id: int) -> List[WorkflowTriggerOption]:
        """Obtener los triggers disponibles para workflows"""
        return [
            WorkflowTriggerOption(
                value="message.urgency_high",
                label="High Urgency Detected",
                description="When high urgency keywords are detected in messages"
            ),
            WorkflowTriggerOption(
                value="message.urgency_medium",
                label="Medium or High Urgency Detected",
                description="When medium or high urgency keywords are detected in messages"
            )
        ]

    @staticmethod
    def get_available_actions(workspace_id: int) -> List[WorkflowActionOption]:
        """Obtener las acciones disponibles para workflows"""
        return [
            WorkflowActionOption(
                id="change_priority",
                name="Change Priority",
                description="Automatically change ticket priority based on detected urgency",
                config_schema={
                    "priority": {
                        "type": "string", 
                        "enum": ["Low", "Medium", "High", "Critical"], 
                        "description": "Priority level to set"
                    }
                }
            )
        ]

    @staticmethod
    def execute_workflows(db: Session, trigger: str, workspace_id: int, context: Dict[str, Any]) -> List[str]:
        """
        Ejecutar workflows que coincidan con el trigger dado
        
        Args:
            db: Sesión de base de datos
            trigger: El evento que activó el workflow
            workspace_id: ID del workspace
            context: Datos del contexto (ticket, comment, etc.)
            
        Returns:
            Lista de nombres de workflows ejecutados
        """
        executed_workflows = []
        
        # Obtener workflows activos para este trigger
        workflows = db.query(Workflow).filter(
            and_(
                Workflow.workspace_id == workspace_id,
                Workflow.is_enabled == True,
                Workflow.trigger == trigger
            )
        ).all()
        
        for workflow in workflows:
            try:
                # Evaluar condiciones
                if WorkflowService._evaluate_conditions(workflow.conditions or [], context):
                    # Ejecutar acciones
                    WorkflowService._execute_actions(db, workflow.actions or [], context)
                    executed_workflows.append(workflow.name)
                    logger.info(f"Executed workflow: {workflow.name} for trigger: {trigger}")
                    
            except Exception as e:
                logger.error(
                    f"Error executing workflow {workflow.name}: {e}",
                    extra={"workflow_id": workflow.id, "workspace_id": workspace_id, "trigger": trigger},
                    exc_info=True
                )
                continue
        
        return executed_workflows

    @staticmethod
    def _evaluate_conditions(conditions: List[Dict[str, Any]], context: Dict[str, Any]) -> bool:
        """Evaluar si se cumplen todas las condiciones del workflow"""
        if not conditions:
            return True  # Sin condiciones = siempre se ejecuta
        
        for condition in conditions:
            field = condition.get('field', '')
            operator = condition.get('operator', '')
            expected_value = condition.get('value')
            
            # Obtener valor actual del contexto
            actual_value = WorkflowService._get_field_value(field, context)
            
            # Evaluar condición
            if not WorkflowService._evaluate_condition(actual_value, operator, expected_value):
                return False
        
        return True

    @staticmethod
    def _get_field_value(field: str, context: Dict[str, Any]) -> Any:
        """Obtener el valor de un campo del contexto"""
        # Soportar notación de punto (ej: "ticket.status")
        parts = field.split('.')
        value = context
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
        
        return value

    @staticmethod
    def _evaluate_condition(actual_value: Any, operator: str, expected_value: Any) -> bool:
        """Evaluar una condición específica"""
        if operator == "equals":
            return actual_value == expected_value
        elif operator == "not_equals":
            return actual_value != expected_value
        elif operator == "contains":
            return str(expected_value).lower() in str(actual_value).lower() if actual_value else False
        elif operator == "not_contains":
            return str(expected_value).lower() not in str(actual_value).lower() if actual_value else True
        elif operator == "greater_than":
            return actual_value > expected_value if actual_value is not None else False
        elif operator == "less_than":
            return actual_value < expected_value if actual_value is not None else False
        elif operator == "is_empty":
            return not actual_value
        elif operator == "is_not_empty":
            return bool(actual_value)
        
        return False

    @staticmethod
    def _execute_actions(db: Session, actions: List[Dict[str, Any]], context: Dict[str, Any]):
        """Ejecutar las acciones del workflow"""
        for action in actions:
            action_type = action.get('type')
            action_config = action.get('config', {})
            
            try:
                if action_type == "change_priority":
                    WorkflowService._action_change_priority(db, action_config, context)
                else:
                    logger.warning(f"Unknown action type: {action_type}")
                    
            except Exception as e:
                logger.error(
                    f"Error executing action {action_type}: {e}",
                    extra={"action_type": action_type, "context": str(context)},
                    exc_info=True
                )
                continue

    @staticmethod
    def _action_change_priority(db: Session, config: Dict[str, Any], context: Dict[str, Any]):
        """Acción: Cambiar prioridad del ticket"""
        ticket = context.get('ticket')
        new_priority = config.get('priority')
        
        if ticket and new_priority:
            ticket.priority = new_priority
            db.commit()
            logger.info(f"Ticket {ticket.id} priority changed to {new_priority}")

    def process_message_for_workflows(self, message_content: str, workspace_id: int, context: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Process a message against all enabled workflows and execute matching ones
        This is the main entry point for content-based workflow automation
        """
        try:
            if not message_content or not message_content.strip():
                return []

            # Get all enabled workflows for this workspace
            workflows = self.db.query(Workflow).filter(
                Workflow.workspace_id == workspace_id,
                Workflow.is_enabled == True
            ).all()

            if not workflows:
                return []

            executed_workflows = []
            
            # Process each workflow
            for workflow in workflows:
                try:
                    # Parse message analysis rules
                    analysis_rules = None
                    if workflow.message_analysis_rules:
                        analysis_rules = MessageAnalysisRule(**workflow.message_analysis_rules)

                    # Analyze the message with DB session and workspace_id
                    analysis = MessageAnalysisService.analyze_message(
                        message_content, 
                        analysis_rules, 
                        self.db, 
                        workspace_id
                    )
                    
                    # Check if this workflow should trigger
                    should_trigger = MessageAnalysisService.check_trigger_match(
                        analysis, workflow.trigger, analysis_rules, self.db, workspace_id
                    )
                    
                    if should_trigger:
                        # Check additional conditions if any
                        if self._check_workflow_conditions(workflow, context, analysis):
                            # Execute workflow actions
                            execution_result = self._execute_workflow_actions(workflow, context, analysis)
                            
                            executed_workflows.append({
                                'workflow_id': workflow.id,
                                'workflow_name': workflow.name,
                                'trigger': workflow.trigger,
                                'analysis': analysis.dict(),
                                'execution_result': execution_result
                            })
                            
                            logger.info(f"Executed workflow {workflow.id} ({workflow.name}) for message analysis")
                        
                except Exception as e:
                    logger.error(
                        f"Error processing workflow {workflow.id}: {e}",
                        extra={"workflow_id": workflow.id, "workspace_id": workspace_id},
                        exc_info=True
                    )
                    continue

            return executed_workflows
            
        except Exception as e:
            logger.error(
                f"Error processing message for workflows: {e}",
                extra={"workspace_id": workspace_id},
                exc_info=True
            )
            return []

    def _check_workflow_conditions(self, workflow: Workflow, context: Dict[str, Any], analysis: MessageAnalysisResult) -> bool:
        """Check if workflow conditions are met"""
        try:
            if not workflow.conditions:
                return True

            for condition in workflow.conditions:
                field = condition.get('field')
                operator = condition.get('operator')
                value = condition.get('value')
                
                # Get the actual value from context or analysis
                actual_value = self._get_condition_value(field, context, analysis)
                
                # Evaluate the condition
                if not self._evaluate_condition(actual_value, operator, value):
                    return False
                    
            return True
            
        except Exception as e:
            logger.error(
                f"Error checking workflow conditions: {e}",
                extra={"workflow_id": workflow.id, "context": str(context)},
                exc_info=True
            )
            return False

    def _get_condition_value(self, field: str, context: Dict[str, Any], analysis: MessageAnalysisResult) -> Any:
        """Get the value for a condition field"""
        # Analysis-based fields
        if field == 'sentiment':
            return analysis.sentiment
        elif field == 'urgency':
            return analysis.urgency_level
        elif field == 'confidence':
            return analysis.confidence
        elif field == 'language':
            return analysis.language
        elif field == 'keywords_count':
            return len(analysis.keywords_found)
        elif field == 'categories_count':
            return len(analysis.categories)
            
        # Context-based fields
        elif context and field in context:
            return context[field]
            
        return None

    def _evaluate_condition(self, actual_value: Any, operator: str, expected_value: Any) -> bool:
        """Evaluate a single condition"""
        try:
            if operator == 'equals':
                return actual_value == expected_value
            elif operator == 'not_equals':
                return actual_value != expected_value
            elif operator == 'greater_than':
                return float(actual_value) > float(expected_value)
            elif operator == 'less_than':
                return float(actual_value) < float(expected_value)
            elif operator == 'greater_equal':
                return float(actual_value) >= float(expected_value)
            elif operator == 'less_equal':
                return float(actual_value) <= float(expected_value)
            elif operator == 'contains':
                return str(expected_value).lower() in str(actual_value).lower()
            elif operator == 'not_contains':
                return str(expected_value).lower() not in str(actual_value).lower()
            elif operator == 'in_list':
                return actual_value in expected_value if isinstance(expected_value, list) else False
            elif operator == 'not_in_list':
                return actual_value not in expected_value if isinstance(expected_value, list) else True
                
            return False
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not evaluate condition due to type mismatch: {e}")
            return False
        except Exception as e:
            logger.error(
                f"Error evaluating condition: {e}",
                extra={"actual_value": actual_value, "operator": operator, "expected_value": expected_value},
                exc_info=True
            )
            return False

    def _execute_workflow_actions(self, workflow: Workflow, context: Dict[str, Any], analysis: MessageAnalysisResult) -> Dict[str, Any]:
        """Execute workflow actions based on message analysis"""
        try:
            if not workflow.actions:
                return {'status': 'no_actions'}

            results = []
            
            for action in workflow.actions:
                action_type = action.get('type')
                action_config = action.get('config', {})
                
                try:
                    result = self._execute_single_action(action_type, action_config, context, analysis)
                    results.append({
                        'action_type': action_type,
                        'status': 'success',
                        'result': result
                    })
                    
                except Exception as e:
                    logger.error(f"Error executing action {action_type}: {str(e)}")
                    results.append({
                        'action_type': action_type,
                        'status': 'error',
                        'error': str(e)
                    })

            return {
                'status': 'completed',
                'actions_executed': len(results),
                'results': results
            }
            
        except Exception as e:
            logger.error(
                f"Error executing workflow actions: {e}",
                extra={"workflow_id": workflow.id},
                exc_info=True
            )
            return {'status': 'error', 'error': str(e)}

    def _execute_single_action(self, action_type: str, config: Dict[str, Any], context: Dict[str, Any], analysis: MessageAnalysisResult) -> Dict[str, Any]:
        """Execute a single workflow action"""
        
        if action_type == 'change_priority':
            return self._auto_prioritize_by_urgency(config, context, analysis)
        else:
            logger.warning(f"Unknown action type: {action_type}")
            return {'status': 'unknown_action_type'}

    def _auto_prioritize_by_urgency(self, config: Dict[str, Any], context: Dict[str, Any], analysis: MessageAnalysisResult) -> Dict[str, Any]:
        """Auto-set priority based on urgency detection"""
        # Si se especificó una prioridad en la configuración, usar esa
        if 'priority' in config and config['priority']:
            priority = config['priority']
            logger.info(f"Setting priority to {priority} as configured")
        else:
            # Auto-mapear basado en urgencia detectada
            urgency_map = {
                'high': 'Critical',
                'medium': 'High',
                'low': 'Medium'
            }
            priority = urgency_map.get(analysis.urgency_level, 'Medium')
            logger.info(f"Auto-setting priority to {priority} based on urgency: {analysis.urgency_level}")
        
        # Actualizar el ticket si está disponible en el contexto
        ticket = context.get('ticket')
        if ticket:
            ticket.priority = priority
            self.db.commit()
            logger.info(f"Updated ticket {ticket.id} priority to {priority}")
            
        return {'priority': priority, 'urgency_detected': analysis.urgency_level}
