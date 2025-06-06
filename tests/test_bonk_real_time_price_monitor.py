#!/usr/bin/env python3
"""
BONK Real-Time Price Monitor
Monitors BONK token for live price updates from blockchain transactions.
Shows actual price changes with timestamps and source information.
"""

import asyncio
import sys
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import json

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
from data.token_database import TokenDatabase
from data.market_data import MarketData

class BONKPriceMonitor:
    def __init__(self):
        self.settings = None
        self.token_db = None
        self.market_data = None
        self.blockchain_listener = None
        
        # BONK tracking
        self.bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        self.bonk_info = None
        self.price_history = []
        self.last_price = None
        self.last_price_time = None
        self.price_update_count = 0
        self.start_time = None
        
        # Display formatting
        self.display_interval = 0.5  # Update display every 500ms
        
        # Listener task
        self.listener_task = None
        
    def _format_price(self, price: float) -> str:
        """Format price with appropriate precision"""
        if price >= 1:
            return f"${price:.4f}"
        elif price >= 0.01:
            return f"${price:.6f}"
        elif price >= 0.0001:
            return f"${price:.8f}"
        else:
            return f"${price:.12f}"
            
    def _format_timestamp(self, timestamp: float) -> str:
        """Format timestamp to readable time"""
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
        
    async def initialize(self):
        """Initialize all components"""
        try:
            print("🔧 Initializing BONK Price Monitor...")
            
            self.settings = Settings()
            
            # Initialize database
            self.token_db = TokenDatabase(self.settings.DATABASE_FILE_PATH, self.settings)
            await self.token_db.initialize()
            
            # Initialize market data
            self.market_data = MarketData(self.settings, token_db=self.token_db)
            await self.market_data.initialize()
            
            # Initialize blockchain listener
            print("🔌 Initializing blockchain listener...")
            await self.market_data.initialize_blockchain_listener()
            
            if self.market_data.blockchain_listener:
                self.blockchain_listener = self.market_data.blockchain_listener
                
                # Set our callback to capture events
                self.blockchain_listener.set_callback(self._price_event_callback)
                print("✅ Blockchain listener initialized")
            else:
                print("❌ Failed to initialize blockchain listener")
                return False
                
            # Get BONK token info
            self.bonk_info = await self.token_db.get_token_info(self.bonk_mint)
            if not self.bonk_info:
                print(f"❌ BONK token not found in database")
                return False
                
            print("✅ BONK Price Monitor initialized")
            return True
            
        except Exception as e:
            print(f"❌ Error initializing: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _price_event_callback(self, event_data: Dict[str, Any]):
        """Process blockchain events for BONK price updates"""
        try:
            # Check if this event is related to BONK
            token_address = event_data.get('token_address') or event_data.get('mint')
            if token_address != self.bonk_mint:
                return  # Not BONK, ignore
                
            event_type = event_data.get('type')
            price = event_data.get('price')
            
            if price and price > 0:
                timestamp = time.time()
                source = event_data.get('source', 'blockchain')
                dex_id = event_data.get('dex_id', 'unknown')
                signature = event_data.get('signature', 'unknown')
                
                # Record price update
                price_info = {
                    'timestamp': timestamp,
                    'price': price,
                    'event_type': event_type,
                    'source': source,
                    'dex_id': dex_id,
                    'signature': signature[:16] if signature != 'unknown' else 'unknown'
                }
                
                self.price_history.append(price_info)
                self.last_price = price
                self.last_price_time = timestamp
                self.price_update_count += 1
                
                # Print immediate price update
                time_str = self._format_timestamp(timestamp)
                price_str = self._format_price(price)
                print(f"🔥 {time_str} | BONK: {price_str} | {dex_id} | {event_type}")
                
                # Keep only last 50 updates for performance
                if len(self.price_history) > 50:
                    self.price_history = self.price_history[-50:]
                    
        except Exception as e:
            print(f"❌ Error in price callback: {e}")
    
    async def start_monitoring(self, duration_seconds: int = 300):
        """Start monitoring BONK price for specified duration"""
        try:
            symbol = self.bonk_info.get('symbol', 'BONK')
            pair_address = self.bonk_info.get('pair_address')
            dex_id = self.bonk_info.get('dex_id', 'raydium_v4')
            
            if not pair_address:
                print(f"❌ No pair address found for {symbol}")
                return False
            
            print(f"\n🚀 STARTING BONK REAL-TIME PRICE MONITORING")
            print(f"📊 Token: {symbol} ({self.bonk_mint[:8]}...)")
            print(f"🔗 Pair: {pair_address}")
            print(f"🏢 DEX: {dex_id}")
            print(f"⏱️ Duration: {duration_seconds}s")
            print("=" * 80)
            
            # Start the blockchain listener
            print("🚀 Starting blockchain listener...")
            self.listener_task = asyncio.create_task(self.blockchain_listener.run_forever())
            
            # Wait for listener to start
            await asyncio.sleep(3)
            
            # Check if listener started successfully
            if self.listener_task.done():
                exception = self.listener_task.exception()
                if exception:
                    print(f"❌ Blockchain listener failed: {exception}")
                    return False
                else:
                    print("❌ Blockchain listener completed unexpectedly")
                    return False
            
            print("✅ Blockchain listener started")
            
            # Start streaming for BONK
            print(f"📡 Setting up BONK monitoring...")
            await self.market_data.start_streaming(self.bonk_mint, pair_address, dex_id)
            
            # Monitor for the specified duration
            self.start_time = time.time()
            last_status_time = self.start_time
            last_display_time = self.start_time
            
            print(f"\n💰 LIVE BONK PRICE FEED:")
            print(f"{'Time':<12} | {'Price':<15} | {'DEX':<12} | {'Source':<10}")
            print("-" * 60)
            
            while time.time() - self.start_time < duration_seconds:
                await asyncio.sleep(0.1)  # Check frequently for responsiveness
                
                current_time = time.time()
                
                # Print periodic status every 30 seconds
                if current_time - last_status_time >= 30:
                    await self._print_status(current_time - self.start_time)
                    last_status_time = current_time
                
                # Check if listener is still running
                if self.listener_task.done():
                    print("❌ Blockchain listener stopped unexpectedly")
                    break
            
            print(f"\n✅ BONK monitoring completed!")
            await self._print_summary(duration_seconds)
            
        except Exception as e:
            print(f"❌ Error during monitoring: {e}")
            import traceback
            traceback.print_exc()
    
    async def _print_status(self, elapsed_seconds: int):
        """Print current monitoring status"""
        print(f"\n📈 STATUS UPDATE - {elapsed_seconds:.0f}s elapsed")
        print(f"   🔥 Price Updates: {self.price_update_count}")
        
        if self.last_price:
            time_since = time.time() - self.last_price_time
            price_str = self._format_price(self.last_price)
            print(f"   💵 Latest Price: {price_str} ({time_since:.1f}s ago)")
        else:
            print(f"   💵 Latest Price: No updates yet")
            
        # Check listener health
        if self.listener_task:
            if self.listener_task.done():
                print(f"   ⚠️ Listener: STOPPED")
            else:
                print(f"   ✅ Listener: RUNNING")
                
        # Connection status
        if self.blockchain_listener and hasattr(self.blockchain_listener, 'ws_connections'):
            active_connections = sum(1 for ws in self.blockchain_listener.ws_connections.values() 
                                   if ws and self.blockchain_listener._is_connection_open(ws))
            total_connections = len(self.blockchain_listener.ws_connections)
            print(f"   🌐 Connections: {active_connections}/{total_connections} active")
            
        print()
    
    async def _print_summary(self, duration_seconds: int):
        """Print final monitoring summary"""
        print(f"\n📋 BONK MONITORING SUMMARY")
        print(f"⏱️ Duration: {duration_seconds}s")
        print(f"🔥 Total Price Updates: {self.price_update_count}")
        
        if self.price_update_count > 0:
            update_rate = self.price_update_count / (duration_seconds / 60)
            print(f"⚡ Update Rate: {update_rate:.1f} updates/min")
            
            # Show recent price changes
            print(f"\n📊 RECENT PRICE HISTORY:")
            for update in self.price_history[-10:]:
                time_str = self._format_timestamp(update['timestamp'])
                price_str = self._format_price(update['price'])
                print(f"   {time_str} | {price_str} | {update['dex_id']} | {update['event_type']}")
                
            # Price statistics
            if len(self.price_history) > 1:
                prices = [p['price'] for p in self.price_history]
                min_price = min(prices)
                max_price = max(prices)
                avg_price = sum(prices) / len(prices)
                
                print(f"\n📈 PRICE STATISTICS:")
                print(f"   📊 Min Price: {self._format_price(min_price)}")
                print(f"   📊 Max Price: {self._format_price(max_price)}")
                print(f"   📊 Avg Price: {self._format_price(avg_price)}")
                
                if max_price > min_price:
                    volatility = ((max_price - min_price) / min_price) * 100
                    print(f"   📊 Volatility: {volatility:.2f}%")
        else:
            print(f"⚠️ No price updates received")
            print(f"   - Check WebSocket connections")
            print(f"   - Verify BONK is actively trading")
            print(f"   - Check DEX subscriptions")
    
    async def close(self):
        """Clean up resources"""
        try:
            print("\n🛑 Shutting down BONK Price Monitor...")
            
            # Stop blockchain listener
            if self.listener_task and not self.listener_task.done():
                print("   Stopping blockchain listener...")
                self.listener_task.cancel()
                try:
                    await self.listener_task
                except asyncio.CancelledError:
                    pass
                    
            # Close market data
            if self.market_data:
                await self.market_data.close()
                
            # Close database
            if self.token_db:
                await self.token_db.close()
                
            print("✅ BONK Price Monitor shut down cleanly")
        except Exception as e:
            print(f"❌ Error during shutdown: {e}")

async def main():
    """Main monitoring function"""
    monitor = BONKPriceMonitor()
    
    try:
        # Initialize
        if not await monitor.initialize():
            print("❌ Failed to initialize BONK Price Monitor")
            return
        
        # Start monitoring for 5 minutes
        await monitor.start_monitoring(duration_seconds=300)
        
    except KeyboardInterrupt:
        print("\n⚠️ Monitoring interrupted by user")
    except Exception as e:
        print(f"❌ Error in main: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await monitor.close()

if __name__ == '__main__':
    print("🎯 SupertradeX BONK Real-Time Price Monitor")
    print("=" * 80)
    asyncio.run(main()) 