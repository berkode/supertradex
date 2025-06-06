#!/usr/bin/env python3
"""
Enhanced BONK Token Real-time Monitor with Detailed Message Analysis
Shows what blockchain messages we're receiving and extracts price data.
"""

import asyncio
import sys
import os
import time
import json
from pathlib import Path
from typing import Dict, Any

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

# Global stats
stats = {
    'total_messages': 0,
    'message_types': {},
    'price_updates': 0,
    'bonk_events': 0,
    'start_time': time.time()
}

async def detailed_message_callback(data: Dict[str, Any]):
    """Enhanced callback that analyzes all blockchain messages in detail"""
    global stats
    
    stats['total_messages'] += 1
    message_type = data.get('type', 'unknown')
    stats['message_types'][message_type] = stats['message_types'].get(message_type, 0) + 1
    
    print(f"\n🔄 Message #{stats['total_messages']} - Type: {message_type}")
    
    # Show basic message info
    if 'pool_address' in data:
        pool_addr = data['pool_address'][:8] + "..."
        print(f"   Pool: {pool_addr}")
    
    if 'dex_id' in data:
        print(f"   DEX: {data['dex_id']}")
    
    if 'signature' in data:
        sig = data['signature']
        if sig:
            print(f"   Signature: {sig[:8]}...")
    
    if 'slot' in data:
        print(f"   Slot: {data['slot']}")
    
    # Check for price information
    if 'price' in data:
        price = data['price']
        stats['price_updates'] += 1
        print(f"   💰 PRICE FOUND: {price}")
        
        # Check if this could be BONK related
        pool_address = data.get('pool_address', '')
        if pool_address:
            print(f"   🎯 Pool Address: {pool_address}")
            stats['bonk_events'] += 1
    
    # Show logs if available
    if 'logs' in data:
        logs = data['logs']
        if logs:
            print(f"   📝 Logs: {len(logs)} entries")
            for i, log in enumerate(logs[:3]):  # Show first 3 logs
                if log and len(log) > 10:
                    print(f"      Log {i+1}: {log[:50]}...")
    
    # Show raw data info if available
    if 'raw_data' in data:
        raw_data = data['raw_data']
        if raw_data:
            print(f"   📦 Raw data: {len(raw_data) if isinstance(raw_data, list) else 'present'}")
    
    # Check for specific BONK-related information
    if any(key in data for key in ['token_reserve_raw', 'sol_reserve_raw', 'liquidity_sol']):
        print(f"   🪙 Liquidity data detected!")
        if 'liquidity_sol' in data:
            print(f"      SOL Liquidity: {data['liquidity_sol']}")
        if 'token_reserve_raw' in data:
            print(f"      Token Reserve: {data['token_reserve_raw']}")
    
    # Show ALL available fields for debugging
    print(f"   🔍 All fields: {list(data.keys())}")
    
    # Check if there are any numeric values that might be prices
    for key, value in data.items():
        if isinstance(value, (int, float)) and value > 0:
            if key not in ['slot', 'timestamp', 'subscription_id']:
                print(f"      {key}: {value}")
    
    print(f"   ⏱️  Processing time: {time.time() - stats['start_time']:.1f}s since start")

async def show_stats():
    """Show detailed statistics periodically"""
    global stats
    
    while True:
        await asyncio.sleep(60)  # Show stats every 60 seconds
        
        runtime = time.time() - stats['start_time']
        print(f"\n📊 === DETAILED MONITOR STATS ({runtime:.1f}s runtime) ===")
        print(f"   Total Messages Processed: {stats['total_messages']}")
        print(f"   Price Updates Found: {stats['price_updates']}")
        print(f"   BONK Events: {stats['bonk_events']}")
        print(f"   Messages/minute: {stats['total_messages'] / (runtime / 60):.1f}")
        
        if stats['message_types']:
            print(f"   Message Types:")
            for msg_type, count in stats['message_types'].items():
                print(f"      {msg_type}: {count}")
        
        print(f"   ⚡ System is actively monitoring blockchain...")

async def main():
    print("🚀 Starting Enhanced BONK Token Monitor")
    print("   This monitor shows detailed blockchain message analysis")
    print("   Looking for price updates and BONK-related events...")
    
    # Initialize settings and database
    settings = Settings()
    db_path = settings.DATABASE_FILE_PATH
    token_db = await TokenDatabase.create(db_path, settings)
    
    try:
        # Get BONK token info
        bonk_tokens = await token_db.get_tokens_list({"symbol": "BONK"})
        if not bonk_tokens:
            print("❌ No BONK tokens found in database")
            return
        
        bonk_token = bonk_tokens[0]
        print(f"✅ Found BONK token: {bonk_token.symbol}")
        print(f"   Mint: {bonk_token.mint}")
        print(f"   Name: {bonk_token.name}")
        
        # Initialize market data with enhanced callback
        market_data = MarketData(settings)
        await market_data.initialize()
        
        # Initialize the blockchain listener specifically
        await market_data.initialize_blockchain_listener()
        
        # Set up the enhanced callback for blockchain events
        blockchain_listener = market_data.blockchain_listener
        if not blockchain_listener:
            raise RuntimeError("Failed to initialize blockchain listener")
        
        blockchain_listener.set_callback(detailed_message_callback)
        
        print(f"🔗 Blockchain listener initialized and monitoring...")
        print(f"   Listening on multiple DEX programs")
        print(f"   Enhanced analysis enabled for all messages")
        print(f"   Press Ctrl+C to stop monitoring\n")
        
        # Start monitoring with enhanced feedback
        stats['start_time'] = time.time()
        
        await asyncio.gather(
            blockchain_listener.run_forever(),
            show_stats()
        )
        
    except KeyboardInterrupt:
        print(f"\n⏹️  Monitor stopped by user")
    except Exception as e:
        print(f"\n❌ Error in enhanced monitor: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            print(f"\n🔄 Shutting down enhanced monitor...")
            if 'market_data' in locals():
                await market_data.close()
            if 'token_db' in locals():
                await token_db.close()
        except Exception as e:
            print(f"⚠️  Error during shutdown: {e}")
        
        # Final comprehensive stats
        runtime = time.time() - stats['start_time']
        print(f"\n📈 === FINAL ENHANCED ANALYSIS ===")
        print(f"   Total Runtime: {runtime/60:.1f} minutes")
        print(f"   Total Messages: {stats['total_messages']}")
        print(f"   Price Updates: {stats['price_updates']}")
        print(f"   BONK Events: {stats['bonk_events']}")
        print(f"   Messages per minute: {stats['total_messages'] / (runtime / 60):.1f}")
        
        if stats['message_types']:
            print(f"   Message breakdown:")
            for msg_type, count in stats['message_types'].items():
                percentage = (count / stats['total_messages']) * 100
                print(f"      {msg_type}: {count} ({percentage:.1f}%)")
        
        print("✅ Enhanced BONK monitor analysis complete")

if __name__ == "__main__":
    asyncio.run(main()) 