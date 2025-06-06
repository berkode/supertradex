#!/usr/bin/env python3
"""
Environment Variable Encryption System

This module provides a secure way to store and access sensitive environment variables
using Fernet symmetric encryption. It handles all encryption-related functionality
for the application.

Features:
- Password-based encryption using PBKDF2 key derivation
- Secure storage of sensitive environment variables
- Automatic decryption when loading environment variables
- Secure password storage using system-specific master key
- Fallback to regular .env file if encrypted file doesn't exist

Usage:
1. Set your encryption password in the environment:
   export ENCRYPTION_PASSWORD="your-secure-password"

2. Encrypt your .env file:
   python utils/encryption.py

How it works:
1. The system uses the ENCRYPTION_PASSWORD environment variable as the encryption key
2. The encrypted file is stored as .env.encrypted by default
3. When loading environment variables:
   - Creates a temporary decrypted file
   - Loads the variables using python-dotenv
   - Deletes the temporary file
4. If the encrypted file doesn't exist, falls back to loading the regular .env file

Security Notes:
- The encryption password should be kept secure and not committed to version control
- The .env.encrypted file contains sensitive data and should not be committed to version control
- The temporary decrypted file is automatically cleaned up after use
- The master key is derived from system-specific information and stored securely

Dependencies:
- cryptography
- python-dotenv

Integration:
The encryption system is integrated with the main application files:
- main.py
- web/app.py
- appserver.py

These files automatically handle loading the encrypted environment variables when the application starts.
"""

import os
import base64
import platform
import uuid
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv
import json
from pathlib import Path
from cryptography.hazmat.backends import default_backend
import io
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)

# Define project root relative to this file (utils/encryption.py -> project_root)
PROJECT_ROOT = Path(__file__).parent.parent

def get_system_identifier() -> str:
    """Generate a unique system identifier based on hardware and OS information."""
    system_info = [
        platform.node(),  # Computer name
        platform.machine(),  # Machine type
        str(uuid.getnode()),  # MAC address
        platform.processor(),  # CPU info
        platform.system(),  # OS name
        platform.version(),  # OS version
    ]
    return hashlib.sha256(''.join(system_info).encode()).hexdigest()

def generate_master_key(system_id: str = None) -> bytes:
    """Generate a master key based on system identifier."""
    if system_id is None:
        system_id = get_system_identifier()
    
    # Use PBKDF2 to derive a key from the system identifier
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'supertradex_master_key',  # Fixed salt for master key
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(system_id.encode()))

def get_key_path() -> Path:
    """Get the encryption key path from .env file or use default."""
    # Load the .env file first to get ENCRYPTION_KEY_PATH
    env_path = PROJECT_ROOT / "config" / ".env"
    if not env_path.exists():
        logger.error(f"Config .env file not found at {env_path}")
        raise FileNotFoundError(f"Config .env file not found at {env_path}")
    
    load_dotenv(env_path)
    key_path_str = os.getenv('ENCRYPTION_KEY_PATH', 'config/.key')
    
    # Convert to Path and resolve relative to project root
    key_path = Path(key_path_str)
    if not key_path.is_absolute():
        key_path = PROJECT_ROOT / key_path
    
    # Ensure parent directory exists
    key_path.parent.mkdir(parents=True, exist_ok=True)
    
    return key_path

def store_encryption_password(password: str) -> None:
    """Store the encryption password securely using a master key."""
    try:
        master_key = generate_master_key()
        cipher = Fernet(master_key)

        # Encrypt the password
        encrypted_password = cipher.encrypt(password.encode())

        # Get key path from .env
        key_path = get_key_path()

        # Store the encrypted password
        with open(key_path, 'wb') as f:
            f.write(encrypted_password)

        logger.info(f"Encryption password stored securely in {key_path}")
    except Exception as e:
        logger.error(f"Failed to store encryption password: {e}")
        raise

def get_encryption_password() -> Optional[str]:
    """Retrieve the encryption password using the master key."""
    try:
        master_key = generate_master_key()
        cipher = Fernet(master_key)
        
        # Get key path from .env
        key_path = get_key_path()
        
        # Read and decrypt the password
        with open(key_path, 'rb') as f:
            encrypted_password = f.read()
        
        return cipher.decrypt(encrypted_password).decode()
    except FileNotFoundError:
        logger.error(f"Error retrieving encryption password: Key file not found at {key_path}")
        return None
    except Exception as e:
        logger.error(f"Error retrieving encryption password: {e}")
        return None

