#!/usr/bin/env python3
"""
Quick Two Token Price Monitor - Shows results faster for testing
"""

import asyncio
import sys
import os
import time
import json
from pathlib import Path
from typing import Dict, Any, List

# Setup environment
sys.path.append(str(Path.cwd()))
from utils.encryption import decrypt_env_file, get_encryption_password
from dotenv import dotenv_values
import io

env_dir = Path('config')
env_encrypted_path = env_dir / '.env.encrypted'
if env_encrypted_path.exists():
    password = get_encryption_password()
    if password:
        decrypted_content = decrypt_env_file(env_encrypted_path, password)
        if decrypted_content:
            env_vars = dotenv_values(stream=io.StringIO(decrypted_content))
            for key, value in env_vars.items():
                if value and key not in os.environ:
                    os.environ[key] = str(value)

from config.settings import Settings
from data.market_data import MarketData
from data.token_database import TokenDatabase

# Global tracking
monitoring_stats = {
    'total_messages': 0,
    'price_updates': 0,
    'monitored_tokens': {},
    'start_time': time.time(),
    'token_info': {}
}

async def price_update_callback(data: Dict[str, Any]):
    """Callback to handle price updates for our monitored tokens"""
    global monitoring_stats
    
    monitoring_stats['total_messages'] += 1
    
    # Check if this is for one of our monitored tokens
    price = data.get('price')
    dex_id = data.get('dex_id', 'unknown')
    
    # Show every 10th message to see activity
    if monitoring_stats['total_messages'] % 10 == 0:
        print(f"📊 Message #{monitoring_stats['total_messages']} processed (from {dex_id})")
    
    # Log all price updates
    if price:
        monitoring_stats['price_updates'] += 1
        print(f"\n💰 PRICE UPDATE #{monitoring_stats['price_updates']}")
        print(f"   Price: ${price:.8f}")
        print(f"   DEX: {dex_id}")
        print(f"   Time: {time.time() - monitoring_stats['start_time']:.1f}s since start")

async def show_quick_stats():
    """Show quick statistics every 30 seconds"""
    global monitoring_stats
    
    while True:
        await asyncio.sleep(30)  # Every 30 seconds for quicker feedback
        
        current_time = time.time()
        runtime = current_time - monitoring_stats['start_time']
        
        print(f"\n" + "="*60)
        print(f"📊 QUICK MONITORING REPORT ({runtime/60:.1f} minutes)")
        print(f"="*60)
        
        print(f"📈 STATISTICS:")
        print(f"   Runtime: {runtime:.1f} seconds")
        print(f"   Total messages: {monitoring_stats['total_messages']}")
        print(f"   Price updates: {monitoring_stats['price_updates']}")
        print(f"   Messages/minute: {monitoring_stats['total_messages'] / (runtime / 60):.1f}")
        
        # Show tokens being monitored
        print(f"\n🪙 MONITORED TOKENS:")
        for token_mint, token_info in monitoring_stats['token_info'].items():
            print(f"   🎯 {token_info['symbol']} ({token_info['name']})")
            print(f"      Mint: {token_mint[:16]}...")
        
        # System health
        message_rate = monitoring_stats['total_messages'] / (runtime / 60) if runtime > 0 else 0
        status = "🟢 ACTIVE" if message_rate > 1 else "🟡 SLOW" if message_rate > 0 else "🔴 WAITING"
        print(f"\n⚡ STATUS: {status} ({message_rate:.1f} msg/min)")
        print(f"="*60)

async def main():
    print("🚀 QUICK TWO TOKEN PRICE MONITOR!")
    print("   📊 Fast testing version")
    print("   💰 Stats every 30 seconds")
    print("   🎯 Shows activity immediately")
    print()
    
    # Initialize
    settings = Settings()
    db_path = settings.DATABASE_FILE_PATH
    token_db = await TokenDatabase.create(db_path, settings)
    
    try:
        # Get first two tokens from database
        all_tokens = await token_db.get_tokens_list()
        
        if len(all_tokens) < 2:
            print(f"❌ Need at least 2 tokens in database, found {len(all_tokens)}")
            if all_tokens:
                print("   Available tokens:")
                for token in all_tokens:
                    print(f"      {token.symbol} - {token.mint}")
            return
        
        # Select first two tokens
        selected_tokens = all_tokens[:2]
        
        print(f"✅ SELECTED TOKENS:")
        for i, token in enumerate(selected_tokens, 1):
            print(f"   {i}. {token.symbol} ({token.name})")
            print(f"      Mint: {token.mint}")
            print(f"      DEX: {token.dex_id}")
            print(f"      Status: {token.monitoring_status}")
            
            # Store token info
            monitoring_stats['token_info'][token.mint] = {
                'symbol': token.symbol,
                'name': token.name,
                'mint': token.mint,
                'dex_id': token.dex_id
            }
        print()
        
        # Initialize market data and blockchain listener
        print("🔄 Initializing market data...")
        market_data = MarketData(settings)
        await market_data.initialize()
        
        print("🔗 Initializing blockchain listener...")
        await market_data.initialize_blockchain_listener()
        
        blockchain_listener = market_data.blockchain_listener
        if not blockchain_listener:
            raise RuntimeError("Failed to initialize blockchain listener")
        
        # Set our callback
        blockchain_listener.set_callback(price_update_callback)
        
        print(f"✅ QUICK MONITORING STARTED!")
        print(f"   🔗 Blockchain listener active")
        print(f"   🎯 Tracking {len(selected_tokens)} tokens")
        print(f"   ⏰ Stats every 30 seconds")
        print(f"   🛑 Press Ctrl+C to stop")
        print()
        
        monitoring_stats['start_time'] = time.time()
        
        # Start monitoring
        await asyncio.gather(
            blockchain_listener.run_forever(),
            show_quick_stats()
        )
        
    except KeyboardInterrupt:
        print(f"\n🛑 Quick monitor stopped by user")
    except Exception as e:
        print(f"\n❌ Monitor error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            print(f"\n🔄 Shutting down...")
            if 'market_data' in locals():
                await market_data.close()
            if 'token_db' in locals():
                await token_db.close()
        except Exception as e:
            print(f"⚠️  Error during shutdown: {e}")
        
        # Final report
        runtime = time.time() - monitoring_stats['start_time']
        print(f"\n🎯 FINAL QUICK REPORT")
        print(f"   Duration: {runtime:.1f} seconds")
        print(f"   Messages: {monitoring_stats['total_messages']}")
        print(f"   Price updates: {monitoring_stats['price_updates']}")
        print(f"🏁 Done!")

if __name__ == "__main__":
    asyncio.run(main()) 