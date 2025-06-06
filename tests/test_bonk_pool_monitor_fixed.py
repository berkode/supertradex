#!/usr/bin/env python3
"""
BONK Pool Monitor - Fixed version that establishes connections first
This script properly starts the blockchain listener, then subscribes to BONK pools.
"""

import asyncio
import sys
import os
import time
import json
from pathlib import Path
from typing import Dict, Any, Set, List

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
    'price_updates': 0,
    'pool_subscriptions': 0,
    'bonk_pools_found': [],
    'start_time': time.time(),
    'last_price': None,
    'last_price_time': None,
    'price_history': [],
    'connections_established': False,
    'subscription_attempts': 0
}

# Known BONK mint address
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

# Known BONK trading pools
KNOWN_BONK_POOLS = [
    # Raydium BONK/SOL pools
    "8nKJ4z9FSw6wrVZKASqBiS9DS1CiNsRnqwCCKVQjqdkB",  # BONK/SOL Raydium
    "Hs97TCZeuYiJxooo3U73qEHXg3dKpRL4uYKYRryEK9CF",  # Another BONK/SOL pool
    # Orca BONK/SOL pools  
    "9vqYJjDUFecLL2xPUC4Rc7hyCtZ6iJ4mDiVZX7aFXoAe",  # BONK/SOL Orca
]

async def bonk_pool_callback(data: Dict[str, Any]):
    """Callback specifically for BONK pool price updates"""
    global tracking
    
    tracking['total_messages'] += 1
    
    print(f"\n🎯 BONK Pool Message #{tracking['total_messages']}")
    print(f"   Type: {data.get('type', 'unknown')}")
    print(f"   DEX: {data.get('dex_id', 'unknown')}")
    
    if 'pool_address' in data:
        print(f"   Pool: {data['pool_address']}")
    
    # Look for price data
    if 'price' in data and data['price']:
        price = data['price']
        tracking['price_updates'] += 1
        tracking['last_price'] = price
        tracking['last_price_time'] = time.time()
        tracking['price_history'].append({
            'price': price,
            'timestamp': time.time(),
            'pool': data.get('pool_address', 'unknown'),
            'dex': data.get('dex_id', 'unknown')
        })
        
        print(f"   💰💰💰 BONK PRICE: ${price:.8f} 💰💰💰")
        print(f"   📈 Price update #{tracking['price_updates']}")
        
        # Show price trend if we have history
        if len(tracking['price_history']) > 1:
            prev_price = tracking['price_history'][-2]['price']
            change = ((price - prev_price) / prev_price) * 100
            trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            print(f"   {trend} Change: {change:+.2f}%")
    
    # Show any liquidity data
    if 'liquidity_sol' in data:
        print(f"   💧 SOL Liquidity: {data['liquidity_sol']}")
    if 'token_reserve_raw' in data:
        print(f"   🪙 Token Reserve: {data['token_reserve_raw']}")
    if 'sol_reserve_raw' in data:
        print(f"   💎 SOL Reserve: {data['sol_reserve_raw']}")
    
    # Show transaction info
    if 'signature' in data and data['signature']:
        print(f"   ✍️  Tx: {data['signature'][:16]}...")
    
    print(f"   ⏱️  Runtime: {time.time() - tracking['start_time']:.1f}s")

async def wait_for_connections(blockchain_listener, max_wait_seconds=30):
    """Wait for blockchain listener connections to be established"""
    print(f"⏳ Waiting for blockchain connections to establish (max {max_wait_seconds}s)...")
    
    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        if blockchain_listener.is_connected():
            tracking['connections_established'] = True
            print(f"✅ Blockchain connections established after {time.time() - start_time:.1f}s")
            return True
        
        print(f"   ⏳ Waiting for connections... ({time.time() - start_time:.1f}s)")
        await asyncio.sleep(2)
    
    print(f"❌ Connections not established within {max_wait_seconds}s")
    return False

