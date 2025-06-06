#!/usr/bin/env python3
"""
BONK Token Real-time Price Monitor
Focused test to monitor BONK token price updates from blockchain events.
"""

import asyncio
import sys
import os
import time
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
from utils.logger import get_logger

# Global variables for tracking
price_updates = []
swap_events = []
start_time = time.time()

async def price_update_callback(event_data: Dict[str, Any]):
    """Handle real-time price updates for BONK token"""
    try:
        current_time = time.time()
        elapsed = current_time - start_time
        
        # Extract relevant information
        event_type = event_data.get('source', 'unknown')
        dex_id = event_data.get('dex_id', 'unknown')
        mint = event_data.get('mint', 'unknown')
        price = event_data.get('price')
        instruction_type = event_data.get('instruction_type', 'unknown')
        signature = event_data.get('signature', 'unknown')
        
        # Only show BONK-related events
        bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        if mint == bonk_mint or bonk_mint in str(event_data):
            # Format the price update
            price_str = f"${price:.8f}" if price else "N/A"
            
            # Create a clean status line
            status_line = f"⏰ +{elapsed:6.1f}s | 🪙 BONK | 💰 {price_str} | 🔄 {instruction_type} | 🏪 {dex_id}"
            
            print(status_line)
            print(f"   📝 Signature: {signature[:20]}...")
            print(f"   📊 Event Type: {event_type}")
            print("   " + "─" * 60)
            
            # Store for analysis
            price_updates.append({
                'timestamp': current_time,
                'elapsed': elapsed,
                'price': price,
                'dex_id': dex_id,
                'instruction_type': instruction_type,
                'event_type': event_type,
                'signature': signature
            })
            
    except Exception as e:
        print(f"❌ Error in price callback: {e}")

async def show_stats():
    """Show periodic statistics"""
    while True:
        await asyncio.sleep(30)  # Show stats every 30 seconds
        
        elapsed = time.time() - start_time
        total_events = len(price_updates)
        
        if total_events > 0:
            recent_events = [e for e in price_updates if e['elapsed'] > elapsed - 30]
            recent_count = len(recent_events)
            
            print("\n" + "=" * 70)
            print(f"📈 BONK MONITORING STATS - Running for {elapsed/60:.1f} minutes")
            print(f"   Total BONK events: {total_events}")
            print(f"   Recent events (30s): {recent_count}")
            print(f"   Events per minute: {(total_events / (elapsed/60)):.1f}")
            
            if recent_events:
                latest_price = recent_events[-1].get('price')
                if latest_price:
                    print(f"   Latest BONK price: ${latest_price:.8f}")
                    
                # Count by DEX
                dex_counts = {}
                for event in recent_events:
                    dex = event.get('dex_id', 'unknown')
                    dex_counts[dex] = dex_counts.get(dex, 0) + 1
                    
                print(f"   Recent activity by DEX: {dex_counts}")
            
            print("=" * 70 + "\n")

async def main():
    """Main monitoring function"""
    settings = Settings()
    logger = get_logger(__name__)
    
    print("🚀 Starting BONK Token Real-time Price Monitor")
    print("=" * 70)
    print(f"⏰ Start time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🪙 Monitoring token: BONK (DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263)")
    print(f"🔗 Monitoring DEXs: {', '.join(settings.MONITORED_PROGRAMS_LIST)}")
    print("💡 Press Ctrl+C to stop monitoring")
    print("=" * 70)
    
    market_data = None
    
    try:
        # Initialize market data with our callback
        market_data = MarketData(settings)
        await market_data.initialize()
        
        # Initialize the blockchain listener specifically
        await market_data.initialize_blockchain_listener()
        
        # Set up the callback for blockchain events
        blockchain_listener = market_data.blockchain_listener
        if not blockchain_listener:
            raise RuntimeError("Failed to initialize blockchain listener")
        blockchain_listener.set_callback(price_update_callback)
        
        # Add BONK to monitoring
        bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        await blockchain_listener.add_token_to_monitor(bonk_mint)
        
        print(f"✅ Initialized blockchain listener with {len(blockchain_listener.parsers)} DEX parsers")
        print(f"🎯 Added BONK token to monitoring list")
        print("🔄 Starting real-time monitoring...\n")
        
        # Start both the blockchain listener and stats display
        await asyncio.gather(
            blockchain_listener.run_forever(),
            show_stats()
        )
        
    except KeyboardInterrupt:
        print("\n🛑 Stopping BONK token monitor...")
    except Exception as e:
        print(f"❌ Error: {e}")
        logger.error(f"Error in BONK monitor: {e}", exc_info=True)
    finally:
        # Cleanup
        if market_data:
            await market_data.close()
        
        # Final stats
        total_time = time.time() - start_time
        total_events = len(price_updates)
        print(f"\n📊 Final Statistics:")
        print(f"   Total monitoring time: {total_time/60:.1f} minutes")
        print(f"   Total BONK events captured: {total_events}")
        if total_events > 0:
            print(f"   Average events per minute: {(total_events / (total_time/60)):.1f}")
            
            # Show unique DEXs seen
            dexs_seen = set(e.get('dex_id') for e in price_updates)
            print(f"   DEXs with BONK activity: {', '.join(dexs_seen)}")
            
        print("✅ BONK monitor shutdown complete")

if __name__ == "__main__":
    asyncio.run(main()) 