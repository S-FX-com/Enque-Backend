import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app.core.config import settings
from app.utils.logger import logger

class EncryptionService:
    def __init__(self, key: str):
        if not key:
            raise ValueError("Encryption key cannot be empty.")
        
        # Use a salt (can be static as long as it's not public)
        # For better security, this could also come from settings
        salt = b'enque-salt_'
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        
        # Derive a key from the setting
        encoded_key = key.encode()
        fernet_key = base64.urlsafe_b64encode(kdf.derive(encoded_key))
        
        self.fernet = Fernet(fernet_key)

    def encrypt(self, data: str) -> str:
        """Encrypts a string and returns it as a string."""
        if not data:
            return data
        try:
            encrypted_data = self.fernet.encrypt(data.encode())
            return encrypted_data.decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}", exc_info=True)
            raise

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypts a string and returns it."""
        if not encrypted_data:
            return encrypted_data
        try:
            decrypted_data = self.fernet.decrypt(encrypted_data.encode())
            return decrypted_data.decode()
        except Exception as e:
            # This can happen if the key is wrong or data is corrupted
            logger.error(f"Decryption failed. This may be due to an invalid key or corrupted data.", exc_info=True)
            # Depending on the use case, you might want to return None or an empty string
            # For token decryption, raising an error is often safer.
            raise ValueError("Decryption failed. Invalid key or corrupted data.")

# Global instance of the encryption service
try:
    encryption_service = EncryptionService(settings.ENCRYPTION_KEY)
except ValueError as e:
    logger.error(f"Failed to initialize EncryptionService: {e}. Ensure ENCRYPTION_KEY is set.")
    # Set to None if initialization fails, so the app can start but encryption-dependent features will fail loudly.
    encryption_service = None