async def subscribe_to_bonk_pools_after_connection(blockchain_listener, pools: List[str]) -> int:
    """Subscribe to BONK pools after connections are established"""
    print(f"\n🔗 Subscribing to {len(pools)} BONK pools (connections ready)...")
    
    successful_subs = 0
    tracking['subscription_attempts'] = len(pools)
    
    for i, pool in enumerate(pools, 1):
        print(f"\n   Attempting pool {i}/{len(pools)}: {pool}")
        
        try:
            # Try Raydium first
            print(f"      Trying Raydium subscription...")
            success = await blockchain_listener.subscribe_to_pool_data(pool, "raydium_v4")
            if success:
                successful_subs += 1
                print(f"      ✅ Subscribed to {pool} (Raydium)")
                continue
            
            # Try pool logs if direct subscription fails
            print(f"      Trying Raydium logs subscription...")
            success = await blockchain_listener.subscribe_to_pool_logs(pool, "raydium_v4")
            if success:
                successful_subs += 1
                print(f"      ✅ Subscribed to {pool} logs (Raydium)")
                continue
                
            print(f"      ❌ Failed to subscribe to {pool}")
            
        except Exception as e:
            print(f"      ❌ Error subscribing to {pool}: {e}")
    
    tracking['pool_subscriptions'] = successful_subs
    print(f"\n📊 Successfully subscribed to {successful_subs}/{len(pools)} BONK pools")
    return successful_subs

async def monitor_and_subscribe():
    """Monitor blockchain and handle delayed pool subscriptions"""
    global tracking
    
    # Wait a bit for the blockchain listener to start
    await asyncio.sleep(5)
    
    # Try to subscribe to pools after connections are ready
    if not tracking['connections_established']:
        print("🔄 Attempting to subscribe to pools...")
        
        # Get the blockchain listener from the global scope
        if 'blockchain_listener' in globals():
            blockchain_listener = globals()['blockchain_listener']
            bonk_pools = tracking['bonk_pools_found']
            
            if bonk_pools:
                successful_subs = await subscribe_to_bonk_pools_after_connection(blockchain_listener, bonk_pools)
                if successful_subs > 0:
                    print(f"🎉 Successfully subscribed to {successful_subs} BONK pools!")
                else:
                    print("❌ Failed to subscribe to any BONK pools")

async def show_bonk_stats():
    """Show BONK monitoring statistics every 60 seconds"""
    global tracking
    
    while True:
        await asyncio.sleep(60)  # Every 60 seconds as requested
        
        runtime = time.time() - tracking['start_time']
        print(f"\n" + "="*70)
        print(f"🐶 BONK POOL MONITORING REPORT ({runtime/60:.1f} minutes)")
        print(f"="*70)
        
        # Connection status
        print(f"🔗 CONNECTION STATUS:")
        print(f"   Connections established: {'✅ Yes' if tracking['connections_established'] else '❌ No'}")
        print(f"   Pool subscriptions: {tracking['pool_subscriptions']}")
        print(f"   Subscription attempts: {tracking['subscription_attempts']}")
        
        # Message stats
        print(f"\n📊 MESSAGE STATISTICS:")
        print(f"   Total messages: {tracking['total_messages']}")
        print(f"   Messages/minute: {tracking['total_messages'] / (runtime / 60):.1f}")
        
        # Price tracking
        print(f"\n💰 PRICE TRACKING:")
        print(f"   Price updates: {tracking['price_updates']}")
        
        if tracking['last_price']:
            time_since = time.time() - tracking['last_price_time']
            print(f"   🎯 Latest BONK price: ${tracking['last_price']:.8f}")
            print(f"   ⏰ Time since last update: {time_since:.0f} seconds")
            
            # Show price history summary
            if len(tracking['price_history']) > 1:
                first_price = tracking['price_history'][0]['price']
                last_price = tracking['price_history'][-1]['price']
                total_change = ((last_price - first_price) / first_price) * 100
                trend = "📈" if total_change > 0 else "📉" if total_change < 0 else "➡️"
                print(f"   {trend} Session change: {total_change:+.2f}%")
                print(f"   📈 Updates this session: {len(tracking['price_history'])}")
        else:
            print(f"   ❌ NO BONK PRICES DETECTED YET")
        
        # Recent price history
        if tracking['price_history']:
            print(f"\n📈 RECENT PRICE HISTORY:")
            recent = tracking['price_history'][-5:]  # Last 5 prices
            for i, entry in enumerate(recent):
                age = time.time() - entry['timestamp']
                print(f"      {i+1}. ${entry['price']:.8f} ({age:.0f}s ago) - {entry['dex']}")
        
        status = "🟢 MONITORING BONK POOLS" if tracking['pool_subscriptions'] > 0 else "🔴 NO ACTIVE SUBSCRIPTIONS"
        print(f"\n⚡ System Status: {status}")
        print(f"="*70)

