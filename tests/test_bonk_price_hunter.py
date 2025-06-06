#!/usr/bin/env python3
"""
BONK Price Hunter - Aggressive Real-time Price Detection
Specifically hunts for BONK prices with detailed debugging
"""

import asyncio
import sys
import os
import time
import json
from pathlib import Path
from typing import Dict, Any, Set

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
tracking = {
    'total_messages': 0,
    'message_types': {},
    'price_updates': 0,
    'bonk_mentions': 0,
    'pool_addresses_seen': set(),
    'signatures_seen': set(),
    'start_time': time.time(),
    'last_price': None,
    'last_price_time': None,
    'dex_activity': {},
    'raw_data_messages': 0,
    'log_messages': 0,
    'account_messages': 0
}

# Known BONK mint address
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

async def aggressive_bonk_callback(data: Dict[str, Any]):
    """Aggressive callback that hunts for any BONK-related price data"""
    global tracking
    
    tracking['total_messages'] += 1
    message_type = data.get('type', 'unknown')
    tracking['message_types'][message_type] = tracking['message_types'].get(message_type, 0) + 1
    
    # Track DEX activity
    dex_id = data.get('dex_id', 'unknown')
    tracking['dex_activity'][dex_id] = tracking['dex_activity'].get(dex_id, 0) + 1
    
    # Track message types
    if message_type == 'account_update':
        tracking['account_messages'] += 1
    elif message_type == 'log_update':
        tracking['log_messages'] += 1
    
    if 'raw_data' in data:
        tracking['raw_data_messages'] += 1
    
    # Track pool addresses and signatures
    if 'pool_address' in data:
        tracking['pool_addresses_seen'].add(data['pool_address'])
    
    if 'signature' in data and data['signature']:
        tracking['signatures_seen'].add(data['signature'])
    
    # 🎯 PRICE HUNTING - Check for ANY price-related data
    price_found = False
    current_price = None
    
    if 'price' in data and data['price']:
        current_price = data['price']
        price_found = True
        tracking['price_updates'] += 1
        tracking['last_price'] = current_price
        tracking['last_price_time'] = time.time()
        
        print(f"\n💰💰💰 PRICE ALERT! 💰💰💰")
        print(f"   🎯 Price: {current_price}")
        print(f"   📊 DEX: {dex_id}")
        print(f"   🏊 Pool: {data.get('pool_address', 'N/A')}")
        print(f"   📝 Type: {message_type}")
        
        # Check for BONK-specific info
        is_bonk_related = False
        if 'pool_address' in data:
            pool_addr = data['pool_address']
            print(f"   🔍 Pool Address: {pool_addr}")
            # We'd need to check if this pool contains BONK
        
        if 'signature' in data and data['signature']:
            print(f"   ✍️  Signature: {data['signature'][:16]}...")
            
        # Show liquidity info if available
        if 'liquidity_sol' in data:
            print(f"   💧 SOL Liquidity: {data['liquidity_sol']}")
        if 'token_reserve_raw' in data:
            print(f"   🪙 Token Reserve: {data['token_reserve_raw']}")
        if 'sol_reserve_raw' in data:
            print(f"   💎 SOL Reserve: {data['sol_reserve_raw']}")
    
    # Check logs for BONK mentions or BONK mint address
    if 'logs' in data and data['logs']:
        logs_text = ' '.join(str(log) for log in data['logs'] if log)
        if BONK_MINT in logs_text or 'bonk' in logs_text.lower():
            tracking['bonk_mentions'] += 1
            print(f"\n🐶 BONK MENTION DETECTED!")
            print(f"   📝 In logs from {dex_id}")
            print(f"   🏊 Pool: {data.get('pool_address', 'N/A')}")
            for i, log in enumerate(data['logs'][:3]):
                if log and (BONK_MINT in str(log) or 'bonk' in str(log).lower()):
                    print(f"      Log {i+1}: {str(log)[:100]}...")
    
    # Show summary every 10 messages to reduce spam
    if tracking['total_messages'] % 10 == 0:
        runtime = time.time() - tracking['start_time']
        print(f"\n📊 Quick Update (Msg #{tracking['total_messages']}, {runtime:.0f}s)")
        print(f"   Prices found: {tracking['price_updates']}")
        print(f"   BONK mentions: {tracking['bonk_mentions']}")
        print(f"   Pools seen: {len(tracking['pool_addresses_seen'])}")
        print(f"   DEX activity: {dict(tracking['dex_activity'])}")
        
        if tracking['last_price']:
            time_since = time.time() - tracking['last_price_time']
            print(f"   💰 Last price: {tracking['last_price']} ({time_since:.0f}s ago)")

