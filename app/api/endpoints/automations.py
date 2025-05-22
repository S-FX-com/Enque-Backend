from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_active_user, check_workspace_access
from app.models.user import User
from app.schemas.automation import (
    AutomationCreate,
    AutomationUpdate,
    AutomationInDB,
    AutomationToggleEnable,
    AutomationRunResponse,
)
from app.services.automation_service import (
    create_automation,
    get_automation_by_id,
    get_automations_by_workspace,
    update_automation,
    delete_automation,
    toggle_automation_status,
    run_automation,
)

router = APIRouter()


@router.get("/{workspace_id}/automations", response_model=List[AutomationInDB])
async def read_automations(
    workspace_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get all automations for a workspace."""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    return get_automations_by_workspace(db, workspace_id)


@router.get("/{workspace_id}/automations/{automation_id}", response_model=AutomationInDB)
async def read_automation(
    workspace_id: int,
    automation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get a specific automation by ID."""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    automation = get_automation_by_id(db, workspace_id, automation_id)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Automation with ID {automation_id} not found",
        )
    return automation


@router.post("/{workspace_id}/automations", response_model=AutomationInDB, status_code=status.HTTP_201_CREATED)
async def create_new_automation(
    workspace_id: int,
    automation_data: AutomationCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new automation for a workspace."""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Solo administradores y gestores pueden crear automatizaciones
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create automations",
        )
    
    return create_automation(db, workspace_id, automation_data)


@router.put("/{workspace_id}/automations/{automation_id}", response_model=AutomationInDB)
async def update_existing_automation(
    workspace_id: int,
    automation_id: int,
    automation_data: AutomationUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update an existing automation."""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Solo administradores y gestores pueden actualizar automatizaciones
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to update automations",
        )
    
    automation = get_automation_by_id(db, workspace_id, automation_id)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Automation with ID {automation_id} not found",
        )
    
    return update_automation(db, automation, automation_data)


@router.delete("/{workspace_id}/automations/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_existing_automation(
    workspace_id: int,
    automation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete an automation."""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Solo administradores y gestores pueden eliminar automatizaciones
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to delete automations",
        )
    
    automation = get_automation_by_id(db, workspace_id, automation_id)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Automation with ID {automation_id} not found",
        )
    
    delete_automation(db, automation)
    return None


@router.put("/{workspace_id}/automations/{automation_id}/toggle", response_model=AutomationInDB)
async def toggle_automation_enabled(
    workspace_id: int,
    automation_id: int,
    toggle_data: AutomationToggleEnable,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Toggle the enabled status of an automation."""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Solo administradores y gestores pueden cambiar el estado de las automatizaciones
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to toggle automation status",
        )
    
    automation = get_automation_by_id(db, workspace_id, automation_id)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Automation with ID {automation_id} not found",
        )
    
    return toggle_automation_status(db, automation, toggle_data.is_enabled)


@router.post("/{workspace_id}/automations/{automation_id}/run", response_model=AutomationRunResponse)
async def run_specific_automation(
    workspace_id: int,
    automation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Run a specific automation immediately (for testing purposes)."""
    # Verificar acceso al workspace
    check_workspace_access(current_user, workspace_id)
    
    # Solo administradores y gestores pueden ejecutar automatizaciones manualmente
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to run automations",
        )
    
    automation = get_automation_by_id(db, workspace_id, automation_id)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Automation with ID {automation_id} not found",
        )
    
    # Si la automatización está deshabilitada, no permitir su ejecución manual
    if not automation.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot run a disabled automation",
        )
    
    result = run_automation(db, automation, current_user)
    return result 