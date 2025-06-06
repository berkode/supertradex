#!/usr/bin/env python3
"""
Diagnostic script to understand token selection issues and test manual monitoring
"""
import asyncio
import sys
import os
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from utils.encryption import decrypt_env_file, get_encryption_password
from config.settings import Settings, EncryptionSettings
from data.token_database import TokenDatabase
from data.market_data import MarketData
import logging
from dotenv import load_dotenv, dotenv_values
import io

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_environment():
    """Load environment variables (simplified version of main.py logic)"""
    env_dir = Path(__file__).parent / "config"
    env_plain_path = env_dir / ".env"
    env_encrypted_path = env_dir / ".env.encrypted"
    
    # Try loading encrypted file first
    password = None
    try:
        key_settings = EncryptionSettings()
        password = get_encryption_password()
        if password and env_encrypted_path.exists():
            decrypted_content = decrypt_env_file(env_encrypted_path, password)
            if decrypted_content:
                loaded_vars = dotenv_values(stream=io.StringIO(decrypted_content))
                for key, value in loaded_vars.items():
                    if value and key not in os.environ:
                        os.environ[key] = str(value)
                logger.info(f"Loaded {len(loaded_vars)} variables from encrypted file")
    except Exception as e:
        logger.warning(f"Could not load encrypted file: {e}")
    
    # Load plain .env file
    if env_plain_path.exists():
        load_dotenv(dotenv_path=env_plain_path, override=True)
        logger.info("Loaded plain .env file")

async def diagnose_token_selection():
    """Diagnose why get_best_token_for_trading is returning None"""
    
    logger.info("=== Loading Environment ===")
    load_environment()
    
    logger.info("=== Loading Settings ===")
    settings = Settings()
    
    logger.info("=== Initializing Database ===")
    db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
    
    try:
        logger.info("=== Checking Settings Values ===")
        logger.info(f"MONITORED_PROGRAMS_LIST: {settings.MONITORED_PROGRAMS_LIST}")
        logger.info(f"DEX_PROGRAM_IDS: {settings.DEX_PROGRAM_IDS}")
        
        logger.info("=== Checking All Tokens in Database ===")
        all_tokens = await db.get_tokens_list()
        logger.info(f"Total tokens in database: {len(all_tokens)}")
        
        if all_tokens:
            logger.info("=== Sample Tokens ===")
            for i, token in enumerate(all_tokens[:5]):  # Show first 5 tokens
                logger.info(f"Token {i+1}: {token.mint}")
                logger.info(f"  - overall_filter_passed: {token.overall_filter_passed}")
                logger.info(f"  - rugcheck_score: {token.rugcheck_score}")
                logger.info(f"  - volume_24h: {token.volume_24h}")
                logger.info(f"  - liquidity: {token.liquidity}")
                logger.info(f"  - pair_address: {token.pair_address}")
                logger.info(f"  - dex_id: {token.dex_id}")
                logger.info(f"  - monitoring_status: {token.monitoring_status}")
                
        logger.info("=== Testing Token Selection ===")
        
        # Test with include_inactive_tokens=True (what the scanner uses)
        best_token = await db.get_best_token_for_trading(include_inactive_tokens=True)
        logger.info(f"Best token with include_inactive_tokens=True: {best_token}")
        
        # Test with include_inactive_tokens=False
        best_token_active = await db.get_best_token_for_trading(include_inactive_tokens=False)
        logger.info(f"Best token with include_inactive_tokens=False: {best_token_active}")
        
        if not best_token and all_tokens:
            logger.info("=== Manual Token Selection for Testing ===")
            # Select the first token that passed filters
            test_token = None
            for token in all_tokens:
                if token.overall_filter_passed and token.pair_address and token.dex_id:
                    test_token = token
                    break
            
            if test_token:
                logger.info(f"Selected test token: {test_token.mint}")
                logger.info(f"  - dex_id: {test_token.dex_id}")
                logger.info(f"  - pair_address: {test_token.pair_address}")
                
                logger.info("=== Testing MarketData Monitoring ===")
                market_data = MarketData(settings=settings)
                
                try:
                    # Test if we can start monitoring this token
                    success = await market_data.start_monitoring_token(
                        mint=test_token.mint
                    )
                    
                    if success:
                        logger.info(f"✅ Successfully started monitoring {test_token.mint}")
                        
                        # Wait a bit to see if we get data
                        logger.info("Waiting 10 seconds for price data...")
                        await asyncio.sleep(10)
                        
                        # Check if we got any price updates
                        price_data = market_data.get_realtime_pair_state(test_token.mint)
                        logger.info(f"Price data after 10 seconds: {price_data}")
                        
                        # Stop monitoring
                        await market_data.stop_monitoring_token(test_token.mint)
                        logger.info(f"✅ Stopped monitoring {test_token.mint}")
                        
                    else:
                        logger.error(f"❌ Failed to start monitoring {test_token.mint}")
                        
                finally:
                    await market_data.close()
                    
            else:
                logger.warning("No suitable test token found - all tokens missing required fields")
                
    except Exception as e:
        logger.error(f"Error during diagnosis: {e}", exc_info=True)
        
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(diagnose_token_selection()) 