async def price_statistics():
    """Show comprehensive price hunting statistics every 60 seconds"""
    global tracking
    
    while True:
        await asyncio.sleep(60)  # Every 60 seconds as requested
        
        runtime = time.time() - tracking['start_time']
        print(f"\n" + "="*70)
        print(f"🎯 BONK PRICE HUNTING REPORT ({runtime/60:.1f} minutes)")
        print(f"="*70)
        
        # Message stats
        print(f"📊 MESSAGE STATISTICS:")
        print(f"   Total messages: {tracking['total_messages']}")
        print(f"   Messages/minute: {tracking['total_messages'] / (runtime / 60):.1f}")
        print(f"   Account updates: {tracking['account_messages']}")
        print(f"   Log updates: {tracking['log_messages']}")
        print(f"   Raw data messages: {tracking['raw_data_messages']}")
        
        # Price hunting results
        print(f"\n💰 PRICE HUNTING RESULTS:")
        print(f"   Prices detected: {tracking['price_updates']}")
        print(f"   BONK mentions: {tracking['bonk_mentions']}")
        
        if tracking['last_price']:
            time_since = time.time() - tracking['last_price_time']
            print(f"   🎯 Latest price: {tracking['last_price']}")
            print(f"   ⏰ Time since last price: {time_since:.0f} seconds")
        else:
            print(f"   ❌ NO PRICES DETECTED YET")
        
        # DEX activity
        print(f"\n🏪 DEX ACTIVITY:")
        for dex, count in tracking['dex_activity'].items():
            print(f"   {dex}: {count} messages")
        
        # Pool tracking
        print(f"\n🏊 POOL TRACKING:")
        print(f"   Unique pools seen: {len(tracking['pool_addresses_seen'])}")
        print(f"   Signatures tracked: {len(tracking['signatures_seen'])}")
        
        if tracking['pool_addresses_seen']:
            print(f"   Recent pools:")
            for pool in list(tracking['pool_addresses_seen'])[-5:]:  # Show last 5
                print(f"      {pool[:16]}...")
        
        # Message type breakdown
        if tracking['message_types']:
            print(f"\n📋 MESSAGE TYPES:")
            total = tracking['total_messages']
            for msg_type, count in tracking['message_types'].items():
                pct = (count / total) * 100 if total > 0 else 0
                print(f"   {msg_type}: {count} ({pct:.1f}%)")
        
        print(f"\n⚡ System Status: {'🟢 HUNTING PRICES' if tracking['total_messages'] > 0 else '🔴 NO DATA'}")
        print(f"="*70)

async def main():
    print("🎯 BONK PRICE HUNTER ACTIVATED!")
    print("   🐶 Aggressively hunting for BONK prices")
    print("   💰 Will show any price data found")
    print("   📊 Statistics every 60 seconds")
    print(f"   🎯 Target BONK mint: {BONK_MINT}")
    print()
    
    # Initialize
    settings = Settings()
    db_path = settings.DATABASE_FILE_PATH
    token_db = await TokenDatabase.create(db_path, settings)
    
    try:
        # Verify BONK token
        bonk_tokens = await token_db.get_tokens_list({"symbol": "BONK"})
        if bonk_tokens:
            bonk = bonk_tokens[0]
            print(f"✅ BONK Target Confirmed:")
            print(f"   Symbol: {bonk.symbol}")
            print(f"   Mint: {bonk.mint}")
            print(f"   Name: {bonk.name}")
            print()
        
        # Start the hunt
        market_data = MarketData(settings)
        await market_data.initialize()
        await market_data.initialize_blockchain_listener()
        
        blockchain_listener = market_data.blockchain_listener
        if not blockchain_listener:
            raise RuntimeError("Failed to initialize blockchain listener")
        
        blockchain_listener.set_callback(aggressive_bonk_callback)
        
        print("🚀 PRICE HUNTING INITIATED!")
        print("   🔗 Blockchain listener active")
        print("   🎯 Monitoring all DEX programs")
        print("   ⏰ Stats every 60 seconds")
        print("   🛑 Press Ctrl+C to stop hunting")
        print()
        
        tracking['start_time'] = time.time()
        
        # Hunt for prices!
        await asyncio.gather(
            blockchain_listener.run_forever(),
            price_statistics()
        )
        
    except KeyboardInterrupt:
        print(f"\n🛑 BONK Price Hunter stopped by user")
    except Exception as e:
        print(f"\n❌ Price Hunter error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            print(f"\n🔄 Shutting down price hunter...")
            if 'market_data' in locals():
                await market_data.close()
            if 'token_db' in locals():
                await token_db.close()
        except Exception as e:
            print(f"⚠️  Error during shutdown: {e}")
        
        # Final hunt report
        runtime = time.time() - tracking['start_time']
        print(f"\n🎯 FINAL BONK PRICE HUNT REPORT")
        print(f"="*50)
        print(f"   Hunt duration: {runtime/60:.1f} minutes")
        print(f"   Total messages: {tracking['total_messages']}")
        print(f"   💰 Prices found: {tracking['price_updates']}")
        print(f"   🐶 BONK mentions: {tracking['bonk_mentions']}")
        print(f"   🏊 Pools discovered: {len(tracking['pool_addresses_seen'])}")
        print(f"   📊 Message rate: {tracking['total_messages'] / (runtime / 60):.1f}/min")
        
        if tracking['price_updates'] > 0:
            print(f"   🎯 Success rate: {(tracking['price_updates'] / tracking['total_messages']) * 100:.2f}%")
            print(f"   💰 Latest price: {tracking['last_price']}")
        else:
            print(f"   ❌ NO PRICES DETECTED - May need specific pool subscriptions")
        
        print(f"🏁 Price hunt complete!")

if __name__ == "__main__":
    asyncio.run(main()) 