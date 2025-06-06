#!/usr/bin/env python3
"""
Simple test: Take first token from database and test monitoring
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

async def test_monitor_first_token():
    """Get first token from database and test monitoring it"""
    
    logger.info("=== Loading Environment ===")
    load_environment()
    
    logger.info("=== Loading Settings ===")
    settings = Settings()
    
    logger.info("=== Initializing Database ===")
    db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
    
    try:
        logger.info("=== Checking Database for Tokens ===")
        all_tokens = await db.get_tokens_list()
        logger.info(f"Total tokens in database: {len(all_tokens)}")
        
        if not all_tokens:
            logger.warning("❌ No tokens found in database. Need to run scanner first.")
            return
            
        # Get the first token
        first_token = all_tokens[0]
        logger.info(f"=== First Token Details ===")
        logger.info(f"Mint: {first_token.mint}")
        logger.info(f"Symbol: {first_token.symbol}")
        logger.info(f"Name: {first_token.name}")
        logger.info(f"Overall filter passed: {first_token.overall_filter_passed}")
        logger.info(f"Rugcheck score: {first_token.rugcheck_score}")
        logger.info(f"Volume 24h: {first_token.volume_24h}")
        logger.info(f"Liquidity: {first_token.liquidity}")
        logger.info(f"Pair address: {first_token.pair_address}")
        logger.info(f"DEX ID: {first_token.dex_id}")
        logger.info(f"Monitoring status: {first_token.monitoring_status}")
        
        logger.info("=== Testing MarketData Monitoring ===")
        market_data = MarketData(settings=settings)
        
        try:
            # Test if we can start monitoring this token
            success = await market_data.start_monitoring_token(mint=first_token.mint)
            
            if success:
                logger.info(f"✅ Successfully started monitoring {first_token.mint}")
                
                # Wait for some price data
                logger.info("Waiting 15 seconds for price data...")
                await asyncio.sleep(15)
                
                # Check if we got any price updates
                price_data = market_data.get_realtime_pair_state(first_token.mint)
                logger.info(f"Price data after 15 seconds: {price_data}")
                
                # Get general market data
                market_info = await market_data.get_token_price(first_token.mint)
                logger.info(f"Market info: {market_info}")
                
                # Check monitoring stats
                monitoring_stats = market_data.get_monitoring_stats()
                logger.info(f"Monitoring stats: {monitoring_stats}")
                
                # Stop monitoring
                await market_data.stop_monitoring_token(first_token.mint)
                logger.info(f"✅ Stopped monitoring {first_token.mint}")
                
            else:
                logger.error(f"❌ Failed to start monitoring {first_token.mint}")
                
                # Try to get basic price info without monitoring
                logger.info("Trying to get basic price info without real-time monitoring...")
                basic_price = await market_data.get_token_price(first_token.mint)
                logger.info(f"Basic price info: {basic_price}")
                
        except Exception as e:
            logger.error(f"Error during monitoring test: {e}", exc_info=True)
            
        finally:
            await market_data.close()
            
        logger.info("=== Testing Token Selection Logic ===")
        
        # Test the selection logic
        best_token = await db.get_best_token_for_trading(include_inactive_tokens=True)
        logger.info(f"Best token for trading: {best_token}")
        
        if best_token:
            logger.info(f"✅ Selection logic found: {best_token.mint}")
        else:
            logger.warning("❌ Selection logic returned None")
            
            # Debug why selection failed
            logger.info("=== Debugging Selection Criteria ===")
            logger.info(f"MONITORED_PROGRAMS_LIST: {settings.MONITORED_PROGRAMS_LIST}")
            
            # Check if any tokens match the criteria
            for i, token in enumerate(all_tokens[:5]):
                logger.info(f"Token {i+1}: {token.mint}")
                logger.info(f"  - overall_filter_passed: {token.overall_filter_passed}")
                logger.info(f"  - rugcheck_score: {token.rugcheck_score}")
                logger.info(f"  - volume_24h: {token.volume_24h}")
                logger.info(f"  - liquidity: {token.liquidity}")
                logger.info(f"  - pair_address: {token.pair_address}")
                logger.info(f"  - dex_id: {token.dex_id}")
                logger.info(f"  - dex_id in MONITORED_PROGRAMS_LIST: {token.dex_id in settings.MONITORED_PROGRAMS_LIST}")
                
    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
        
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(test_monitor_first_token()) 