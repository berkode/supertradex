#!/usr/bin/env python3
"""
Test script to monitor a specific token and see real-time blockchain updates
"""

import asyncio
import logging
import os
import io
from pathlib import Path
from datetime import datetime, timezone
from config.settings import Settings, EncryptionSettings
from data.market_data import MarketData
from data.token_database import TokenDatabase
from data.blockchain_listener import BlockchainListener
from utils.logger import get_logger
from utils.encryption import decrypt_env_file, get_encryption_password
from dotenv import load_dotenv, dotenv_values

def load_environment():
    """Load environment variables (like main.py logic)"""
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
                print(f"Loaded {len(loaded_vars)} variables from encrypted file")
    except Exception as e:
        print(f"Could not load encrypted file: {e}")
    
    # Load plain .env file
    if env_plain_path.exists():
        load_dotenv(dotenv_path=env_plain_path, override=True)
        print("Loaded plain .env file")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = get_logger(__name__)

# Example token to monitor (JOJO from the config docs)
TEST_TOKEN = {
    'mint': '7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij',
    'symbol': 'JOJO',
    'name': 'JOJO',
    'dex_id': 'raydium_v4',  # This token has a Raydium pool
    'pair_address': 'GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL'  # Raydium CPMM Pool
}

# Alternative Pump.fun only token for testing
PUMP_TOKEN = {
    'mint': '6pwrctNrXweLQDtQAz9XYwqu3GK87wRkn9GrrXLqpump',
    'symbol': 'REPO',
    'name': 'REPO',
    'dex_id': 'pumpfun'
}

