from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.responses import RedirectResponse # Para redireccionar a S3 URLs
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import urllib.parse # Para codificar el nombre del archivo para Content-Disposition
import unicodedata # Para normalizar y crear un nombre de archivo ASCII
from typing import List

from app.api import dependencies # Para get_db
from app.models.ticket_attachment import TicketAttachment
from app.schemas.ticket_attachment import TicketAttachmentSchema
from app.utils.logger import logger
from app.services.s3_service import get_s3_service, S3Service

router = APIRouter()

@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(dependencies.get_db)
):
    """
    Downloads a ticket attachment by its ID by redirecting to S3 URL.
    """
    logger.info(f"Attempting to download attachment with ID: {attachment_id}")
    stmt = select(TicketAttachment).where(TicketAttachment.id == attachment_id)
    result = await db.execute(stmt)
    db_attachment = result.scalar_one_or_none()

    if not db_attachment:
        logger.warning(f"Attachment with ID: {attachment_id} not found.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    # Check if we have an S3 URL (new system) or content_bytes (old system)
    if hasattr(db_attachment, 's3_url') and db_attachment.s3_url:
        # New S3 system - redirect to S3 URL
        logger.info(f"Redirecting to S3 URL for attachment ID: {attachment_id}")
        return RedirectResponse(url=db_attachment.s3_url)
    elif db_attachment.content_bytes:
        # Old system - serve from database (legacy support)
        logger.info(f"Serving from database for attachment ID: {attachment_id}")
        from fastapi.responses import StreamingResponse
        import io
        
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
    else:
        logger.error(f"Attachment with ID: {attachment_id} found but has no content.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Attachment content not available")

@router.post("/attachments/upload-multiple", response_model=List[TicketAttachmentSchema])
async def upload_multiple_attachments(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(dependencies.get_db),
    current_agent = Depends(dependencies.get_current_active_user),
    s3_service: S3Service = Depends(get_s3_service)
):
    """
    Upload multiple attachments to S3 and return their info.
    These attachments will be temporarily stored without a comment_id.
    When creating a comment, the frontend will pass the attachment IDs to associate.
    """
    logger.info(f"Uploading multiple attachments to S3 from agent ID: {current_agent.id}")
    
    result = []
    for file in files:
        try:
            # Get file size BEFORE uploading to S3
            file_content = await file.read()
            file_size = len(file_content)
            await file.seek(0)  # Reset file pointer for S3 upload
            
            logger.info(f"Processing file: {file.filename}, size: {file_size} bytes, content_type: {file.content_type}")
            
            # Upload to S3
            s3_url = await s3_service.upload_from_upload_file(
                upload_file=file,
                folder="attachments",
                max_size=50 * 1024 * 1024  # 50MB limit for attachments
            )
            
            logger.info(f"Successfully uploaded {file.filename} to S3: {s3_url}")
            
            # Create temporary attachment record (without comment_id for now)
            # Use a placeholder comment_id (will be updated when comment is created)
            from app.models.comment import Comment
            # Find or create a placeholder comment for temporary attachments
            stmt = select(Comment).where(
                Comment.agent_id == current_agent.id,
                Comment.is_private == True,
                Comment.content == "TEMP_ATTACHMENT_PLACEHOLDER"
            )
            query_result = await db.execute(stmt)
            placeholder_comment = query_result.scalar_one_or_none()
            
            if not placeholder_comment:
                from app.models.task import Task
                # Find any task to associate with this placeholder (it doesn't matter which one)
                # This is just to satisfy the database constraints
                stmt = select(Task)
                query_result = await db.execute(stmt)
                any_task = query_result.scalars().first()
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
                await db.flush()  # Get the ID before creating attachments
            
            # Create attachment record with S3 URL
            db_attachment = TicketAttachment(
                comment_id=placeholder_comment.id,
                file_name=file.filename,
                content_type=file.content_type or "application/octet-stream",
                file_size=file_size,
                s3_url=s3_url  # Store S3 URL instead of content_bytes
            )
            db.add(db_attachment)
            await db.flush()  # To get ID
            await db.refresh(db_attachment)  # Load all attributes including created_at

            logger.info(f"Created attachment record: ID={db_attachment.id}, size={db_attachment.file_size}, s3_url={db_attachment.s3_url}")

            # Add to result
            result.append(TicketAttachmentSchema.model_validate(db_attachment))
            
        except Exception as e:
            logger.error(f"Error uploading file {file.filename}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error uploading file: {str(e)}"
            )

    await db.commit()
    return result

@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(dependencies.get_db),
    current_agent = Depends(dependencies.get_current_active_user),
    s3_service: S3Service = Depends(get_s3_service)
):
    """
    Delete a temporary attachment by ID (both from database and S3).
    """
    stmt = select(TicketAttachment).where(TicketAttachment.id == attachment_id)
    result = await db.execute(stmt)
    db_attachment = result.scalar_one_or_none()
    
    if not db_attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )
    
    # Check if the attachment is in a temporary state
    from app.models.comment import Comment
    stmt = select(Comment).where(Comment.id == db_attachment.comment_id)
    result = await db.execute(stmt)
    comment = result.scalar_one_or_none()
    if not comment or comment.content != "TEMP_ATTACHMENT_PLACEHOLDER":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete temporary attachments"
        )
    
    # Delete from S3 if it exists
    if hasattr(db_attachment, 's3_url') and db_attachment.s3_url:
        try:
            # Extract S3 key from URL
            s3_key = db_attachment.s3_url.split('amazonaws.com/')[-1]
            s3_service.delete_file(s3_key)
            logger.info(f"Deleted attachment from S3: {s3_key}")
        except Exception as e:
            logger.warning(f"Failed to delete attachment from S3: {e}")
    
    # Delete attachment from database
    await db.delete(db_attachment)
    await db.commit()

    return {"success": True, "message": "Attachment deleted"} 