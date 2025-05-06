import os
import uuid
from pathlib import Path
from typing import Dict

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Request

from app.core.config import settings

router = APIRouter()

# Define the base directory for uploads relative to the backend app directory
# Ensure this path aligns with your static files mounting in main.py
UPLOAD_DIR = Path("static/uploads/images")
# Create the directory if it doesn't exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 5 * 1024 * 1024 # 5 MB limit
ALLOWED_MIME_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"]

@router.post("/image", response_model=Dict[str, str])
async def upload_image(
    request: Request, # Inject Request to build absolute URL
    file: UploadFile = File(...)
) -> Dict[str, str]:
    """
    Uploads an image file, saves it, and returns its public URL.
    """
    # 1. Validate file type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    # 2. Validate file size (check content-length header if available, or read chunks)
    # Note: Reading the whole file into memory to check size can be inefficient for large files.
    # A more robust solution might involve streaming and checking size incrementally.
    # For simplicity here, we'll read the file content.
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the limit of {MAX_FILE_SIZE / 1024 / 1024} MB"
        )
    await file.seek(0) # Reset file pointer after reading

    # 3. Generate unique filename
    file_extension = Path(file.filename).suffix if file.filename else ".png" # Default extension
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    save_path = UPLOAD_DIR / unique_filename

    # 4. Save the file asynchronously
    try:
        async with aiofiles.open(save_path, "wb") as out_file:
            while chunk := await file.read(1024 * 1024): # Read in 1MB chunks
                await out_file.write(chunk)
    except Exception as e:
        # Log the error details
        print(f"Error saving file: {e}") # Replace with proper logging
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save file."
        )
    finally:
        await file.close()

    # 5. Construct the public URL
    # Assuming static files are mounted at "/static" in main.py
    # and UPLOAD_DIR is relative to the 'static' mount point's source directory
    # Example: if static is mounted from 'backend/static', URL is /static/uploads/images/...
    # If running behind a proxy, use request.base_url, otherwise construct manually if needed.

    # Construct relative path from the static mount point
    relative_path = save_path.relative_to(Path("static"))
    # Use POSIX path separators for URL
    file_url = f"/static/{relative_path.as_posix()}"

    # Optional: Construct absolute URL using request base_url
    # base_url = str(request.base_url)
    # absolute_file_url = f"{base_url.strip('/')}{file_url}"
    # Use relative URL for simplicity, frontend can prepend base URL if needed

    return {"url": file_url}
