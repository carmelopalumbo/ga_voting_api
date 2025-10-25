"""
Cryptographic utilities for handling sensitive citizen data.

This module provides functions for:
- Encrypting/decrypting personal data (fiscal codes, names, emails)
- Hashing fiscal codes for fast database lookups
- Generating random hashes for vote anonymization
"""

import hashlib
import secrets
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings
import base64


def _get_fernet_key():
    """
    Generate Fernet encryption key from settings.
    Uses PBKDF2 to derive a proper key from the ENCRYPTION_KEY setting.
    """
    # Get encryption key from settings
    password = settings.ENCRYPTION_KEY.encode()
    
    # Use a fixed salt (in production, store this securely)
    # For now, we derive it from the password itself
    salt = hashlib.sha256(password).digest()[:16]
    
    # Derive a proper Fernet key using PBKDF2
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    
    return Fernet(key)


def encrypt_data(data):
    """
    Encrypt sensitive data using Fernet (AES-128).
    
    Args:
        data (str): Plain text data to encrypt
        
    Returns:
        str: Encrypted data as base64 string
        
    Example:
        >>> encrypted_cf = encrypt_data("RSSMRA80A01H501Z")
        >>> print(encrypted_cf)
        'gAAAAABh...'
    """
    if not data:
        return None
    
    fernet = _get_fernet_key()
    encrypted = fernet.encrypt(data.encode())
    return encrypted.decode()


def decrypt_data(encrypted_data):
    """
    Decrypt data that was encrypted with encrypt_data().
    
    Args:
        encrypted_data (str): Base64 encrypted string
        
    Returns:
        str: Decrypted plain text
        
    Example:
        >>> decrypted_cf = decrypt_data(encrypted_cf)
        >>> print(decrypted_cf)
        'RSSMRA80A01H501Z'
    """
    if not encrypted_data:
        return None
    
    fernet = _get_fernet_key()
    decrypted = fernet.decrypt(encrypted_data.encode())
    return decrypted.decode()


def hash_fiscal_code(fiscal_code):
    """
    Create SHA-256 hash of fiscal code for fast database lookups.
    This hash is NOT reversible (unlike encryption).
    
    Args:
        fiscal_code (str): Italian fiscal code (codice fiscale)
        
    Returns:
        str: 64-character hexadecimal hash
        
    Example:
        >>> hash_fc = hash_fiscal_code("RSSMRA80A01H501Z")
        >>> print(hash_fc)
        'a3f5b9c8d2e1f...'  # 64 chars
    """
    if not fiscal_code:
        return None
    
    # Normalize: uppercase and strip whitespace
    normalized = fiscal_code.strip().upper()
    
    # Create SHA-256 hash
    hash_obj = hashlib.sha256(normalized.encode())
    return hash_obj.hexdigest()


def generate_session_hash():
    """
    Generate a random hash for vote anonymization.
    Used in Result model to prevent timing correlation attacks.
    
    Returns:
        str: 64-character random hexadecimal string
        
    Example:
        >>> random_hash = generate_session_hash()
        >>> print(random_hash)
        'f4e3d2c1b0a9...'  # 64 chars, completely random
    """
    # Generate 32 random bytes and convert to hex (64 chars)
    random_bytes = secrets.token_bytes(32)
    return random_bytes.hex()


def verify_fiscal_code_hash(fiscal_code, stored_hash):
    """
    Verify if a fiscal code matches a stored hash.
    Used during SPID login to find existing citizens.
    
    Args:
        fiscal_code (str): Plain fiscal code to verify
        stored_hash (str): Hash stored in database
        
    Returns:
        bool: True if fiscal code matches the hash
    """
    if not fiscal_code or not stored_hash:
        return False
    
    computed_hash = hash_fiscal_code(fiscal_code)
    return computed_hash == stored_hash


# ==============================================================================
# HELPER FUNCTIONS FOR CITIZEN MODEL
# ==============================================================================

def encrypt_citizen_data(fiscal_code, first_name, last_name, email=None):
    """
    Encrypt all citizen personal data at once.
    Convenience function for use in SPID callback.
    
    Args:
        fiscal_code (str): Codice fiscale
        first_name (str): Nome
        last_name (str): Cognome
        email (str, optional): Email
        
    Returns:
        dict: Dictionary with encrypted data and hash
    """
    return {
        'fiscal_code_hash': hash_fiscal_code(fiscal_code),
        'fiscal_code_encrypted': encrypt_data(fiscal_code),
        'first_name_encrypted': encrypt_data(first_name),
        'last_name_encrypted': encrypt_data(last_name),
        'email_encrypted': encrypt_data(email) if email else None,
    }


def decrypt_citizen_data(citizen):
    """
    Decrypt all citizen personal data at once.
    Useful for admin views or document generation.
    
    Args:
        citizen (Citizen): Citizen model instance
        
    Returns:
        dict: Dictionary with decrypted data
    """
    return {
        'fiscal_code': decrypt_data(citizen.fiscal_code_encrypted),
        'first_name': decrypt_data(citizen.first_name_encrypted),
        'last_name': decrypt_data(citizen.last_name_encrypted),
        'email': decrypt_data(citizen.email_encrypted) if citizen.email_encrypted else None,
    }


# ==============================================================================
# TESTING FUNCTIONS (for development)
# ==============================================================================

def test_encryption():
    """
    Test encryption/decryption functionality.
    Run this in Django shell to verify crypto is working.
    
    Usage:
        >>> from authentication.crypto_utils import test_encryption
        >>> test_encryption()
        ✓ Encryption test passed
        ✓ Hash test passed
        ✓ Session hash test passed
    """
    # Test encryption
    original = "RSSMRA80A01H501Z"
    encrypted = encrypt_data(original)
    decrypted = decrypt_data(encrypted)
    assert original == decrypted, "Encryption/decryption failed!"
    print("✓ Encryption test passed")
    
    # Test hashing
    hash1 = hash_fiscal_code("RSSMRA80A01H501Z")
    hash2 = hash_fiscal_code("RSSMRA80A01H501Z")
    assert hash1 == hash2, "Hashing is not consistent!"
    assert len(hash1) == 64, "Hash length incorrect!"
    print("✓ Hash test passed")
    
    # Test random hash
    random1 = generate_session_hash()
    random2 = generate_session_hash()
    assert random1 != random2, "Random hash not random!"
    assert len(random1) == 64, "Random hash length incorrect!"
    print("✓ Session hash test passed")
    
    print("\n✅ All crypto tests passed!")


if __name__ == "__main__":
    # Allow running tests directly
    test_encryption()