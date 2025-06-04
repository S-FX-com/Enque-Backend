"""
Utilities for processing images in emails.
This module handles extraction of base64 images and conversions to file attachments.
"""

import re
import base64
import uuid
from typing import List, Dict, Tuple, Optional
import logging
from app.core.config import settings
from app.services.s3_service import get_s3_service

# Configure logger
logger = logging.getLogger(__name__)

def extract_base64_images(html_content: str, ticket_id: int) -> Tuple[str, List[Dict]]:
    """
    Extracts base64 encoded images from HTML content and uploads them to S3.
    
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
    
    # Get S3 service instance
    s3_service = get_s3_service()
    
    # Pattern for finding data URIs in img tags
    img_pattern = r'<img[^>]*src="data:image/([^;]+);base64,([^"]+)"[^>]*>'
    extracted_images = []
    
    def replace_image(match):
        try:
            # Extract image type and base64 data
            img_type = match.group(1)
            base64_data = match.group(2)
            
            # Generate unique filename
            img_filename = f"ticket_{ticket_id}_{uuid.uuid4()}.{img_type}"
            
            # Decode image
            img_bytes = base64.b64decode(base64_data)
            file_size = len(img_bytes)
            
            # Upload to S3
            s3_url = s3_service.upload_file(
                file_content=img_bytes,
                filename=img_filename,
                folder="email_images",
                content_type=f"image/{img_type}"
            )
            
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
                "url": s3_url,
                "content_type": f"image/{img_type}",
                "size": file_size,
                "size_text": size_text,
                "is_image": True,
                "is_extracted": True,
                "s3_url": s3_url  # Include S3 URL for consistency
            })
            
            # Create new img tag with the same attributes but updated src with S3 URL and special class
            new_img = f'<img src="{s3_url}" class="email-extracted-image" data-filename="{img_filename}"'
            if width_match:
                new_img += f' width="{width_match.group(1)}"'
            if height_match:
                new_img += f' height="{height_match.group(1)}"'
            
            # Add data attributes for frontend to handle as attachment
            new_img += f' data-attachment-url="{s3_url}" data-attachment-size="{size_text}"'
            
            # Close the tag
            new_img += ' />'
            
            logger.info(f"Extracted and uploaded image from email to S3: {s3_url}")
            return new_img
            
        except Exception as e:
            logger.error(f"Error processing image in email: {str(e)}")
            # Return a placeholder or the original
            return f'<img src="https://via.placeholder.com/100x100?text=Error" alt="Image processing error" />'
    
    # Replace all base64 images in the HTML
    processed_html = re.sub(img_pattern, replace_image, html_content)
    
    return processed_html, extracted_images

# Legacy function for backward compatibility
def ensure_upload_dir(base_path: str = None) -> str:
    """
    Legacy function for backward compatibility.
    Now returns a message indicating S3 usage.
    """
    logger.warning("ensure_upload_dir is deprecated. Images are now stored in S3.")
    return "S3_STORAGE_USED" 