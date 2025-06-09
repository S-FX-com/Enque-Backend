import os
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Request

from app.services.s3_service import get_s3_service, S3Service
from app.utils.logger import logger

router = APIRouter()

# File size and type constraints
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit (increased from 5MB)
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"]
ALLOWED_DOCUMENT_TYPES = [
    "application/pdf", "application/msword", 
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel", 
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain", "text/csv"
]
ALL_ALLOWED_TYPES = ALLOWED_IMAGE_TYPES + ALLOWED_DOCUMENT_TYPES

@router.post("/image", response_model=Dict[str, str])
async def upload_image(
    file: UploadFile = File(...),
    s3_service: S3Service = Depends(get_s3_service)
) -> Dict[str, str]:
    """
    Upload an image file to S3 and return its public URL.
    """
    logger.info(f"🖼️ Image upload endpoint called with file: {file.filename}")
    
    # Validate file type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        logger.error(f"❌ Invalid file type: {file.content_type}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_IMAGE_TYPES)}"
        )

    try:
        # Upload to S3 in images folder
        file_url = await s3_service.upload_from_upload_file(
            upload_file=file,
            folder="images",
            max_size=MAX_FILE_SIZE
        )
        
        logger.info(f"✅ Image uploaded successfully: {file_url}")
        return {"url": file_url}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error in image upload: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading image: {str(e)}"
        )

@router.post("/file", response_model=Dict[str, str])
async def upload_file(
    file: UploadFile = File(...),
    s3_service: S3Service = Depends(get_s3_service)
) -> Dict[str, str]:
    """
    Upload any allowed file type to S3 and return its public URL.
    """
    logger.info(f"📎 File upload endpoint called with file: {file.filename}")
    
    # Validate file type
    if file.content_type not in ALL_ALLOWED_TYPES:
        logger.error(f"❌ Invalid file type: {file.content_type}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed types: {', '.join(ALL_ALLOWED_TYPES)}"
        )

    try:
        # Determine folder based on file type
        folder = "images" if file.content_type in ALLOWED_IMAGE_TYPES else "documents"
        logger.info(f"📁 Using folder: {folder}")
        
        # Upload to S3
        file_url = await s3_service.upload_from_upload_file(
            upload_file=file,
            folder=folder,
            max_size=MAX_FILE_SIZE
        )
        
        logger.info(f"✅ File uploaded successfully: {file_url}")
        return {"url": file_url, "type": folder}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error in file upload: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading file: {str(e)}"
        )

@router.post("/multiple", response_model=List[Dict[str, str]])
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    s3_service: S3Service = Depends(get_s3_service)
) -> List[Dict[str, str]]:
    """
    Upload multiple files to S3 and return their public URLs.
    """
    logger.info(f"📦 Multiple files upload endpoint called with {len(files)} files")
    
    if len(files) > 10:  # Limit number of files
        logger.error(f"❌ Too many files: {len(files)} > 10")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot upload more than 10 files at once"
        )
    
    results = []
    
    for i, file in enumerate(files):
        logger.info(f"📎 Processing file {i+1}/{len(files)}: {file.filename}")
        try:
            # Validate file type
            if file.content_type not in ALL_ALLOWED_TYPES:
                logger.warning(f"❌ Invalid file type for {file.filename}: {file.content_type}")
                results.append({
                    "filename": file.filename,
                    "error": f"Invalid file type: {file.content_type}"
                })
                continue
            
            # Determine folder based on file type
            folder = "images" if file.content_type in ALLOWED_IMAGE_TYPES else "documents"
            
            # Upload to S3
            file_url = await s3_service.upload_from_upload_file(
                upload_file=file,
                folder=folder,
                max_size=MAX_FILE_SIZE
            )
            
            results.append({
                "filename": file.filename,
                "url": file_url,
                "type": folder
            })
            logger.info(f"✅ File {file.filename} uploaded successfully")
            
        except Exception as e:
            logger.error(f"❌ Error uploading {file.filename}: {str(e)}")
            results.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    logger.info(f"📦 Multiple upload completed. Success: {len([r for r in results if 'url' in r])}/{len(files)}")
    return results

@router.post("/conversation-html", response_model=Dict[str, str])
async def upload_conversation_html(
    html_content: str,
    filename: str,
    s3_service: S3Service = Depends(get_s3_service)
) -> Dict[str, str]:
    """
    Upload HTML content (like ticket conversations) to S3.
    """
    logger.info(f"📄 HTML upload endpoint called: {filename}")
    
    try:
        file_url = s3_service.upload_html_content(
            html_content=html_content,
            filename=filename,
            folder="conversations"
        )
        
        logger.info(f"✅ HTML uploaded successfully: {file_url}")
        return {"url": file_url}
        
    except Exception as e:
        logger.error(f"❌ Error uploading HTML: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading HTML content: {str(e)}"
        )

@router.get("/list/{folder}")
async def list_files(
    folder: str,
    limit: int = 100,
    s3_service: S3Service = Depends(get_s3_service)
) -> Dict[str, List[Dict]]:
    """
    List files in a specific S3 folder.
    """
    logger.info(f"📋 List files endpoint called: folder={folder}, limit={limit}")
    
    try:
        files = s3_service.list_files(folder=folder, limit=limit)
        logger.info(f"✅ Listed {len(files)} files from folder: {folder}")
        return {"files": files}
        
    except Exception as e:
        logger.error(f"❌ Error listing files: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing files: {str(e)}"
        )

@router.delete("/file/{folder}/{filename}")
async def delete_file(
    folder: str,
    filename: str,
    s3_service: S3Service = Depends(get_s3_service)
) -> Dict[str, str]:
    """
    Delete a file from S3.
    """
    logger.info(f"🗑️ Delete file endpoint called: {folder}/{filename}")
    
    try:
        s3_key = f"{folder}/{filename}"
        success = s3_service.delete_file(s3_key)
        
        if success:
            logger.info(f"✅ File deleted successfully: {s3_key}")
            return {"message": f"File {filename} deleted successfully"}
        else:
            logger.error(f"❌ File not found or could not be deleted: {s3_key}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File {filename} not found or could not be deleted"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting file: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting file: {str(e)}"
        )
