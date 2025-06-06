#!/usr/bin/env python3
"""
Direct test: Insert a token manually and test monitoring (bypass app initialization)
"""
import asyncio
import sys
import os
import sqlite3
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from utils.encryption import decrypt_env_file, get_encryption_password
from config.settings import Settings, EncryptionSettings
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

def insert_test_token():
    """Insert a test token directly into the database"""
    db_path = "outputs/supertradex.db"
    
    # Connect to SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Insert a test token with known good values
        test_token = {
            'mint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC mint for testing
            'symbol': 'USDC',
            'name': 'USD Coin',
            'overall_filter_passed': 1,
            'rugcheck_score': 10,
            'volume_24h': 1000000.0,
            'liquidity': 500000.0,
            'pair_address': 'test_pair_address_123',
            'dex_id': 'raydium_v4',  # Valid DEX ID
            'monitoring_status': 'pending'
        }
        
        # Insert the token
        cursor.execute("""
            INSERT OR REPLACE INTO tokens 
            (mint, symbol, name, overall_filter_passed, rugcheck_score, 
             volume_24h, liquidity, pair_address, dex_id, monitoring_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            test_token['mint'], test_token['symbol'], test_token['name'],
            test_token['overall_filter_passed'], test_token['rugcheck_score'],
            test_token['volume_24h'], test_token['liquidity'], 
            test_token['pair_address'], test_token['dex_id'], test_token['monitoring_status']
        ))
        
        conn.commit()
        logger.info(f"✅ Inserted test token: {test_token['mint']} ({test_token['symbol']})")
        return test_token
        
    except Exception as e:
        logger.error(f"❌ Failed to insert test token: {e}")
        return None
    finally:
        conn.close()

async def test_direct_monitoring():
    """Test monitoring without full database initialization"""
    
    logger.info("=== Loading Environment ===")
    load_environment()
    
    logger.info("=== Loading Settings ===")
    settings = Settings()
    
    logger.info("=== Inserting Test Token ===")
    test_token = insert_test_token()
    if not test_token:
        logger.error("Failed to insert test token")
        return
        
    logger.info("=== Verifying Token in Database ===")
    conn = sqlite3.connect("outputs/supertradex.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tokens")
    count = cursor.fetchone()[0]
    logger.info(f"Total tokens in database: {count}")
    conn.close()
    
    logger.info("=== Testing MarketData Monitoring ===")
    # Initialize MarketData with all required dependencies
    import httpx
    from solana.rpc.async_api import AsyncClient
    from data.token_database import TokenDatabase
    
    # Create required clients
    http_client = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT)
    solana_client = AsyncClient(settings.SOLANA_RPC_URL, commitment=settings.SOLANA_COMMITMENT)
    
    # Create a minimal TokenDatabase for MarketData
    db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
    
    # Initialize MarketData properly
    market_data = MarketData(
        settings=settings, 
        token_db=db, 
        http_client=http_client, 
        solana_client=solana_client
    )
    
    # Initialize MarketData (this sets up all internal components)
    await market_data.initialize()
    
    try:
        # Test if we can start monitoring this token
        success = await market_data.start_monitoring_token(mint=test_token['mint'])
        
        if success:
            logger.info(f"✅ Successfully started monitoring {test_token['mint']}")
            
            # Wait for some price data
            logger.info("Waiting 10 seconds for price data...")
            await asyncio.sleep(10)
            
            # Check monitoring status
            monitoring_status = await market_data.get_current_monitoring_status()
            logger.info(f"Monitoring status: {monitoring_status}")
            
            # Check if we got any price updates from PriceMonitor
            if hasattr(market_data.price_monitor, 'get_current_price_usd'):
                current_price = await market_data.price_monitor.get_current_price_usd(test_token['mint'])
                logger.info(f"Current price from PriceMonitor: {current_price}")
            else:
                logger.info("PriceMonitor.get_current_price_usd method not available")
            
            # Get general market data
            market_info = await market_data.get_token_price(test_token['mint'])
            logger.info(f"Market info: {market_info}")
            
            # Stop monitoring
            await market_data.stop_monitoring_token(test_token['mint'])
            logger.info(f"✅ Stopped monitoring {test_token['mint']}")
            
        else:
            logger.error(f"❌ Failed to start monitoring {test_token['mint']}")
            
            # Try to get basic price info without monitoring
            logger.info("Trying to get basic price info without real-time monitoring...")
            basic_price = await market_data.get_token_price(test_token['mint'])
            logger.info(f"Basic price info: {basic_price}")
            
    except Exception as e:
        logger.error(f"Error during monitoring test: {e}", exc_info=True)
        
    finally:
        await market_data.close()
        await db.close()
        await http_client.aclose()
        await solana_client.close()

if __name__ == "__main__":
    asyncio.run(test_direct_monitoring()) 