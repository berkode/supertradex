#!/usr/bin/env python3
"""
Comprehensive TokenScanner test that mimics main.py's environment loading.
"""
import asyncio
import logging
import sys
import os
import io
from pathlib import Path
from dotenv import dotenv_values, load_dotenv

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import necessary modules
from config.settings import Settings, EncryptionSettings
from utils.logger import get_logger
from utils.encryption import get_encryption_password, decrypt_env_file

def update_dotenv_vars(env_vars: dict, override: bool = False) -> None:
    """Update environment variables from a dictionary."""
    for key, value in env_vars.items():
        if value is not None:
            if override or key not in os.environ:
                os.environ[key] = str(value)

async def test_scanner_with_proper_env():
    """Test TokenScanner with proper environment loading like main.py"""
    
    project_root = Path(__file__).parent
    ENV_DIR = project_root / "config"
    ENV_PLAIN_PATH = ENV_DIR / ".env"
    ENV_ENCRYPTED_PATH = ENV_DIR / ".env.encrypted"
    
    print("=== Loading Environment Variables ===")
    
    # 1. Try getting encryption password
    password = None
    try:
        key_settings = EncryptionSettings()
        key_file_to_use = key_settings.ENCRYPTION_KEY_PATH
        print(f"Using key filename: {key_file_to_use}")
        
        password = get_encryption_password()
        if password:
            print("Successfully retrieved encryption password")
        else:
            password = os.getenv("ENCRYPTION_PASSWORD")
            if password:
                print("Using encryption password from environment variable")
    except Exception as e:
        print(f"Error retrieving encryption password: {e}")

    # 2. Try loading encrypted file first
    if ENV_ENCRYPTED_PATH.exists():
        print(f"Found encrypted environment file: {ENV_ENCRYPTED_PATH}")
        if password:
            try:
                decrypted_content = decrypt_env_file(ENV_ENCRYPTED_PATH, password)
                if decrypted_content:
                    loaded_vars = dotenv_values(stream=io.StringIO(decrypted_content))
                    print(f"Found {len(loaded_vars)} variables in decrypted content")
                    update_dotenv_vars(loaded_vars, override=False)
                    print("Environment updated from decrypted .env.encrypted")
            except Exception as e:
                print(f"Failed to decrypt {ENV_ENCRYPTED_PATH}: {e}")
        else:
            print("No encryption password available")
    else:
        print(f"Encrypted environment file not found: {ENV_ENCRYPTED_PATH}")

    # 3. Load plain .env file
    if ENV_PLAIN_PATH.exists():
        print(f"Loading plain environment file: {ENV_PLAIN_PATH}")
        try:
            load_dotenv(dotenv_path=ENV_PLAIN_PATH, override=True)
            print("Plain .env file loaded")
        except Exception as e:
            print(f"Failed loading plain env file: {e}")
    else:
        print(f"Plain environment file not found: {ENV_PLAIN_PATH}")

    print("=== Environment Loading Complete ===\n")

    # 4. Now test settings and TokenScanner
    logger = get_logger(__name__)
    
    try:
        logger.info("Loading settings...")
        settings = Settings()
        logger.info("Settings loaded successfully")
        
        # Check TOKEN_SCAN_INTERVAL
        logger.info(f"TOKEN_SCAN_INTERVAL: {settings.TOKEN_SCAN_INTERVAL}")
        
        # Test TokenScanner initialization
        logger.info("Testing TokenScanner initialization...")
        
        from data.token_scanner import TokenScanner
        from data.token_database import TokenDatabase
        from data.market_data import MarketData
        from filters.filter_manager import FilterManager
        from config.thresholds import Thresholds
        from config.filters_config import FiltersConfig
        import httpx
        
        # Initialize dependencies like in main.py
        logger.info("Initializing dependencies...")
        
        # Create HTTP client
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(settings.HTTP_TIMEOUT))
        
        # Initialize database
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        
        # Initialize market data (simplified)
        market_data = MarketData(settings=settings, token_db=db)
        
        # Initialize thresholds and filters
        thresholds = Thresholds(settings)
        filters_config = FiltersConfig(settings)
        
        # Create filter manager (simplified)
        filter_manager = FilterManager(
            settings=settings,
            thresholds=thresholds,
            filters_config=filters_config,
            rugcheck_api=None,
            solsniffer_api=None,
            twitter_check=None
        )
        
        # Now try to create TokenScanner
        logger.info("Creating TokenScanner...")
        token_scanner = TokenScanner(
            settings=settings,
            db=db,
            market_data=market_data,
            filter_manager=filter_manager,
            thresholds=thresholds,
            http_client=http_client
        )
        
        logger.info("TokenScanner created successfully!")
        logger.info(f"Scanner scan interval: {token_scanner.scan_interval} seconds")
        
        # Test a quick scan (just to see if it starts)
        logger.info("Testing a quick scan...")
        await token_scanner.scan_tokens()
        
        logger.info("Quick scan completed!")
        
        # Cleanup
        await token_scanner.close()
        await db.close()
        await http_client.aclose()
        
        logger.info("Test completed successfully!")
        
    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
        return False
    
    return True

if __name__ == "__main__":
    success = asyncio.run(test_scanner_with_proper_env())
    if success:
        print("\n✅ TokenScanner test PASSED")
    else:
        print("\n❌ TokenScanner test FAILED") 