async def monitor_token_realtime(token_info: dict, duration_seconds: int = 60):
    """
    Monitor a token in real-time and display blockchain updates
    
    Args:
        token_info: Token information dictionary
        duration_seconds: How long to monitor (default 60 seconds)
    """
    logger.info(f"🚀 Starting real-time monitoring for {token_info['symbol']} ({token_info['mint']})")
    logger.info(f"   Duration: {duration_seconds} seconds")
    logger.info(f"   DEX: {token_info['dex_id']}")
    if 'pair_address' in token_info:
        logger.info(f"   Pair Address: {token_info['pair_address']}")
    
    # Load environment before initializing Settings
    load_environment()
    
    # Initialize components
    settings = Settings()
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    market_data = MarketData(settings, db)
    
    try:
        # Start monitoring system
        await market_data.initialize()
        logger.info("✅ MarketData initialized")
        
        # Start monitoring to initialize blockchain listener
        await market_data.start_monitoring()
        logger.info("✅ Started monitoring (including blockchain listener)")
        
        # CRITICAL: Start BlockchainListener's run_forever() task to initialize TaskGroup
        blockchain_listener_task = None
        if market_data.blockchain_listener:
            logger.info("🚀 Starting BlockchainListener.run_forever() task...")
            blockchain_listener_task = asyncio.create_task(market_data.blockchain_listener.run_forever())
            # Give it a moment to initialize the TaskGroup
            await asyncio.sleep(2)
            logger.info("✅ BlockchainListener TaskGroup initialized")
        
        # Add token for monitoring
        if token_info['dex_id'] == 'pumpfun':
            # For Pump.fun tokens, we derive the bonding curve address
            from filters.bonding_curve import BondingCurveCalculator
            bonding_curve_calculator = BondingCurveCalculator(None, settings)
            pair_address = bonding_curve_calculator.derive_bonding_curve_address(token_info['mint'])
            logger.info(f"📊 Derived bonding curve address: {pair_address}")
            
            success = await market_data.add_token_for_monitoring(
                mint=token_info['mint'],
                pair_address=pair_address,
                dex_id=token_info['dex_id']
            )
        else:
            # For AMM tokens, use the provided pair address
            success = await market_data.add_token_for_monitoring(
                mint=token_info['mint'],
                pair_address=token_info['pair_address'],
                dex_id=token_info['dex_id']
            )
        
        if success:
            logger.info(f"✅ Successfully started monitoring {token_info['symbol']}")
        else:
            logger.error(f"❌ Failed to start monitoring {token_info['symbol']}")
            return
        
        # Monitor for the specified duration
        logger.info("=" * 80)
        logger.info("🎯 REAL-TIME MONITORING ACTIVE - Watching for blockchain events...")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        last_update_time = start_time
        update_count = 0
        
        for i in range(duration_seconds):
            await asyncio.sleep(1)
            current_time = datetime.now()
            
            # Check real-time state
            pair_address_for_check = token_info.get('pair_address')
            if token_info['dex_id'] == 'pumpfun':
                pair_address_for_check = bonding_curve_calculator.derive_bonding_curve_address(token_info['mint'])
            
            if pair_address_for_check and pair_address_for_check in market_data._realtime_pair_state:
                pair_state = market_data._realtime_pair_state[pair_address_for_check]
                
                # Check if this is a new update
                state_timestamp = pair_state.get('timestamp')
                if state_timestamp and state_timestamp != last_update_time:
                    update_count += 1
                    last_update_time = state_timestamp
                    
                    logger.info("🔥 LIVE UPDATE DETECTED!")
                    logger.info(f"   Time: {state_timestamp}")
                    logger.info(f"   Price: {pair_state.get('price', 'N/A')}")
                    logger.info(f"   Base Reserves: {pair_state.get('base_reserves', 'N/A')}")
                    logger.info(f"   Quote Reserves: {pair_state.get('quote_reserves', 'N/A')}")
                    if 'virtual_sol_reserves' in pair_state:
                        logger.info(f"   Virtual SOL Reserves: {pair_state.get('virtual_sol_reserves', 'N/A')}")
                        logger.info(f"   Virtual Token Reserves: {pair_state.get('virtual_token_reserves', 'N/A')}")
                    logger.info("-" * 60)
            
            # Show progress every 10 seconds
            if (i + 1) % 10 == 0:
                elapsed = (current_time - start_time).total_seconds()
                logger.info(f"⏱️  Monitoring progress: {elapsed:.0f}s elapsed, {update_count} updates received")
        
        # Final summary
        logger.info("=" * 80)
        logger.info("📊 MONITORING SUMMARY")
        logger.info(f"   Token: {token_info['symbol']} ({token_info['mint']})")
        logger.info(f"   Duration: {duration_seconds} seconds")
        logger.info(f"   Total Updates: {update_count}")
        logger.info(f"   Update Rate: {update_count/duration_seconds:.2f} updates/second")
        
        # Check final state
        if pair_address_for_check and pair_address_for_check in market_data._realtime_pair_state:
            final_state = market_data._realtime_pair_state[pair_address_for_check]
            logger.info(f"   Final Price: {final_state.get('price', 'N/A')}")
            logger.info(f"   Final Timestamp: {final_state.get('timestamp', 'N/A')}")
        
        # Check blockchain listener status
        if hasattr(market_data, 'blockchain_listener') and market_data.blockchain_listener:
            listener = market_data.blockchain_listener
            if hasattr(listener, '_message_count'):
                logger.info(f"   Total Messages Received: {listener._message_count}")
            if hasattr(listener, 'ws_connections'):
                active_connections = sum(1 for ws in listener.ws_connections.values() if ws and listener._is_connection_open(ws))
                logger.info(f"   Active WebSocket Connections: {active_connections}")
        
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"Error during monitoring: {e}", exc_info=True)
    
    finally:
        # Clean shutdown
        try:
            if market_data:
                await market_data.stop_streaming(token_info['mint'])
                logger.info("✅ Stopped token streaming")
                
            # Clean up blockchain listener task
            if 'blockchain_listener_task' in locals() and blockchain_listener_task and not blockchain_listener_task.done():
                logger.info("🛑 Stopping BlockchainListener task...")
                if market_data.blockchain_listener:
                    await market_data.blockchain_listener.close()
                blockchain_listener_task.cancel()
                try:
                    await blockchain_listener_task
                except asyncio.CancelledError:
                    pass
                logger.info("✅ BlockchainListener task stopped")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

async def main():
    """Main function to run the monitoring test"""
    print("🔍 Real-time Token Monitoring Test")
    print("="*50)
    
    # Automatically select the Raydium token for demonstration
    token = TEST_TOKEN
    duration = 30  # Monitor for 30 seconds
    
    print(f"🎯 Monitoring: {token['symbol']} ({token['dex_id']}) for {duration} seconds")
    print("Starting monitoring...\n")
    
    await monitor_token_realtime(token, duration)

if __name__ == "__main__":
    asyncio.run(main()) 