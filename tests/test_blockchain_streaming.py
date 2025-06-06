#!/usr/bin/env python3
"""
Test real-time blockchain streaming with BlockchainListener for Raydium tokens
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
    """Load environment variables"""
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

def insert_raydium_test_token():
    """Insert a popular Raydium token for testing"""
    db_path = "outputs/supertradex.db"
    
    # Connect to SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Insert SOL token (native Solana) - very active on Raydium
        test_token = {
            'mint': 'So11111111111111111111111111111111111111112',  # SOL mint
            'symbol': 'SOL',
            'name': 'Solana',
            'overall_filter_passed': 1,
            'rugcheck_score': 10,
            'volume_24h': 50000000.0,  # High volume
            'liquidity': 10000000.0,   # High liquidity
            'pair_address': '58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2',  # SOL/USDC Raydium pool
            'dex_id': 'raydium_v4',
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
        logger.info(f"   Pair Address: {test_token['pair_address']}")
        logger.info(f"   DEX: {test_token['dex_id']}")
        return test_token
        
    except Exception as e:
        logger.error(f"❌ Failed to insert test token: {e}")
        return None
    finally:
        conn.close()

async def test_blockchain_streaming():
    """Test real-time blockchain streaming with BlockchainListener"""
    
    logger.info("=== Loading Environment ===")
    load_environment()
    
    logger.info("=== Loading Settings ===")
    settings = Settings()
    
    logger.info("=== Inserting Raydium Test Token ===")
    test_token = insert_raydium_test_token()
    if not test_token:
        logger.error("Failed to insert test token")
        return
        
    logger.info("=== Setting Up MarketData with BlockchainListener ===")
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
    
    # Initialize BlockchainListener for real-time monitoring
    await market_data.initialize_blockchain_listener()
    
    # Start BlockchainListener's run_forever() task to initialize TaskGroup
    blockchain_listener_task = None
    if market_data.blockchain_listener:
        logger.info("=== Starting BlockchainListener.run_forever() Task ===")
        blockchain_listener_task = asyncio.create_task(market_data.blockchain_listener.run_forever())
        # Give it a moment to start up
        await asyncio.sleep(2)
        logger.info("✅ BlockchainListener task started")
    
    try:
        logger.info("=== Starting Real-time Blockchain Streaming ===")
        
        # Use add_token_for_monitoring which does both PriceMonitor AND streaming
        success = await market_data.add_token_for_monitoring(
            mint=test_token['mint'],
            pair_address=test_token['pair_address'], 
            dex_id=test_token['dex_id']
        )
        
        if success:
            logger.info(f"✅ Successfully started streaming for {test_token['symbol']} ({test_token['mint']})")
            logger.info(f"   Monitoring pair: {test_token['pair_address']}")
            logger.info(f"   DEX: {test_token['dex_id']}")
            
            # Check if token is in actively streamed set
            is_streaming = test_token['mint'] in market_data.actively_streamed_mints
            logger.info(f"   Active streaming: {is_streaming}")
            
            # Wait for real-time blockchain events
            logger.info("=== Waiting for Real-time Blockchain Events ===")
            logger.info("⏳ Monitoring for 30 seconds for live blockchain updates...")
            
            # Monitor for events over time
            for i in range(6):  # 6 intervals of 5 seconds each = 30 seconds
                await asyncio.sleep(5)
                
                # Check real-time state
                pair_state = market_data._realtime_pair_state.get(test_token['pair_address'])
                if pair_state:
                    logger.info(f"🎯 Real-time state found for {test_token['symbol']}:")
                    logger.info(f"   Price: {pair_state.get('price', 'N/A')}")
                    logger.info(f"   Timestamp: {pair_state.get('timestamp', 'N/A')}")
                    logger.info(f"   Base Reserves: {pair_state.get('base_reserves', 'N/A')}")
                    logger.info(f"   Quote Reserves: {pair_state.get('quote_reserves', 'N/A')}")
                else:
                    logger.info(f"⏳ Waiting for real-time data... ({(i+1)*5}s elapsed)")
                
                # Check if we got any blockchain events via listener
                if hasattr(market_data, 'blockchain_listener') and market_data.blockchain_listener:
                    # Check if listener is connected and active
                    if hasattr(market_data.blockchain_listener, 'is_connected'):
                        connected = market_data.blockchain_listener.is_connected()
                        logger.info(f"   BlockchainListener connected: {connected}")
                    
                    # Check subscription status if available
                    if hasattr(market_data.blockchain_listener, 'get_subscription_status'):
                        status = market_data.blockchain_listener.get_subscription_status()
                        logger.info(f"   Subscriptions: {status}")
            
            logger.info("=== Testing Price Retrieval Methods ===")
            
            # Method 1: Real-time via _realtime_pair_state
            pair_state = market_data._realtime_pair_state.get(test_token['pair_address'])
            if pair_state:
                logger.info(f"✅ Real-time blockchain price: ${pair_state.get('price', 'N/A')}")
            else:
                logger.info("❌ No real-time blockchain data available")
            
            # Method 2: MarketData get_token_price (should prioritize real-time if available)
            market_price = await market_data.get_token_price(test_token['mint'])
            if market_price:
                logger.info(f"✅ MarketData price: ${market_price.get('price', 'N/A')} (source: {market_price.get('source', 'unknown')})")
            else:
                logger.info("❌ No market data price available")
            
            # Method 3: PriceMonitor fallback
            if hasattr(market_data.price_monitor, 'get_current_price_usd'):
                pm_price = await market_data.price_monitor.get_current_price_usd(test_token['mint'])
                if pm_price:
                    logger.info(f"✅ PriceMonitor fallback: ${pm_price}")
                else:
                    logger.info("❌ No PriceMonitor price available")
            
            # Stop streaming
            await market_data.stop_streaming(test_token['mint'])
            logger.info(f"✅ Stopped streaming for {test_token['symbol']}")
            
        else:
            logger.error(f"❌ Failed to start streaming for {test_token['symbol']}")
            
    except Exception as e:
        logger.error(f"Error during blockchain streaming test: {e}", exc_info=True)
        
    finally:
        # Stop the blockchain listener task first
        if blockchain_listener_task and not blockchain_listener_task.done():
            logger.info("Stopping BlockchainListener task...")
            blockchain_listener_task.cancel()
            try:
                await blockchain_listener_task
            except asyncio.CancelledError:
                logger.info("BlockchainListener task cancelled")
        
        await market_data.close()
        await db.close()
        await http_client.aclose()
        await solana_client.close()

if __name__ == "__main__":
    asyncio.run(test_blockchain_streaming()) 