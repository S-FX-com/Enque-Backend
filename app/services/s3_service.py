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
        logger.debug("🔧 Initializing S3Service...")
        # TODO: Switch back to environment variables once Railway issue is resolved
        self.aws_access_key_id = "AKIAQ3EGRIILJHGBQJOZ"
        self.aws_secret_access_key = "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"
        self.aws_region = "us-east-2"
        self.bucket_name = "enque"
        if not self.aws_access_key_id:
            self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        if not self.aws_secret_access_key:
            self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        if not self.aws_region:
            self.aws_region = os.getenv("AWS_REGION", "us-east-2")
        if not self.bucket_name:
            self.bucket_name = os.getenv("AWS_S3_BUCKET", "enque")
        
        logger.debug(f"📋 S3 Configuration:")
        logger.debug(f"   - AWS Region: {self.aws_region}")
        logger.debug(f"   - S3 Bucket: {self.bucket_name}")
        if self.aws_access_key_id:
            logger.debug(f"   - Access Key ID: {self.aws_access_key_id[:10]}...{self.aws_access_key_id[-4:]}")
        else:
            logger.error("   - Access Key ID: NOT SET")
            
        if self.aws_secret_access_key:
            logger.debug("   - Secret Key: ***")
        else:
            logger.error("   - Secret Key: NOT SET")
        
        if not all([self.aws_access_key_id, self.aws_secret_access_key]):
            error_msg = "❌ AWS credentials not found in environment variables"
            logger.error(error_msg)
            logger.error("Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in Railway variables")
            raise ValueError(error_msg)

        try:
            logger.debug("🔌 Creating optimized S3 client...")

            config = Config(
                retries={'max_attempts': 2, 'mode': 'adaptive'},  
                max_pool_connections=50,  # Aumentar pool de conexiones
                region_name=self.aws_region,
                # Configuraciones adicionales para optimizar conexiones
                connect_timeout=5,
                read_timeout=10,
                tcp_keepalive=True
            )
            
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.aws_region,
                config=config
            )
            logger.debug("✅ Optimized S3 client created successfully")
        except Exception as e:
            logger.error(f"❌ Error creating S3 client: {e}")
            raise
        self._test_connection()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if hasattr(self, 's3_client') and self.s3_client:
                pass
        except Exception as e:
            logger.warning(f"Error during S3Service cleanup: {e}")
    
    def _test_connection(self):
        try:
            logger.debug("🔍 Testing S3 connection...")
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.debug(f"✅ Successfully connected to S3 bucket: {self.bucket_name}")
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
        try:
            logger.debug(f"📤 Starting S3 upload:")
            logger.debug(f"   - Original filename: {filename}")
            logger.debug(f"   - File size: {len(file_content)} bytes")
            logger.debug(f"   - Folder: {folder}")
            logger.debug(f"   - Content type: {content_type}")
            
            file_extension = os.path.splitext(filename)[1]
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            s3_key = f"{folder.rstrip('/')}/{unique_filename}" if folder else unique_filename
            logger.debug(f"   - S3 key: {s3_key}")

            if not content_type:
                content_type, _ = mimetypes.guess_type(filename)
                if not content_type:
                    content_type = "application/octet-stream"
            
            logger.debug(f"   - Final content type: {content_type}")
            
            # Upload to S3
            logger.debug("🚀 Uploading to S3...")
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_content,
                ContentType=content_type
            )
            public_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
            
            logger.debug(f"✅ File uploaded successfully to S3!")
            logger.debug(f"   - Public URL: {public_url}")
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
        max_size: int = 10 * 1024 * 1024 
    ) -> str:
        try:
            logger.debug(f"📁 Processing UploadFile:")
            logger.debug(f"   - Filename: {upload_file.filename}")
            logger.debug(f"   - Content type: {upload_file.content_type}")
            logger.debug(f"   - Folder: {folder}")
            logger.debug(f"   - Max size: {max_size / 1024 / 1024:.1f}MB")
            logger.debug("📖 Reading file content...")
            file_content = await upload_file.read()
            actual_size = len(file_content)
            logger.debug(f"   - Actual file size: {actual_size} bytes ({actual_size / 1024:.1f} KB)")
            if actual_size > max_size:
                error_msg = f"❌ File size {actual_size / 1024 / 1024:.1f}MB exceeds maximum of {max_size / 1024 / 1024:.1f}MB"
                logger.error(error_msg)
                raise HTTPException(
                    status_code=413,
                    detail=error_msg
                )
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
        try:
            logger.debug(f"📄 Uploading HTML content:")
            logger.debug(f"   - Filename: {filename}")
            logger.debug(f"   - Content length: {len(html_content)} characters")
            logger.debug(f"   - Folder: {folder}")
            html_bytes = html_content.encode('utf-8')
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
        try:
            logger.debug(f"🗑️ Deleting file from S3: {s3_key}")
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.debug(f"✅ Successfully deleted file from S3: {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"❌ Error deleting file from S3: {e}")
            return False
    
    def get_file_url(self, s3_key: str) -> str:
        return f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
    
    def list_files(self, folder: str = "", limit: int = 100) -> List[Dict]:
        try:
            logger.debug(f"📋 Listing files in S3:")
            logger.debug(f"   - Folder: {folder}")
            logger.debug(f"   - Limit: {limit}")
            
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
            
            logger.debug(f"✅ Found {len(files)} files in S3")
            return files
            
        except ClientError as e:
            error_msg = f"❌ Error listing files from S3: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
    
    def should_store_html_in_s3(self, html_content: str) -> bool:
        if not html_content:
            logger.debug("📝 Empty content - skipping S3")
            return False
        content_length = len(html_content)
        logger.debug(f"📤 Content length: {content_length} chars - ALWAYS storing in S3")
        return True
    
    def store_comment_html(self, comment_id: int, html_content: str) -> str:
        try:
            logger.debug(f"📄 Storing comment {comment_id} HTML in S3")
            filename = f"comment-{comment_id}.html"
            s3_url = self.upload_html_content(
                html_content=html_content,
                filename=filename,
                folder="comments"
            )
            
            logger.debug(f"✅ Comment {comment_id} HTML stored in S3: {s3_url}")
            return s3_url
            
        except Exception as e:
            logger.error(f"❌ Error storing comment {comment_id} HTML in S3: {str(e)}")
            raise
    
    def get_comment_html(self, s3_url: str) -> Optional[str]:
        try:
            logger.debug(f"📥 Fast retrieving comment HTML from S3: {s3_url}")
            file_content = self._download_file_from_s3(s3_url)
            if not file_content:
                return None
            html_content = file_content.decode('utf-8')
            logger.debug(f"✅ Fast retrieved {len(html_content)} characters from S3")
            return html_content
            
        except Exception as e:
            logger.error(f"❌ Error retrieving comment HTML from S3: {str(e)}")
            return None

    def _download_file_from_s3(self, s3_url: str) -> Optional[bytes]:
        try:
            if not s3_url.startswith(f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/"):
                logger.error(f"❌ Invalid S3 URL format: {s3_url}")
                return None
                
            s3_key = s3_url.replace(f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/", "")
            logger.debug(f"📥 Fast downloading file from S3: {s3_key}")
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            file_content = response['Body'].read()
            
            logger.debug(f"✅ Fast downloaded {len(file_content)} bytes from S3")
            return file_content
            
        except ClientError as e:
            logger.error(f"❌ Error downloading file from S3: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error downloading file from S3: {e}")
            return None
s3_service = None

def get_s3_service() -> S3Service:
    global s3_service
    if s3_service is None:
        logger.debug("🏗️ Creating new S3Service instance...")
        s3_service = S3Service()
    return s3_service 