def generate_key(password: str, salt: bytes = None) -> tuple[bytes, bytes]:
    """Generate a key from a password using PBKDF2."""
    if salt is None:
        salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key, salt

def encrypt_env_file(password: str, env_file: str = "config/.env", output_file: str = "config/.env.encrypted") -> bool:
    """Encrypt the .env file using the provided password. Returns True on success, False on failure."""
    logger = get_logger(__name__) # Use local logger instance
    try:
        # Ensure paths are Path objects and resolve relative paths
        env_path = Path(env_file)
        if not env_path.is_absolute():
            env_path = PROJECT_ROOT / env_path

        output_path = Path(output_file)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Read the .env file
        logger.debug(f"Reading environment file: {env_path}")
        with open(env_path, 'r') as f:
            env_contents = f.read()

        # Generate key and salt
        logger.debug("Generating encryption key and salt...")
        key, salt = generate_key(password)

        # Create Fernet cipher
        logger.debug("Encrypting file contents...")
        encrypted_data = key.encrypt(env_contents.encode())

        # Save encrypted data and salt
        logger.debug(f"Writing encrypted data to: {output_path}")
        with open(output_path, 'wb') as f:
            f.write(salt + encrypted_data)

        logger.info(f"Successfully encrypted {env_path} to {output_path}")
        return True # Explicitly return True on success

    except FileNotFoundError:
        logger.error(f"Error during encryption: Input file not found at {env_path}")
        return False
    except PermissionError:
        logger.error(f"Error during encryption: Permission denied for {env_path} or {output_path}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during encryption of {env_path}: {e}", exc_info=True)
        return False

def decrypt_env_file(encrypted_path: Path, password: str) -> Optional[str]:
    """
    Decrypts an environment file encrypted with Fernet using a password.

    Args:
        encrypted_path: Path to the encrypted file (.env.encrypted).
        password: The password used for encryption.

    Returns:
        The decrypted file content as a string if successful, otherwise None.
    """
    logger = get_logger(__name__) # Use local logger instance
    if not encrypted_path.exists():
        logger.error(f"Encrypted file not found at {encrypted_path}")
        return None

    try:
        # Read salt and encrypted data from the encrypted file
        with open(encrypted_path, "rb") as f:
            salt = f.read(16) # Read the salt (first 16 bytes)
            if len(salt) < 16:
                logger.error(f"Encrypted file {encrypted_path} is too short, likely corrupted or missing salt.")
                return None
            encrypted_data = f.read()
            if not encrypted_data:
                logger.error(f"Encrypted file {encrypted_path} has no data after salt.")
                return None

        # Restore PBKDF2 derivation using password and salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000, # Standard iteration count
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))

        # Use the derived key
        fernet = Fernet(key)

        decrypted_data = fernet.decrypt(encrypted_data)
        decrypted_content = decrypted_data.decode()
        logger.info(f"Successfully decrypted content from {encrypted_path} using password.")
        return decrypted_content # Return content directly

    except InvalidToken:
        logger.error(f"Decryption failed for {encrypted_path}: Invalid password or corrupted file.", exc_info=True)
        return None
    except FileNotFoundError as e:
        logger.error(f"Error reading file during decryption: {encrypted_path} - {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during decryption of {encrypted_path}: {e}", exc_info=True)
        return None

