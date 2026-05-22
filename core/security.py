"""
Security module for encryption/decryption of keys
"""
from cryptography.fernet import Fernet
from flask import current_app
import base64


class KeyEncryption:
    """Class for encrypting and decrypting keys"""
    
    def __init__(self, encryption_key=None):
        """
        Initialize with encryption key from config or provided key
        
        Args:
            encryption_key: Base64-encoded Fernet key (optional, uses config if not provided)
        """
        if encryption_key is None:
            try:
                encryption_key = current_app.config['ENCRYPTION_KEY']
            except (RuntimeError, KeyError):
                # Fallback for cases where app context is not available
                import os
                from dotenv import load_dotenv
                load_dotenv()
                encryption_key = os.environ.get('ENCRYPTION_KEY')
        
        if not encryption_key:
            raise ValueError("Encryption key is required")
        
        # Ensure key is bytes
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()
        
        self.fernet = Fernet(encryption_key)
    
    def encrypt(self, plaintext_key):
        """
        Encrypt a key
        
        Args:
            plaintext_key: Plain text key to encrypt
            
        Returns:
            Encrypted key as base64 string
        """
        if not plaintext_key:
            raise ValueError("Key cannot be empty")
        
        encrypted_bytes = self.fernet.encrypt(plaintext_key.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')
    
    def decrypt(self, encrypted_key):
        """
        Decrypt a key
        
        Args:
            encrypted_key: Encrypted key as string
            
        Returns:
            Decrypted plain text key
        """
        if not encrypted_key:
            raise ValueError("Encrypted key cannot be empty")
        
        try:
            decrypted_bytes = self.fernet.decrypt(encrypted_key.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Failed to decrypt key: {str(e)}")


def get_encryption_handler():
    """Get encryption handler instance"""
    return KeyEncryption()


def encrypt_key(plaintext_key):
    """Helper function to encrypt a key"""
    handler = get_encryption_handler()
    return handler.encrypt(plaintext_key)


def decrypt_key(encrypted_key):
    """Helper function to decrypt a key"""
    handler = get_encryption_handler()
    return handler.decrypt(encrypted_key)