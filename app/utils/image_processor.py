"""
Utilities for processing images in emails.
This module handles extraction of base64 images and conversions to file attachments.
"""

import re
import base64
import os
import uuid
from typing import List, Dict, Tuple, Optional
import logging
from pathlib import Path
from app.core.config import settings

# Configure logger
logger = logging.getLogger(__name__)

# Ensure uploads directory exists
def ensure_upload_dir(base_path: str = None) -> str:
    """
    Ensures the upload directory exists.
    """
    if not base_path:
        # Default path relative to the root of the project
        base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
    
    email_images_path = os.path.join(base_path, "email_images")
    os.makedirs(email_images_path, exist_ok=True)
    return email_images_path

def extract_base64_images(html_content: str, ticket_id: int) -> Tuple[str, List[Dict]]:
    """
    Extracts base64 encoded images from HTML content and converts them to files.
    
    Args:
        html_content: The HTML content containing base64 images
        ticket_id: The ID of the ticket associated with these images
        
    Returns:
        Tuple containing:
            - Modified HTML with image references replaced
            - List of dictionaries with extracted image information
    """
    if not html_content:
        return html_content, []
    
    # Ensure upload directory exists
    upload_dir = ensure_upload_dir()
    
    # Pattern for finding data URIs in img tags
    img_pattern = r'<img[^>]*src="data:image/([^;]+);base64,([^"]+)"[^>]*>'
    extracted_images = []
    
    # Get base URL from settings (fallback to production URL if not set)
    base_url = getattr(settings, "PUBLIC_API_URL", "https://enque-backend-production.up.railway.app")
    
    def replace_image(match):
        try:
            # Extract image type and base64 data
            img_type = match.group(1)
            base64_data = match.group(2)
            
            # Generate unique filename
            img_filename = f"ticket_{ticket_id}_{uuid.uuid4()}.{img_type}"
            img_path = os.path.join(upload_dir, img_filename)
            
            # Decode and save image
            img_bytes = base64.b64decode(base64_data)
            file_size = len(img_bytes)
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            
            # Generate absolute URL path (with domain)
            relative_path = f"/uploads/email_images/{img_filename}"
            absolute_url = f"{base_url}{relative_path}"
            
            # Get any additional attributes from the original img tag
            img_tag = match.group(0)
            width_match = re.search(r'width=["\']\s*(\d+)\s*["\']', img_tag)
            height_match = re.search(r'height=["\']\s*(\d+)\s*["\']', img_tag)
            
            # Format file size
            size_kb = file_size / 1024
            size_text = f"{size_kb:.1f} KB"
            
            # Store image info with metadata needed for attachments
            extracted_images.append({
                "filename": img_filename,
                "path": img_path,
                "url": absolute_url,
                "content_type": f"image/{img_type}",
                "size": file_size,
                "size_text": size_text,
                "is_image": True,
                "is_extracted": True
            })
            
            # Create new img tag with the same attributes but updated src with absolute URL and special class
            new_img = f'<img src="{absolute_url}" class="email-extracted-image" data-filename="{img_filename}"'
            if width_match:
                new_img += f' width="{width_match.group(1)}"'
            if height_match:
                new_img += f' height="{height_match.group(1)}"'
            
            # Add data attributes for frontend to handle as attachment
            new_img += f' data-attachment-url="{absolute_url}" data-attachment-size="{size_text}"'
            
            # Close the tag
            new_img += ' />'
            
            logger.info(f"Extracted and saved image from email to {img_path}, accessible at {absolute_url}")
            return new_img
            
        except Exception as e:
            logger.error(f"Error processing image in email: {str(e)}")
            # Return a placeholder or the original
            return f'<img src="{base_url}/static/broken-image.png" alt="Image processing error" />'
    
    # Replace all base64 images in the HTML
    processed_html = re.sub(img_pattern, replace_image, html_content)
    
    return processed_html, extracted_images 