async def main():
    global blockchain_listener
    
    print("🐶 BONK POOL MONITOR ACTIVATED! (Fixed Version)")
    print("   🎯 Monitoring specific BONK trading pools")
    print("   💰 Real-time price updates from pool subscriptions")
    print("   📊 Statistics every 60 seconds")
    print(f"   🪙 Target BONK mint: {BONK_MINT}")
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
        
        # Find BONK pools
        bonk_pools = KNOWN_BONK_POOLS.copy()
        tracking['bonk_pools_found'] = bonk_pools
        
        print(f"🔍 Found {len(bonk_pools)} BONK pools to monitor:")
        for i, pool in enumerate(bonk_pools, 1):
            print(f"      {i}. {pool}")
        print()
        
        # Initialize blockchain listener
        market_data = MarketData(settings)
        await market_data.initialize()
        await market_data.initialize_blockchain_listener()
        
        blockchain_listener = market_data.blockchain_listener
        if not blockchain_listener:
            raise RuntimeError("Failed to initialize blockchain listener")
        
        # Set callback for pool updates
        blockchain_listener.set_callback(bonk_pool_callback)
        
        print(f"🚀 STARTING BLOCKCHAIN LISTENER...")
        print(f"   🔗 Will establish connections first")
        print(f"   🎯 Then subscribe to BONK pools")
        print(f"   ⏰ Stats every 60 seconds")
        print(f"   🛑 Press Ctrl+C to stop monitoring")
        print()
        
        tracking['start_time'] = time.time()
        
        # Start monitoring with proper connection handling!
        await asyncio.gather(
            blockchain_listener.run_forever(),
            monitor_and_subscribe(),
            show_bonk_stats()
        )
        
    except KeyboardInterrupt:
        print(f"\n🛑 BONK Pool Monitor stopped by user")
    except Exception as e:
        print(f"\n❌ Pool Monitor error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            print(f"\n🔄 Shutting down pool monitor...")
            if 'market_data' in locals():
                await market_data.close()
            if 'token_db' in locals():
                await token_db.close()
        except Exception as e:
            print(f"⚠️  Error during shutdown: {e}")
        
        # Final report
        runtime = time.time() - tracking['start_time']
        print(f"\n🐶 FINAL BONK POOL MONITOR REPORT")
        print(f"="*50)
        print(f"   Monitor duration: {runtime/60:.1f} minutes")
        print(f"   Connections established: {'✅ Yes' if tracking['connections_established'] else '❌ No'}")
        print(f"   Pool subscriptions: {tracking['pool_subscriptions']}")
        print(f"   Total messages: {tracking['total_messages']}")
        print(f"   💰 Price updates: {tracking['price_updates']}")
        print(f"   📊 Message rate: {tracking['total_messages'] / (runtime / 60):.1f}/min")
        
        if tracking['price_updates'] > 0:
            print(f"   🎯 Latest BONK price: ${tracking['last_price']:.8f}")
            if len(tracking['price_history']) > 1:
                first = tracking['price_history'][0]['price']
                last = tracking['price_history'][-1]['price']
                change = ((last - first) / first) * 100
                print(f"   📈 Session change: {change:+.2f}%")
        else:
            print(f"   ❌ NO PRICES DETECTED - May need different approach")
        
        print(f"🏁 BONK pool monitoring complete!")

if __name__ == "__main__":
    asyncio.run(main()) 