def test_encryption(encrypted_path: Path, password: str) -> bool:
    """Tests the encryption/decryption process and access to a sensitive var."""
    logger = get_logger(__name__) # Use local logger instance
    test_var_name = "TEST_SENSITIVE_VAR"
    test_var_value = "THIS_IS_SECRET"
    temp_env_plain = Path(".env.test_plain")
    temp_env_encrypted = Path(".env.test_encrypted")
    original_env_value = os.environ.get(test_var_name) # Store original value if exists

    try:
        # 1. Create a dummy .env file (without newline at end)
        with open(temp_env_plain, "w") as f:
            f.write(f"{test_var_name}={test_var_value}")  # No newline

        # 2. Encrypt it
        if not encrypt_env_file(password, temp_env_plain, temp_env_encrypted):
            logger.error("Encryption test failed: Could not encrypt dummy file.")
            return False
        logger.info(f"Encryption test: Encrypted {temp_env_plain} to {temp_env_encrypted}")

        # 3. Decrypt it (using the modified decrypt function)
        decrypted_content = decrypt_env_file(temp_env_encrypted, password)
        if decrypted_content is None:
            logger.error("Encryption test failed: Could not decrypt dummy encrypted file.")
            return False
        logger.info("Encryption test: Successfully decrypted dummy file content.")

        # 4. Load the decrypted content into the environment temporarily
        try:
            # Ensure environment is clean of the test variable before loading stream
            if test_var_name in os.environ:
                del os.environ[test_var_name]
            load_dotenv(stream=io.StringIO(decrypted_content), override=True)
            logger.info("Encryption test: Loaded decrypted content into environment via stream.")
        except Exception as e:
            logger.error(f"Encryption test failed: Could not load decrypted stream: {e}", exc_info=True)
            return False

        # 5. Check if the variable is accessible
        retrieved_value = os.getenv(test_var_name)
        if retrieved_value == test_var_value:  # Direct comparison now works as there's no newline
            logger.info(f"Encryption test successful: Retrieved variable '{test_var_name}' correctly.")

            # Optional: Test access to real sensitive variables from config/.env.encrypted
            logger.info("\nTesting access to sensitive variables from actual encrypted file:")
            actual_decrypted_content = decrypt_env_file(encrypted_path, password)
            if actual_decrypted_content:
                try:
                    # Load actual encrypted vars using stream, potentially overriding existing ones for test scope
                    load_dotenv(stream=io.StringIO(actual_decrypted_content), override=True)
                    logger.info("Loaded actual encrypted vars from stream for testing access.")

                    # Need settings for display logic (masked values)
                    settings_instance = None
                    try:
                        from config.settings import Settings
                        settings_instance = Settings() # Re-init settings after loading actual vars
                    except ImportError:
                        logger.warning("Could not import Settings for test_encryption sensitive var display.")
                    except Exception as e:
                        logger.error(f"Error initializing Settings in test_encryption: {e}", exc_info=True)

                    sensitive_keys_to_test = [
                        'SOLANA_RPC_URL', 'HELIUS_API_KEY', 'SOLSNIFFER_API_KEY',
                        'TWITTER_API_KEY', 'TWITTER_API_KEY_SECRET', 'TWITTER_PASSWORD',
                        'DISCORD_BOT_TOKEN', 'DISCORD_CHANNEL_ID', 'DISCORD_WEBHOOK_URL',
                        'BIRDEYE_API_KEY', 'JUPITER_API_ENDPOINT'
                    ]
                    for key in sensitive_keys_to_test:
                        value = os.getenv(key)
                        # Use masking logic, falling back if Settings instance failed
                        if settings_instance and hasattr(settings_instance, '_mask_value'):
                            masked_value = settings_instance._mask_value(key, value)
                        else:
                            masked_value = mask_sensitive_value(key, value)
                        logger.info(f"  {key}: {masked_value}")

                except Exception as e:
                    logger.error(f"Error testing access to actual sensitive vars: {e}", exc_info=True)
            else:
                logger.error("Could not decrypt actual encrypted file for access test.")

            return True
        else:
            logger.error(f"Encryption test failed: Expected '{test_var_value}', got '{retrieved_value}'.")
            return False
        
    except Exception as e:
        logger.error(f"An unexpected error occurred during encryption test: {e}", exc_info=True)
        return False
    finally:
        # Clean up test files
        if temp_env_plain.exists():
            temp_env_plain.unlink()
        if temp_env_encrypted.exists():
            temp_env_encrypted.unlink()
        # Restore original environment variable if it was overwritten
        if original_env_value is None:
            if os.environ.get(test_var_name): # If test set it and it wasn't there before
                del os.environ[test_var_name]
        else:
            os.environ[test_var_name] = original_env_value # Restore original
        logger.debug("Encryption test cleanup finished.")

# Add mask_sensitive_value helper if it doesn't exist globally
# (Assuming it might be needed by test_encryption now)
SENSITIVE_KEYS = [
    'API_KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'DATABASE_URL',
    'RPC_URL', 'WSS_URL', 'PRIVATE_KEY', 'SEED_PHRASE', 'EMAIL', 'WEBHOOK_URL'
]

