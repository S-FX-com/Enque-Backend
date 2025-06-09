import os
import uuid
import mimetypes
from typing import Optional, Dict, List
from io import BytesIO
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.config import Config
from fastapi import HTTPException, UploadFile
import logging

logger = logging.getLogger(__name__)

class S3Service:
    def __init__(self):
        """Initialize S3 service with credentials from environment variables"""
        logger.info("🔧 Initializing S3Service...")
        
        # TEMPORARY: Hardcoded credentials for debugging
        # TODO: Switch back to environment variables once Railway issue is resolved
        self.aws_access_key_id = "AKIAQ3EGRIILJHGBQJOZ"
        self.aws_secret_access_key = "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"
        self.aws_region = "us-east-2"
        self.bucket_name = "enque"
        
        # Fallback to environment variables if needed
        if not self.aws_access_key_id:
            self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        if not self.aws_secret_access_key:
            self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        if not self.aws_region:
            self.aws_region = os.getenv("AWS_REGION", "us-east-2")
        if not self.bucket_name:
            self.bucket_name = os.getenv("AWS_S3_BUCKET", "enque")
        
        logger.info(f"📋 S3 Configuration:")
        logger.info(f"   - AWS Region: {self.aws_region}")
        logger.info(f"   - S3 Bucket: {self.bucket_name}")
        
        # Safe logging of credentials
        if self.aws_access_key_id:
            logger.info(f"   - Access Key ID: {self.aws_access_key_id[:10]}...{self.aws_access_key_id[-4:]}")
        else:
            logger.error("   - Access Key ID: NOT SET")
            
        if self.aws_secret_access_key:
            logger.info("   - Secret Key: ***")
        else:
            logger.error("   - Secret Key: NOT SET")
        
        if not all([self.aws_access_key_id, self.aws_secret_access_key]):
            error_msg = "❌ AWS credentials not found in environment variables"
            logger.error(error_msg)
            logger.error("Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in Railway variables")
            raise ValueError(error_msg)
        
        # Initialize S3 client with optimized config for speed
        try:
            logger.info("🔌 Creating optimized S3 client...")
            
            # Optimized configuration for speed
            config = Config(
                retries={'max_attempts': 2, 'mode': 'adaptive'},  # Fewer retries for speed
                max_pool_connections=10,  # More concurrent connections
                region_name=self.aws_region
            )
            
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.aws_region,
                config=config
            )
            logger.info("✅ Optimized S3 client created successfully")
        except Exception as e:
            logger.error(f"❌ Error creating S3 client: {e}")
            raise
        
        # Test connection
        self._test_connection()
    
    def _test_connection(self):
        """Test S3 connection"""
        try:
            logger.info("🔍 Testing S3 connection...")
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"✅ Successfully connected to S3 bucket: {self.bucket_name}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                error_msg = f"❌ S3 bucket '{self.bucket_name}' not found"
                logger.error(error_msg)
                raise ValueError(error_msg)
            else:
                error_msg = f"❌ Error connecting to S3: {e}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        except NoCredentialsError:
            error_msg = "❌ AWS credentials not found or invalid"
            logger.error(error_msg)
            raise ValueError(error_msg)
        except Exception as e:
            error_msg = f"❌ Unexpected error testing S3 connection: {e}"
            logger.error(error_msg)
            raise
    
    def upload_file(
        self, 
        file_content: bytes, 
        filename: str, 
        folder: str = "", 
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload file to S3 and return public URL
        
        Args:
            file_content: File content as bytes
            filename: Original filename
            folder: S3 folder/prefix (e.g., 'images/', 'attachments/')
            content_type: MIME type of the file
            
        Returns:
            Public URL of uploaded file
        """
        try:
            logger.info(f"📤 Starting S3 upload:")
            logger.info(f"   - Original filename: {filename}")
            logger.info(f"   - File size: {len(file_content)} bytes")
            logger.info(f"   - Folder: {folder}")
            logger.info(f"   - Content type: {content_type}")
            
            # Generate unique filename
            file_extension = os.path.splitext(filename)[1]
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            
            # Create S3 key (path)
            s3_key = f"{folder.rstrip('/')}/{unique_filename}" if folder else unique_filename
            logger.info(f"   - S3 key: {s3_key}")
            
            # Determine content type if not provided
            if not content_type:
                content_type, _ = mimetypes.guess_type(filename)
                if not content_type:
                    content_type = "application/octet-stream"
            
            logger.info(f"   - Final content type: {content_type}")
            
            # Upload to S3
            logger.info("🚀 Uploading to S3...")
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_content,
                ContentType=content_type
            )
            
            # Return public URL
            public_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
            
            logger.info(f"✅ File uploaded successfully to S3!")
            logger.info(f"   - Public URL: {public_url}")
            return public_url
            
        except ClientError as e:
            error_msg = f"❌ AWS S3 ClientError: {e.response['Error']['Code']} - {e.response['Error']['Message']}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")
        except Exception as e:
            error_msg = f"❌ Unexpected error uploading file to S3: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")
    
    async def upload_from_upload_file(
        self, 
        upload_file: UploadFile, 
        folder: str = "",
        max_size: int = 10 * 1024 * 1024  # 10MB default
    ) -> str:
        """
        Upload from FastAPI UploadFile to S3
        
        Args:
            upload_file: FastAPI UploadFile object
            folder: S3 folder/prefix
            max_size: Maximum file size in bytes
            
        Returns:
            Public URL of uploaded file
        """
        try:
            logger.info(f"📁 Processing UploadFile:")
            logger.info(f"   - Filename: {upload_file.filename}")
            logger.info(f"   - Content type: {upload_file.content_type}")
            logger.info(f"   - Folder: {folder}")
            logger.info(f"   - Max size: {max_size / 1024 / 1024:.1f}MB")
            
            # Read file content
            logger.info("📖 Reading file content...")
            file_content = await upload_file.read()
            actual_size = len(file_content)
            logger.info(f"   - Actual file size: {actual_size} bytes ({actual_size / 1024:.1f} KB)")
            
            # Validate file size
            if actual_size > max_size:
                error_msg = f"❌ File size {actual_size / 1024 / 1024:.1f}MB exceeds maximum of {max_size / 1024 / 1024:.1f}MB"
                logger.error(error_msg)
                raise HTTPException(
                    status_code=413,
                    detail=error_msg
                )
            
            # Upload to S3
            return self.upload_file(
                file_content=file_content,
                filename=upload_file.filename or "unnamed_file",
                folder=folder,
                content_type=upload_file.content_type
            )
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"❌ Error processing upload file: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
    
    def upload_html_content(self, html_content: str, filename: str, folder: str = "conversations") -> str:
        """
        Upload HTML content (like ticket conversations) to S3
        
        Args:
            html_content: HTML content as string
            filename: Filename for the HTML file
            folder: S3 folder/prefix
            
        Returns:
            Public URL of uploaded HTML file
        """
        try:
            logger.info(f"📄 Uploading HTML content:")
            logger.info(f"   - Filename: {filename}")
            logger.info(f"   - Content length: {len(html_content)} characters")
            logger.info(f"   - Folder: {folder}")
            
            # Convert HTML string to bytes
            html_bytes = html_content.encode('utf-8')
            
            # Ensure filename has .html extension
            if not filename.endswith('.html'):
                filename += '.html'
            
            return self.upload_file(
                file_content=html_bytes,
                filename=filename,
                folder=folder,
                content_type="text/html; charset=utf-8"
            )
            
        except Exception as e:
            error_msg = f"❌ Error uploading HTML content: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
    
    def delete_file(self, s3_key: str) -> bool:
        """
        Delete file from S3
        
        Args:
            s3_key: S3 key (path) of the file to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"🗑️ Deleting file from S3: {s3_key}")
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"✅ Successfully deleted file from S3: {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"❌ Error deleting file from S3: {e}")
            return False
    
    def get_file_url(self, s3_key: str) -> str:
        """
        Get public URL for a file in S3
        
        Args:
            s3_key: S3 key (path) of the file
            
        Returns:
            Public URL of the file
        """
        return f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
    
    def list_files(self, folder: str = "", limit: int = 100) -> List[Dict]:
        """
        List files in S3 bucket or folder
        
        Args:
            folder: S3 folder/prefix to list
            limit: Maximum number of files to return
            
        Returns:
            List of file information dictionaries
        """
        try:
            logger.info(f"📋 Listing files in S3:")
            logger.info(f"   - Folder: {folder}")
            logger.info(f"   - Limit: {limit}")
            
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=folder,
                MaxKeys=limit
            )
            
            files = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    files.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat(),
                        'url': self.get_file_url(obj['Key'])
                    })
            
            logger.info(f"✅ Found {len(files)} files in S3")
            return files
            
        except ClientError as e:
            error_msg = f"❌ Error listing files from S3: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
    
    def should_store_html_in_s3(self, html_content: str) -> bool:
        """
        Determine if HTML content should be stored in S3 based on size and complexity
        
        MODIFIED: Now stores ALL comments in S3 regardless of size or complexity
        
        Args:
            html_content: HTML content to analyze
            
        Returns:
            True if should be stored in S3, False otherwise
        """
        if not html_content:
            logger.info("📝 Empty content - skipping S3")
            return False
            
        # MODIFICATION: Store ALL comments in S3 regardless of size or complexity
        content_length = len(html_content)
        logger.info(f"📤 Content length: {content_length} chars - ALWAYS storing in S3")
        return True
        
        # ORIGINAL CONDITIONS (commented out):
        # # 1. Large content (> 2KB)
        # if content_length > 2000:
        #     logger.info(f"📏 Content length {content_length} > 2000 chars - recommending S3")
        #     return True
        #     
        # # 2. Contains email signatures (multiple style tags)
        # style_count = html_content.count('<style')
        # if style_count > 2:
        #     logger.info(f"🎨 Contains {style_count} style tags - recommending S3")
        #     return True
        #     
        # # 3. Contains email signatures patterns
        # signature_patterns = [
        #     'elementToProof',
        #     'MsoNormal',
        #     'newoldstamp.com',
        #     'data-outlook-trace',
        #     'x_Signature'
        # ]
        # 
        # pattern_matches = sum(1 for pattern in signature_patterns if pattern in html_content)
        # if pattern_matches >= 2:
        #     logger.info(f"📧 Contains {pattern_matches} email signature patterns - recommending S3")
        #     return True
        #     
        # # 4. Contains inline styles (indication of complex email content)
        # if html_content.count('style=') > 10:
        #     logger.info(f"💄 Contains many inline styles - recommending S3")
        #     return True
        #     
        # return False
    
    def store_comment_html(self, comment_id: int, html_content: str) -> str:
        """
        Store comment HTML content in S3 and return URL
        
        Args:
            comment_id: ID of the comment
            html_content: HTML content to store
            
        Returns:
            S3 URL of stored HTML file
        """
        try:
            logger.info(f"📄 Storing comment {comment_id} HTML in S3")
            
            # Generate filename
            filename = f"comment-{comment_id}.html"
            
            # Use existing upload_html_content method
            s3_url = self.upload_html_content(
                html_content=html_content,
                filename=filename,
                folder="comments"
            )
            
            logger.info(f"✅ Comment {comment_id} HTML stored in S3: {s3_url}")
            return s3_url
            
        except Exception as e:
            logger.error(f"❌ Error storing comment {comment_id} HTML in S3: {str(e)}")
            raise
    
    def get_comment_html(self, s3_url: str) -> Optional[str]:
        """
        Retrieve comment HTML content from S3 - Optimized for speed
        
        Args:
            s3_url: S3 URL of the HTML file
            
        Returns:
            HTML content as string, or None if error
        """
        try:
            logger.info(f"📥 Fast retrieving comment HTML from S3: {s3_url}")
            
            # Download file content with optimized timeout
            file_content = self._download_file_from_s3(s3_url)
            if not file_content:
                return None
                
            # Convert bytes to string
            html_content = file_content.decode('utf-8')
            logger.info(f"✅ Fast retrieved {len(html_content)} characters from S3")
            return html_content
            
        except Exception as e:
            logger.error(f"❌ Error retrieving comment HTML from S3: {str(e)}")
            return None

    def _download_file_from_s3(self, s3_url: str) -> Optional[bytes]:
        """
        Download file content from S3 using URL - Optimized for speed
        
        Args:
            s3_url: S3 URL of the file
            
        Returns:
            File content as bytes, or None if error
        """
        try:
            # Extract S3 key from URL
            # URL format: https://bucket.s3.region.amazonaws.com/key
            if not s3_url.startswith(f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/"):
                logger.error(f"❌ Invalid S3 URL format: {s3_url}")
                return None
                
            s3_key = s3_url.replace(f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/", "")
            logger.info(f"📥 Fast downloading file from S3: {s3_key}")
            
            # Download file from S3 with optimized config
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            file_content = response['Body'].read()
            
            logger.info(f"✅ Fast downloaded {len(file_content)} bytes from S3")
            return file_content
            
        except ClientError as e:
            logger.error(f"❌ Error downloading file from S3: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error downloading file from S3: {e}")
            return None

# Global S3 service instance
s3_service = None

def get_s3_service() -> S3Service:
    """Dependency to get S3 service instance"""
    global s3_service
    if s3_service is None:
        logger.info("🏗️ Creating new S3Service instance...")
        s3_service = S3Service()
    return s3_service 