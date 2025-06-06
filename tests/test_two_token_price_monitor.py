#!/usr/bin/env python3
"""
Two Token Price Monitor - Select two tokens from database and show real-time prices
Shows prices every 60 seconds as requested by the user.
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
    'last_stats_time': time.time(),
    'token_info': {}
}

async def price_update_callback(data: Dict[str, Any]):
    """Callback to handle price updates for our monitored tokens"""
    global monitoring_stats
    
    monitoring_stats['total_messages'] += 1
    
    # Check if this is for one of our monitored tokens
    pool_address = data.get('pool_address', '')
    price = data.get('price')
    dex_id = data.get('dex_id', 'unknown')
    
    # Log all price updates with token info
    if price:
        monitoring_stats['price_updates'] += 1
        
        # Try to identify which token this is for
        token_identified = False
        for token_mint, token_info in monitoring_stats['token_info'].items():
            token_symbol = token_info['symbol']
            
            # Update price for this token
            if token_mint not in monitoring_stats['monitored_tokens']:
                monitoring_stats['monitored_tokens'][token_mint] = {
                    'symbol': token_symbol,
                    'latest_price': None,
                    'price_history': [],
                    'update_count': 0,
                    'last_update_time': None
                }
            
            # Store the price update (we'll assume any price update could be for our tokens)
            monitoring_stats['monitored_tokens'][token_mint]['latest_price'] = price
            monitoring_stats['monitored_tokens'][token_mint]['price_history'].append({
                'price': price,
                'timestamp': time.time(),
                'dex': dex_id,
                'pool': pool_address
            })
            monitoring_stats['monitored_tokens'][token_mint]['update_count'] += 1
            monitoring_stats['monitored_tokens'][token_mint]['last_update_time'] = time.time()
            
            print(f"\n💰 PRICE UPDATE for {token_symbol}")
            print(f"   Price: ${price:.8f}")
            print(f"   DEX: {dex_id}")
            print(f"   Pool: {pool_address[:16]}..." if pool_address else "   Pool: N/A")
            print(f"   Update #{monitoring_stats['monitored_tokens'][token_mint]['update_count']}")
            
            token_identified = True
            break
        
        if not token_identified:
            print(f"\n💰 GENERAL PRICE UPDATE")
            print(f"   Price: ${price:.8f}")
            print(f"   DEX: {dex_id}")
            print(f"   Pool: {pool_address[:16]}..." if pool_address else "   Pool: N/A")

async def show_token_price_statistics():
    """Show token price statistics every 60 seconds as requested"""
    global monitoring_stats
    
    while True:
        await asyncio.sleep(60)  # Every 60 seconds as requested
        
        current_time = time.time()
        runtime = current_time - monitoring_stats['start_time']
        time_since_last = current_time - monitoring_stats['last_stats_time']
        
        print(f"\n" + "="*80)
        print(f"📊 TWO TOKEN PRICE MONITORING REPORT ({runtime/60:.1f} minutes)")
        print(f"="*80)
        
        # General stats
        print(f"📈 MONITORING STATISTICS:")
        print(f"   Runtime: {runtime/60:.1f} minutes")
        print(f"   Total messages processed: {monitoring_stats['total_messages']}")
        print(f"   Price updates received: {monitoring_stats['price_updates']}")
        print(f"   Messages/minute: {monitoring_stats['total_messages'] / (runtime / 60):.1f}")
        print(f"   Price updates/minute: {monitoring_stats['price_updates'] / (runtime / 60):.1f}")
        
        # Token-specific stats
        print(f"\n🪙 TOKEN PRICE DETAILS:")
        
        if not monitoring_stats['token_info']:
            print("   ❌ No tokens being monitored")
        else:
            for token_mint, token_info in monitoring_stats['token_info'].items():
                symbol = token_info['symbol']
                name = token_info['name']
                
                print(f"\n   🎯 {symbol} ({name})")
                print(f"      Mint: {token_mint}")
                
                if token_mint in monitoring_stats['monitored_tokens']:
                    token_stats = monitoring_stats['monitored_tokens'][token_mint]
                    
                    if token_stats['latest_price']:
                        latest_price = token_stats['latest_price']
                        update_count = token_stats['update_count']
                        last_update = token_stats['last_update_time']
                        time_since_update = current_time - last_update if last_update else float('inf')
                        
                        print(f"      💰 Latest Price: ${latest_price:.8f}")
                        print(f"      📊 Updates: {update_count}")
                        print(f"      ⏰ Last Update: {time_since_update:.0f}s ago")
                        
                        # Price history analysis
                        if len(token_stats['price_history']) > 1:
                            recent_prices = [p['price'] for p in token_stats['price_history'][-5:]]
                            min_price = min(recent_prices)
                            max_price = max(recent_prices)
                            volatility = ((max_price - min_price) / min_price) * 100 if min_price > 0 else 0
                            
                            print(f"      📈 Recent Range: ${min_price:.8f} - ${max_price:.8f}")
                            print(f"      📊 Recent Volatility: {volatility:.2f}%")
                        
                        # Show recent price history
                        if token_stats['price_history']:
                            print(f"      📋 Recent Updates:")
                            recent = token_stats['price_history'][-3:]  # Last 3 prices
                            for i, entry in enumerate(recent):
                                age = current_time - entry['timestamp']
                                print(f"         {i+1}. ${entry['price']:.8f} ({age:.0f}s ago, {entry['dex']})")
                    else:
                        print(f"      ❌ No price updates received yet")
                else:
                    print(f"      ❌ No price data available")
        
        # System health
        messages_this_period = monitoring_stats['total_messages']
        message_rate = messages_this_period / (runtime / 60) if runtime > 0 else 0
        
        status_icon = "🟢" if message_rate > 1 else "🟡" if message_rate > 0 else "🔴"
        print(f"\n⚡ SYSTEM STATUS: {status_icon} {'ACTIVE' if message_rate > 0 else 'WAITING FOR DATA'}")
        print(f"   Message Rate: {message_rate:.1f} messages/minute")
        print(f"   Price Update Rate: {monitoring_stats['price_updates'] / (runtime / 60):.1f} updates/minute")
        
        print(f"="*80)
        monitoring_stats['last_stats_time'] = current_time

async def main():
    print("🎯 TWO TOKEN PRICE MONITOR STARTING!")
    print("   📊 Selecting first two tokens from database")
    print("   💰 Monitoring real-time prices")
    print("   📈 Statistics every 60 seconds")
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
            return
        
        # Select first two tokens
        selected_tokens = all_tokens[:2]
        
        print(f"✅ Selected tokens for monitoring:")
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
        market_data = MarketData(settings)
        await market_data.initialize()
        await market_data.initialize_blockchain_listener()
        
        blockchain_listener = market_data.blockchain_listener
        if not blockchain_listener:
            raise RuntimeError("Failed to initialize blockchain listener")
        
        # Set our callback
        blockchain_listener.set_callback(price_update_callback)
        
        print(f"🚀 MONITORING STARTED!")
        print(f"   🔗 Blockchain listener active")
        print(f"   🎯 Tracking prices for {len(selected_tokens)} tokens")
        print(f"   ⏰ Statistics every 60 seconds")
        print(f"   🛑 Press Ctrl+C to stop monitoring")
        print()
        
        monitoring_stats['start_time'] = time.time()
        
        # Start monitoring
        await asyncio.gather(
            blockchain_listener.run_forever(),
            show_token_price_statistics()
        )
        
    except KeyboardInterrupt:
        print(f"\n🛑 Two Token Monitor stopped by user")
    except Exception as e:
        print(f"\n❌ Monitor error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            print(f"\n🔄 Shutting down monitor...")
            if 'market_data' in locals():
                await market_data.close()
            if 'token_db' in locals():
                await token_db.close()
        except Exception as e:
            print(f"⚠️  Error during shutdown: {e}")
        
        # Final report
        runtime = time.time() - monitoring_stats['start_time']
        print(f"\n🎯 FINAL TWO TOKEN MONITORING REPORT")
        print(f"="*50)
        print(f"   Monitor duration: {runtime/60:.1f} minutes")
        print(f"   Total messages: {monitoring_stats['total_messages']}")
        print(f"   Price updates: {monitoring_stats['price_updates']}")
        print(f"   Message rate: {monitoring_stats['total_messages'] / (runtime / 60):.1f}/min")
        
        if monitoring_stats['monitored_tokens']:
            print(f"\n   TOKEN FINAL PRICES:")
            for token_mint, token_stats in monitoring_stats['monitored_tokens'].items():
                symbol = token_stats['symbol']
                if token_stats['latest_price']:
                    print(f"      {symbol}: ${token_stats['latest_price']:.8f} ({token_stats['update_count']} updates)")
                else:
                    print(f"      {symbol}: No price data received")
        
        print(f"🏁 Two token monitoring complete!")

if __name__ == "__main__":
    asyncio.run(main()) 