def mask_sensitive_value(key: str, value: Optional[str]) -> str:
    if value is None:
        return "Not set"
    if not isinstance(value, str):
        # Attempt to convert non-strings, log warning
        logger.warning(f"Non-string value encountered for key '{key}' during masking: {type(value)}. Converting to string.")
        try:
            value = str(value)
        except Exception:
            return "[Unmaskable Value]"

    # Basic check if key name suggests sensitivity
    key_upper = key.upper() if key else ''
    is_sensitive = any(sensitive_part in key_upper for sensitive_part in SENSITIVE_KEYS)

    if is_sensitive and len(value) > 8:
        # Mask value: show first 3 and last 3 chars
        return f"{value[:3]}...{value[-3:]}"
    elif is_sensitive:
        # Mask shorter sensitive values completely
        return "*" * len(value) if len(value) > 0 else "******"
    else:
        # Return non-sensitive values as is
        return value

# Ensure Settings class import attempt for test_encryption display logic
# This doesn't strictly need to succeed for the core test logic to work
try:
    from config.settings import Settings
except ImportError:
    logger.warning("Could not import Settings for test_encryption display logic.")
    Settings = None # Allows the test to proceed without crashing if Settings unavailable

def main():
    """Main function to handle encryption operations."""
    logger.info("Starting encryption utility...")
    password = None # Initialize password
    
    try:
        # Get the key path first
        key_path = get_key_path()
        logger.info(f"Using encryption key path: {key_path}")
        logger.debug(f"Key path exists: {key_path.exists()}, is file: {key_path.is_file() if key_path.exists() else False}")
        
        # Check if key file exists
        if key_path.is_file():
            logger.info("An existing encryption key file was found.")
            response = input("Do you want to:\n1. Delete the existing key and create a new one\n2. Continue with the existing key\nEnter your choice (1/2): ")
        
        if response == "1":
            try:
            # Delete existing key file
                key_path.unlink(missing_ok=True)
                logger.info("Existing key file deleted.")
            except Exception as e:
                logger.warning(f"Could not delete existing key file: {e}")
                
            # Get new password and store it for this run
            password = input("Enter new encryption password: ")
            store_encryption_password(password) # Store it securely
        else:
            # Use existing password
            password = get_encryption_password()
            if not password:
                logger.error("Could not retrieve stored encryption password")
                return # Exit if password retrieval fails
            else: # Case where key file does not exist
            # Get new password and store it
                logger.info("No existing encryption key file found. Creating a new one.")
        password = input("Enter encryption password: ")
        store_encryption_password(password)
    
        # --- Encryption steps using the obtained password --- 
        if password is None:
            logger.error("Password was not set or retrieved. Cannot proceed with encryption.")
            return

        # Check if .env file exists
        env_path = PROJECT_ROOT / "config" / ".env"
        if not env_path.is_file():
            logger.error("config/.env file not found!")
        return
    
         # Check if encrypted file exists
        encrypted_path = PROJECT_ROOT / "config" / ".env.encrypted"
        if encrypted_path.is_file():
            response = input("\nAn existing encrypted file (config/.env.encrypted) was found. Do you want to overwrite it? (y/n): ")
        if response.lower() != 'y':
            logger.info("Operation cancelled.")
            return
        logger.info("Existing encrypted file will be overwritten.")
    
        # Encrypt the .env file
        if not encrypt_env_file(password):
            logger.error("Encryption failed.")
            return
    
        # Test the encryption
        if not test_encryption(encrypted_path, password):
            logger.error("Encryption test failed.")
            return
    
        # Ask if user wants to delete the original .env file
        response = input("\nDo you want to delete the original .env file? (y/n): ")
        if response.lower() == 'y':
            try:
                env_path.unlink()
                logger.info("Original .env file deleted.")
            except Exception as e:
                logger.error(f"Could not delete original .env file: {e}")
        else:
            logger.info("Original .env file kept.")
                
    except Exception as e: # Catches errors from get_key_path or other setup issues
        logger.error(f"An error occurred during the encryption setup or process: {e}", exc_info=True)
        return

if __name__ == "__main__":
    main() 