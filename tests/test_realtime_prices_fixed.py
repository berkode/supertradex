#!/usr/bin/env python3
"""
Test real-time price monitoring with enhanced logging to verify fixes
"""

import asyncio
import sys
import os
import time
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup environment
from utils.encryption import decrypt_env_file, get_encryption_password
from dotenv import dotenv_values
import io

env_dir = project_root / "config"
env_encrypted_path = env_dir / ".env.encrypted"
if env_encrypted_path.exists():
    password = get_encryption_password()
    if password:
        decrypted_content = decrypt_env_file(env_encrypted_path, password)
        if decrypted_content:
            env_vars = dotenv_values(stream=io.StringIO(decrypted_content))
            for key, value in env_vars.items():
                if value and key not in os.environ:
                    os.environ[key] = str(value)

async def test_realtime_prices():
    """Test that real-time prices are now visible in logs"""
    print("🚀 TESTING REAL-TIME PRICE VISIBILITY")
    print("=" * 60)
    
    try:
        from config.settings import Settings
        from data.market_data import MarketData
        from data.token_database import TokenDatabase
        
        # Initialize components
        settings = Settings()
        token_db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
        await token_db.initialize()
        
        market_data = MarketData(settings, token_db=token_db)
        await market_data.initialize()
        
        print("✅ Components initialized")
        
        # Initialize blockchain listener
        await market_data.initialize_blockchain_listener()
        
        if not market_data.blockchain_listener:
            print("❌ Blockchain listener not initialized")
            return False
            
        print("✅ Blockchain listener initialized")
        
        # Get a token to monitor
        tokens = await token_db.get_valid_tokens()
        if not tokens:
            print("❌ No tokens found in database")
            return False
            
        test_token = None
        for token in tokens:
            if hasattr(token, 'pair_address') and hasattr(token, 'dex_id') and token.pair_address and token.dex_id:
                test_token = token
                break
                
        if not test_token:
            print("❌ No valid tokens found with pair_address and dex_id")
            return False
            
        print(f"📊 Testing with token: {test_token.symbol} ({test_token.mint[:8]}...)")
        print(f"🔗 Pair: {test_token.pair_address}")
        print(f"🏢 DEX: {test_token.dex_id}")
        print()
        
        # Start monitoring
        print("🚀 Starting real-time monitoring...")
        await market_data.start_streaming(test_token.mint, test_token.pair_address, test_token.dex_id)
        
        # Start blockchain listener
        listener_task = asyncio.create_task(market_data.blockchain_listener.run_forever())
        
        print("✅ Blockchain listener started")
        print("📱 Watching for real-time price updates in logs...")
        print("💡 Look for these log patterns:")
        print("   🔗 BLOCKCHAIN CONNECTION SUCCESS")
        print("   📡 BLOCKCHAIN EVENT")
        print("   📝 TRANSACTION LOGS")
        print("   💰 REALTIME PRICE")
        print("   ✅ EVENT FORWARDED")
        print()
        print("⏱️ Monitoring for 60 seconds...")
        print("=" * 60)
        
        # Monitor for 60 seconds
        start_time = time.time()
        while time.time() - start_time < 60:
            await asyncio.sleep(1)
            
            # Check if listener is still running
            if listener_task.done():
                print("❌ Blockchain listener stopped unexpectedly")
                break
                
        print("\n" + "=" * 60)
        print("🛑 Monitoring complete")
        
        # Stop streaming
        await market_data.stop_streaming(test_token.mint)
        
        # Cancel listener
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
            
        # Close resources
        await market_data.close()
        await token_db.close()
        
        print("✅ Test completed successfully")
        print()
        print("📋 What to check in the logs:")
        print("   1. No more flooding WebSocket status messages")
        print("   2. Clear blockchain connection success messages")
        print("   3. Visible transaction processing")
        print("   4. Prominent real-time price updates")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    asyncio.run(test_realtime_prices()) 