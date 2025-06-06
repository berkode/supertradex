#!/usr/bin/env python3
"""
Test REAL-TIME blockchain price monitoring using BlockchainListener.
This script shows WebSocket-based real-time price updates from Solana blockchain.
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
                if key not in os.environ:
                    os.environ[key] = value

from data.token_database import TokenDatabase
from data.blockchain_listener import BlockchainListener
from config.settings import Settings

async def blockchain_event_callback(event_data):
    """Callback function to handle blockchain events and display real-time prices."""
    try:
        event_type = event_data.get("type")
        program_id = event_data.get("program_id", "unknown")[:8]
        signature = event_data.get("signature", "unknown")[:8]
        log_count = event_data.get("log_count", 0)
        has_swap = event_data.get("has_swap_activity", False)
        
        print(f"🔥 BLOCKCHAIN EVENT: Program {program_id}... | TX {signature}... | {log_count} logs | Swap: {has_swap}")
        
        # Log the raw logs for debugging
        logs = event_data.get("logs", [])
        if logs:
            print(f"   📄 Transaction logs preview:")
            for i, log in enumerate(logs[:3]):  # Show first 3 logs
                print(f"      {i+1}. {log[:100]}{'...' if len(log) > 100 else ''}")
        
    except Exception as e:
        print(f"❌ Error in blockchain event callback: {e}")

async def test_blockchain_realtime_monitoring():
    print("🚀 REAL-TIME BLOCKCHAIN PRICE MONITORING TEST")
    print("=" * 70)
    print("🎯 This test uses ACTUAL BlockchainListener for WebSocket-based monitoring")
    print()
    
    # Initialize components
    settings = Settings()
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await db.initialize()
    
    print("📊 Finding suitable token for testing...")
    
    # Get tokens with complete data
    tokens = await db.get_valid_tokens()
    complete_tokens = [token for token in tokens if token.pair_address and token.dex_id]
    
    if not complete_tokens:
        print("❌ No tokens with complete data found!")
        await db.close()
        return
    
    # Select BONK token if available, otherwise first available token
    test_token = None
    for token in complete_tokens:
        if token.symbol.upper() == "BONK":
            test_token = token
            break
    
    if not test_token:
        test_token = complete_tokens[0]
    
    print(f"✅ Selected token: {test_token.symbol} ({test_token.mint[:8]}...)")
    print(f"   DEX: {test_token.dex_id}")
    print(f"   Pair: {test_token.pair_address[:8]}...")
    print()
    
    # Initialize BlockchainListener
    print("🚀 Initializing BlockchainListener for real-time monitoring...")
    
    # Create HTTP client for BlockchainListener
    import httpx
    http_client = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT)
    
    # Initialize BlockchainListener
    blockchain_listener = BlockchainListener(
        settings=settings,
        callback=blockchain_event_callback,
        http_client=http_client
    )
    
    # Set the callback explicitly
    blockchain_listener.set_callback(blockchain_event_callback)
    
    if not await blockchain_listener.initialize():
        print("❌ Failed to initialize BlockchainListener")
        await http_client.aclose()
        await db.close()
        return
    
    print("✅ BlockchainListener initialized successfully!")
    print()
    
    # Add specific token to monitoring
    print(f"📈 Adding {test_token.symbol} to real-time blockchain monitoring...")
    
    await blockchain_listener.add_token_to_monitor(
        mint_address=test_token.mint,
        pair_address=test_token.pair_address,
        dex_id=test_token.dex_id
    )
    
    print(f"✅ {test_token.symbol} added to blockchain monitoring")
    print()
    print("🎯 REAL-TIME BLOCKCHAIN MONITORING ACTIVE")
    print("   🔗 WebSocket connections to Solana blockchain established")
    print("   📡 Listening for transaction logs in real-time")
    print("   💰 Price updates will appear as '💰 REALTIME PRICE UPDATE' messages")
    print("   🔥 Blockchain events will appear as '🔥 BLOCKCHAIN EVENT' messages")
    print()
    print("Press Ctrl+C to stop monitoring...")
    print("=" * 70)
    
    try:
        # Start the main blockchain listening loop
        print("🎧 Starting blockchain listener main loop...")
        
        # Run the blockchain listener in the background
        listener_task = asyncio.create_task(blockchain_listener.run_forever())
        
        # Keep the test running for a reasonable time or until interrupted
        start_time = time.time()
        max_runtime = 300  # 5 minutes
        
        print(f"⏱️  Test will run for up to {max_runtime//60} minutes...")
        print("   🔍 Watch the logs above for real-time blockchain events!")
        print()
        
        while time.time() - start_time < max_runtime:
            elapsed = time.time() - start_time
            
            # Show periodic status
            if int(elapsed) % 30 == 0 and int(elapsed) > 0:  # Every 30 seconds
                print(f"📊 Status update: {elapsed:.0f}s elapsed | Monitoring active | Waiting for blockchain events...")
            
            await asyncio.sleep(5)  # Check every 5 seconds
            
            # Check if listener task is still running
            if listener_task.done():
                exception = listener_task.exception()
                if exception:
                    print(f"❌ BlockchainListener task failed: {exception}")
                    break
                else:
                    print("⚠️ BlockchainListener task completed unexpectedly")
                    break
        
        print(f"\n⏰ Test completed after {time.time() - start_time:.1f} seconds")
        
    except KeyboardInterrupt:
        print(f"\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Error during monitoring: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 Cleaning up...")
        
        # Stop BlockchainListener
        try:
            await blockchain_listener.close()
            print("✅ BlockchainListener closed")
        except Exception as e:
            print(f"⚠️ Error closing BlockchainListener: {e}")
        
        # Close HTTP client
        try:
            await http_client.aclose()
            print("✅ HTTP client closed")
        except Exception as e:
            print(f"⚠️ Error closing HTTP client: {e}")
        
        # Close database
        try:
            await db.close()
            print("✅ Database closed")
        except Exception as e:
            print(f"⚠️ Error closing database: {e}")
        
        print("✅ Cleanup complete!")

if __name__ == "__main__":
    try:
        asyncio.run(test_blockchain_realtime_monitoring())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback
        traceback.print_exc() 