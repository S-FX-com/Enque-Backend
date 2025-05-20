from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.responses import StreamingResponse # O Response si StreamingResponse no es adecuada para bytes directos
from sqlalchemy.orm import Session
import io # Para convertir bytes a un stream si es necesario con StreamingResponse
import urllib.parse # Para codificar el nombre del archivo para Content-Disposition
import unicodedata # Para normalizar y crear un nombre de archivo ASCII
from typing import List

from app.api import dependencies # Para get_db
from app.models.ticket_attachment import TicketAttachment
from app.schemas.ticket_attachment import TicketAttachmentSchema
from app.utils.logger import logger

router = APIRouter()

@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: int,
    db: Session = Depends(dependencies.get_db)
):
    """
    Downloads a ticket attachment by its ID.
    """
    logger.info(f"Attempting to download attachment with ID: {attachment_id}")
    db_attachment = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()

    if not db_attachment:
        logger.warning(f"Attachment with ID: {attachment_id} not found.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    if not db_attachment.content_bytes:
        logger.error(f"Attachment with ID: {attachment_id} found but has no content_bytes.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Attachment content not available")

    logger.info(f"Streaming attachment ID: {attachment_id}, Name: {db_attachment.file_name}, Content-Type: {db_attachment.content_type}")
    
    # Convert bytes to a BytesIO stream for StreamingResponse
    stream = io.BytesIO(db_attachment.content_bytes)
    
    # Preparar el nombre de archivo para la cabecera Content-Disposition
    file_name = db_attachment.file_name
    
    # Crear una versión ASCII segura del nombre de archivo para el parámetro 'filename'
    ascii_filename = (
        unicodedata.normalize('NFKD', file_name)
        .encode('ascii', 'ignore')
        .decode('ascii')
    )
    if not ascii_filename: # Si el nombre se vuelve vacío, usar un fallback genérico
        ascii_filename = "downloaded_file"

    # Codificar el nombre de archivo original para el parámetro 'filename*' (UTF-8)
    utf8_filename_encoded = urllib.parse.quote(file_name)

    headers = {
        "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{utf8_filename_encoded}"
    }
    
    return StreamingResponse(
        stream, 
        media_type=db_attachment.content_type,
        headers=headers
    )

@router.post("/attachments/upload-multiple", response_model=List[TicketAttachmentSchema])
async def upload_multiple_attachments(
    files: List[UploadFile] = File(...),
    db: Session = Depends(dependencies.get_db),
    current_agent = Depends(dependencies.get_current_active_user)
):
    """
    Upload multiple attachments and return their info.
    These attachments will be temporarily stored without a comment_id.
    When creating a comment, the frontend will pass the attachment IDs to associate.
    """
    logger.info(f"Uploading multiple attachments from agent ID: {current_agent.id}")
    
    result = []
    for file in files:
        try:
            # Read file content
            content = await file.read()
            file_size = len(content)
            
            # Create temporary attachment record (without comment_id for now)
            # Use a placeholder comment_id (will be updated when comment is created)
            from app.models.comment import Comment
            # Find or create a placeholder comment for temporary attachments
            placeholder_comment = db.query(Comment).filter(
                Comment.agent_id == current_agent.id,
                Comment.is_private == True,
                Comment.content == "TEMP_ATTACHMENT_PLACEHOLDER"
            ).first()
            
            if not placeholder_comment:
                from app.models.task import Task
                # Find any task to associate with this placeholder (it doesn't matter which one)
                # This is just to satisfy the database constraints
                any_task = db.query(Task).first()
                if not any_task:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot create placeholder for attachments - no tasks in system"
                    )
                
                placeholder_comment = Comment(
                    ticket_id=any_task.id,
                    agent_id=current_agent.id,
                    workspace_id=current_agent.workspace_id,
                    content="TEMP_ATTACHMENT_PLACEHOLDER",
                    is_private=True
                )
                db.add(placeholder_comment)
                db.flush()  # Get the ID before creating attachments
            
            # Create attachment
            db_attachment = TicketAttachment(
                comment_id=placeholder_comment.id,
                file_name=file.filename,
                content_type=file.content_type or "application/octet-stream",
                file_size=file_size,
                content_bytes=content
            )
            db.add(db_attachment)
            db.flush()  # To get ID
            
            # Add to result
            result.append(TicketAttachmentSchema.model_validate(db_attachment))
            
        except Exception as e:
            logger.error(f"Error uploading file {file.filename}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error uploading file: {str(e)}"
            )
    
    db.commit()
    return result

@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: int,
    db: Session = Depends(dependencies.get_db),
    current_agent = Depends(dependencies.get_current_active_user)
):
    """
    Delete a temporary attachment by ID.
    """
    db_attachment = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
    
    if not db_attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )
    
    # Check if the attachment is in a temporary state
    comment = db.query(Comment).filter(Comment.id == db_attachment.comment_id).first()
    if not comment or comment.content != "TEMP_ATTACHMENT_PLACEHOLDER":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete temporary attachments"
        )
    
    # Delete attachment
    db.delete(db_attachment)
    db.commit()
    
    return {"success": True, "message": "Attachment deleted"} 