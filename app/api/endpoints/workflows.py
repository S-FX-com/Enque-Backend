from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_user, check_workspace_access
from app.models.agent import Agent
from app.schemas.workflow import (
    Workflow,
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowToggle,
    WorkflowTriggerOption,
    WorkflowActionOption
)
from app.services.workflow_service import WorkflowService
from app.utils.logger import logger

router = APIRouter()

@router.get("/{workspace_id}/workflows", response_model=List[Workflow])
async def get_workflows(
    workspace_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_user),
):
    """
    Obtener todos los workflows de un workspace.
    Requiere acceso al workspace.
    """
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    workflows = WorkflowService.get_workflows(db, workspace_id, skip, limit)
    return workflows

@router.get("/{workspace_id}/triggers", response_model=List[WorkflowTriggerOption])
def get_workflow_triggers(
    workspace_id: int,
    current_user: Agent = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get available workflow triggers"""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can access workflow triggers")
    
    return WorkflowService.get_available_triggers(workspace_id)

@router.get("/{workspace_id}/actions", response_model=List[WorkflowActionOption])
def get_workflow_actions(
    workspace_id: int,
    current_user: Agent = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get available workflow actions"""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can access workflow actions")
    
    return WorkflowService.get_available_actions(workspace_id)

# NEW ENDPOINT: Test message analysis
@router.post("/{workspace_id}/test-analysis")
def test_message_analysis(
    workspace_id: int,
    request: dict,
    current_user: Agent = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Test message analysis against content-based rules"""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can test message analysis")
    
    try:
        from app.services.message_analysis_service import MessageAnalysisService
        from app.schemas.workflow import MessageAnalysisRule
        
        message_content = request.get('message', '')
        if not message_content:
            raise HTTPException(status_code=400, detail="Message content is required")
        
        # Parse optional analysis rules
        rules = None
        if 'analysis_rules' in request:
            rules = MessageAnalysisRule(**request['analysis_rules'])
        
        # Analyze the message with DB session and workspace_id
        analysis = MessageAnalysisService.analyze_message(
            message_content, 
            rules, 
            db, 
            workspace_id
        )
        
        return {
            "message": message_content,
            "analysis": analysis.dict(),
            "analysis_rules": rules.dict() if rules else None
        }
        
    except Exception as e:
        logger.error(f"Error testing message analysis: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@router.post("/{workspace_id}/workflows", response_model=Workflow, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workspace_id: int,
    workflow: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_user),
):
    """
    Crear un nuevo workflow.
    Solo administradores pueden crear workflows.
    """
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Verificar que sea administrador
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create workflows"
        )
    
    return WorkflowService.create_workflow(db, workflow, workspace_id)

@router.get("/{workspace_id}/workflows/{workflow_id}", response_model=Workflow)
async def get_workflow(
    workspace_id: int,
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_user),
):
    """
    Obtener un workflow específico.
    """
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    workflow = WorkflowService.get_workflow(db, workflow_id, workspace_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )
    
    return workflow

@router.put("/{workspace_id}/workflows/{workflow_id}", response_model=Workflow)
async def update_workflow(
    workspace_id: int,
    workflow_id: int,
    workflow: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_user),
):
    """
    Actualizar un workflow existente.
    Solo administradores pueden actualizar workflows.
    """
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Verificar que sea administrador
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can update workflows"
        )
    
    return WorkflowService.update_workflow(db, workflow_id, workflow, workspace_id)

@router.delete("/{workspace_id}/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workspace_id: int,
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_user),
):
    """
    Eliminar un workflow.
    Solo administradores pueden eliminar workflows.
    """
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Verificar que sea administrador
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete workflows"
        )
    
    WorkflowService.delete_workflow(db, workflow_id, workspace_id)

@router.post("/{workspace_id}/workflows/{workflow_id}/toggle", response_model=Workflow)
async def toggle_workflow(
    workspace_id: int,
    workflow_id: int,
    toggle_data: WorkflowToggle,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_user),
):
    """
    Activar/desactivar un workflow.
    Solo administradores pueden cambiar el estado de workflows.
    """
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Verificar que sea administrador
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can toggle workflows"
        )
    
    return WorkflowService.toggle_workflow(db, workflow_id, workspace_id, toggle_data.is_enabled)

@router.post("/{workspace_id}/workflows/{workflow_id}/duplicate", response_model=Workflow, status_code=status.HTTP_201_CREATED)
async def duplicate_workflow(
    workspace_id: int,
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: Agent = Depends(get_current_user),
):
    """
    Duplicar un workflow existente.
    Solo administradores pueden duplicar workflows.
    """
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Verificar que sea administrador
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can duplicate workflows"
        )
    
    return WorkflowService.duplicate_workflow(db, workflow_id, workspace_id) 