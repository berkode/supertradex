#!/usr/bin/env python3
"""
Quick test: Run TokenScanner once, then test token selection and monitoring
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
from data.token_scanner import TokenScanner
from filters import FilterManager
from data.platform_tracker import PlatformTracker
import httpx
from solana.rpc.async_api import AsyncClient
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

async def test_scanner_and_selection():
    """Run scanner once, then test token selection and monitoring"""
    
    logger.info("=== Loading Environment ===")
    load_environment()
    
    logger.info("=== Loading Settings ===")
    settings = Settings()
    
    logger.info("=== Initializing Components ===")
    # Database
    db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
    
    # HTTP Client
    http_client = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT)
    
    # Solana Client  
    solana_client = AsyncClient(settings.SOLANA_RPC_URL, commitment=settings.SOLANA_COMMITMENT)
    
    # MarketData
    market_data = MarketData(settings=settings)
    
    # Initialize dependencies for FilterManager
    from config.thresholds import Thresholds
    from config.filters_config import FiltersConfig
    from filters.rugcheck_api import RugcheckAPI
    from filters.solsniffer_api import SolsnifferAPI
    from filters.twitter_check import TwitterCheck
    
    thresholds = Thresholds(settings=settings)
    filters_config = FiltersConfig(settings=settings, thresholds=thresholds)
    rugcheck_api = RugcheckAPI(settings=settings)
    solsniffer_api = SolsnifferAPI(settings=settings)
    twitter_check = TwitterCheck(settings=settings, thresholds=thresholds)
    await twitter_check.initialize()
    
    # FilterManager (properly initialized)
    filter_manager = FilterManager(
        settings=settings,
        thresholds=thresholds,
        filters_config=filters_config,
        db=db,
        http_client=http_client,
        solana_client=solana_client,
        price_monitor=market_data.price_monitor,
        rugcheck_api=rugcheck_api,
        solsniffer_api=solsniffer_api,
        twitter_check=twitter_check
    )
    
    # PlatformTracker
    platform_tracker = PlatformTracker(settings=settings)
    
    # TokenScanner
    token_scanner = TokenScanner(
        settings=settings,
        db=db,
        market_data=market_data,
        filter_manager=filter_manager,
        platform_tracker=platform_tracker
    )
    
    try:
        logger.info("=== Running TokenScanner Once ===")
        # Run one scan cycle
        await token_scanner.run_scan_once()
        
        logger.info("=== Checking Database After Scan ===")
        all_tokens = await db.get_tokens_list()
        logger.info(f"Total tokens in database after scan: {len(all_tokens)}")
        
        if all_tokens:
            logger.info("=== Sample Tokens ===")
            for i, token in enumerate(all_tokens[:3]):  # Show first 3 tokens
                logger.info(f"Token {i+1}: {token.mint}")
                logger.info(f"  - overall_filter_passed: {token.overall_filter_passed}")
                logger.info(f"  - rugcheck_score: {token.rugcheck_score}")
                logger.info(f"  - volume_24h: {token.volume_24h}")
                logger.info(f"  - liquidity: {token.liquidity}")
                logger.info(f"  - pair_address: {token.pair_address}")
                logger.info(f"  - dex_id: {token.dex_id}")
                logger.info(f"  - monitoring_status: {token.monitoring_status}")
                
        logger.info("=== Testing Token Selection ===")
        best_token = await db.get_best_token_for_trading(include_inactive_tokens=True)
        logger.info(f"Best token found: {best_token}")
        
        if best_token:
            logger.info(f"✅ Found best token: {best_token.mint}")
            logger.info(f"  - dex_id: {best_token.dex_id}")
            logger.info(f"  - pair_address: {best_token.pair_address}")
            
            logger.info("=== Testing MarketData Monitoring ===")
            try:
                # Test monitoring
                success = await market_data.start_monitoring_token(mint=best_token.mint)
                
                if success:
                    logger.info(f"✅ Successfully started monitoring {best_token.mint}")
                    
                    # Wait briefly for data
                    logger.info("Waiting 5 seconds for price data...")
                    await asyncio.sleep(5)
                    
                    # Check for price updates
                    price_data = market_data.get_realtime_pair_state(best_token.mint)
                    logger.info(f"Price data: {price_data}")
                    
                    # Stop monitoring
                    await market_data.stop_monitoring_token(best_token.mint)
                    logger.info(f"✅ Stopped monitoring {best_token.mint}")
                    
                else:
                    logger.error(f"❌ Failed to start monitoring {best_token.mint}")
                    
            except Exception as e:
                logger.error(f"Error during monitoring test: {e}", exc_info=True)
        else:
            logger.warning("❌ No best token found - checking selection criteria")
            
            # Check why no token was selected
            logger.info("MONITORED_PROGRAMS_LIST:")
            for program in settings.MONITORED_PROGRAMS_LIST:
                logger.info(f"  - {program}")
            
            if all_tokens:
                logger.info("Sample token dex_ids from database:")
                for token in all_tokens[:5]:
                    logger.info(f"  - {token.mint}: dex_id = {token.dex_id}")
                    
    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
        
    finally:
        logger.info("=== Cleanup ===")
        await token_scanner.close()
        await market_data.close()
        await filter_manager.close()
        await platform_tracker.close()
        await twitter_check.close()
        await http_client.aclose()
        await solana_client.close()
        await db.close()

if __name__ == "__main__":
    asyncio.run(test_scanner_and_selection()) 