#!/usr/bin/env python3
"""
Simple test for real-time price monitoring using PriceMonitor (fallback system).
This test will show that the system can monitor tokens and fetch real-time prices.
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
from data.price_monitor import PriceMonitor
from config.settings import Settings
from config.dexscreener_api import DexScreenerAPI

async def test_realtime_price_monitoring():
    print("🔥 REAL-TIME PRICE MONITORING TEST (PriceMonitor)")
    print("=" * 60)
    
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
    
    # Initialize DexScreenerAPI client
    print("🚀 Initializing DexScreenerAPI and PriceMonitor...")
    
    dex_api = DexScreenerAPI(settings=settings)
    await dex_api.initialize()
    
    # Create HTTP client for PriceMonitor
    import httpx
    http_client = httpx.AsyncClient(timeout=30)
    
    # Initialize PriceMonitor with correct parameters
    price_monitor = PriceMonitor(
        settings=settings,
        dex_api_client=dex_api,
        http_client=http_client,
        db=db
    )
    
    await price_monitor.initialize()
    
    print("✅ PriceMonitor initialized successfully!")
    print()
    
    # Add token to monitoring
    print(f"📈 Adding {test_token.symbol} to real-time price monitoring...")
    
    price_monitor.add_token(test_token.mint)
    
    print(f"✅ {test_token.symbol} added to PriceMonitor")
    print()
    print("🎯 REAL-TIME PRICE MONITORING ACTIVE")
    print("   📈 PriceMonitor will fetch prices every 15 seconds (default)")
    print("   💰 Look for price updates in the output below")
    print()
    print("Press Ctrl+C to stop monitoring...")
    print("=" * 60)
    
    try:
        # Monitor for price updates for a reasonable time
        start_time = time.time()
        max_runtime = 120  # 2 minutes
        check_interval = 5  # Check every 5 seconds
        
        last_price = None
        price_updates_count = 0
        
        while time.time() - start_time < max_runtime:
            # Get current price for the token
            current_price = await price_monitor.get_current_price_usd(test_token.mint)
            
            if current_price is not None:
                if last_price is None:
                    print(f"💰 INITIAL PRICE: {test_token.symbol} = ${current_price:.8f}")
                    last_price = current_price
                    price_updates_count += 1
                elif abs(current_price - last_price) > 0.000001:  # Detect price changes
                    change = ((current_price - last_price) / last_price) * 100
                    direction = "📈" if current_price > last_price else "📉"
                    print(f"💰 PRICE UPDATE: {test_token.symbol} = ${current_price:.8f} {direction} ({change:+.2f}%)")
                    last_price = current_price
                    price_updates_count += 1
            
            # Show heartbeat
            elapsed = time.time() - start_time
            if int(elapsed) % 15 == 0:  # Every 15 seconds
                price_history = price_monitor.get_price_history(test_token.mint)
                print(f"⏱️  {elapsed:.0f}s elapsed | {price_updates_count} price updates | {len(price_history)} data points stored")
            
            await asyncio.sleep(check_interval)
        
        print(f"\n⏰ Test completed after {time.time() - start_time:.1f} seconds")
        print(f"📊 Total price updates: {price_updates_count}")
        
        # Show final price history
        price_history = price_monitor.get_price_history(test_token.mint)
        if price_history:
            print(f"📈 Price history ({len(price_history)} entries):")
            for i, (timestamp, price) in enumerate(price_history[-5:]):  # Show last 5 entries
                time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
                print(f"   {i+1}. {time_str}: ${price:.8f}")
        
    except KeyboardInterrupt:
        print(f"\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Error during monitoring: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 Cleaning up...")
        
        # Remove token from monitoring (if method exists)
        try:
            if hasattr(price_monitor, 'remove_token'):
                price_monitor.remove_token(test_token.mint)
            elif hasattr(price_monitor, 'stop_monitoring'):
                await price_monitor.stop_monitoring(test_token.mint)
        except Exception as e:
            print(f"Note: Could not remove token from monitoring: {e}")
        
        # Close PriceMonitor
        await price_monitor.close()
        
        # Close HTTP client
        await http_client.aclose()
        
        # Close DexScreener API
        await dex_api.close()
        
        # Close database
        await db.close()
        
        print("✅ Cleanup complete!")

if __name__ == "__main__":
    try:
        asyncio.run(test_realtime_price_monitoring())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback
        traceback.print_exc() 