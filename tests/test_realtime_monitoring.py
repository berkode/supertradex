#!/usr/bin/env python3
"""
Real-time blockchain monitoring test for debugging price updates.
Monitors the BONK token for live price updates from blockchain events.
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
from data.token_database import TokenDatabase
from data.market_data import MarketData

class RealTimeMonitor:
    def __init__(self):
        self.settings = None
        self.token_db = None
        self.market_data = None
        self.blockchain_listener = None
        
        # Tracking
        self.price_updates = []
        self.transaction_count = 0
        self.last_price = None
        self.last_price_time = None
        self.start_time = None
        self.monitoring_token = None
        
        # Task management
        self.listener_task = None
        
    async def initialize(self):
        """Initialize all components"""
        try:
            print("🔧 Initializing components...")
            
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
                self.blockchain_listener.set_callback(self._event_callback)
                print("✅ Blockchain listener initialized")
            else:
                print("❌ Failed to initialize blockchain listener")
                return False
                
            print("✅ All components initialized")
            return True
            
        except Exception as e:
            print(f"❌ Error initializing: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _event_callback(self, event_data: Dict[str, Any]):
        """Process blockchain events"""
        try:
            self.transaction_count += 1
            event_type = event_data.get('type')
            
            # Log all events for debugging
            print(f"📡 Event #{self.transaction_count}: {event_type}")
            
            if event_type == 'log_update':
                await self._handle_swap_event(event_data)
            elif event_type == 'account_update':
                await self._handle_account_event(event_data)
            
            # Also forward to original market data handler
            if hasattr(self.market_data, '_handle_blockchain_update'):
                await self.market_data._handle_blockchain_update(event_data)
                
        except Exception as e:
            print(f"❌ Error in event callback: {e}")
    
    async def _handle_swap_event(self, event_data: Dict[str, Any]):
        """Handle swap transaction events"""
        try:
            price = event_data.get('price')
            signature = event_data.get('signature', 'unknown')
            dex_id = event_data.get('dex_id', 'unknown')
            pool_address = event_data.get('pool_address', 'unknown')
            
            if price:
                self._record_price_update(price, 'swap', signature, dex_id)
                print(f"🔥 SWAP PRICE UPDATE:")
                print(f"   💵 Price: ${price:.12f}")
                print(f"   🏢 DEX: {dex_id}")
                print(f"   🏊 Pool: {pool_address[:8]}...")
                print(f"   🔗 Signature: {signature[:16]}...")
                print()
                
            # Show additional details
            amount_in = event_data.get('amount_in')
            amount_out = event_data.get('amount_out')
            if amount_in and amount_out:
                print(f"   💱 Trade: {amount_in:.6f} → {amount_out:.6f}")
                
        except Exception as e:
            print(f"❌ Error handling swap event: {e}")
    
    async def _handle_account_event(self, event_data: Dict[str, Any]):
        """Handle account update events"""
        try:
            price = event_data.get('price')
            pool_address = event_data.get('pool_address', 'unknown')
            dex_id = event_data.get('dex_id', 'unknown')
            slot = event_data.get('slot')
            
            if price:
                self._record_price_update(price, 'account', f"slot_{slot}", dex_id)
                print(f"📊 ACCOUNT PRICE UPDATE:")
                print(f"   💵 Price: ${price:.12f}")
                print(f"   🏢 DEX: {dex_id}")
                print(f"   🏊 Pool: {pool_address[:8]}...")
                print(f"   📦 Slot: {slot}")
                print()
                
        except Exception as e:
            print(f"❌ Error handling account event: {e}")
    
    def _record_price_update(self, price: float, source: str, signature: str, dex_id: str):
        """Record a price update"""
        timestamp = time.time()
        self.price_updates.append({
            'timestamp': timestamp,
            'price': price,
            'source': source,
            'signature': signature,
            'dex_id': dex_id
        })
        self.last_price = price
        self.last_price_time = timestamp
    
    async def start_monitoring(self, mint: str, duration_seconds: int = 120):
        """Start monitoring a token"""
        try:
            # Get token info
            token_info = await self.token_db.get_token_info(mint)
            if not token_info:
                print(f"❌ Token {mint} not found in database")
                return False
            
            self.monitoring_token = mint
            symbol = token_info.get('symbol', 'Unknown')
            pair_address = token_info.get('pair_address')
            dex_id = token_info.get('dex_id', 'raydium_v4')
            
            if not pair_address:
                print(f"❌ No pair address found for {symbol}")
                return False
            
            print(f"🚀 STARTING REAL-TIME MONITORING")
            print(f"📊 Token: {symbol} ({mint[:8]}...)")
            print(f"🔗 Pair: {pair_address}")
            print(f"🏢 DEX: {dex_id}")
            print(f"⏱️ Duration: {duration_seconds}s")
            print("=" * 80)
            
            # CRITICAL: Start the blockchain listener with TaskGroup
            print("🚀 Starting blockchain listener TaskGroup...")
            self.listener_task = asyncio.create_task(self.blockchain_listener.run_forever())
            
            # Wait a moment for the listener to start
            await asyncio.sleep(3)
            
            # Check if the listener is running
            if self.listener_task.done():
                exception = self.listener_task.exception()
                if exception:
                    print(f"❌ Blockchain listener failed to start: {exception}")
                    return False
                else:
                    print("❌ Blockchain listener task completed unexpectedly")
                    return False
            
            print("✅ Blockchain listener TaskGroup started")
            
            # Start streaming for the specific token
            print(f"📡 Setting up monitoring for {symbol} pair {pair_address}")
            await self.market_data.start_streaming(mint, pair_address, dex_id)
            
            # Monitor for the specified duration
            self.start_time = time.time()
            last_status_time = self.start_time
            
            while time.time() - self.start_time < duration_seconds:
                await asyncio.sleep(2)
                
                current_time = time.time()
                
                # Print status every 15 seconds
                if current_time - last_status_time >= 15:
                    await self._print_status(current_time - self.start_time)
                    last_status_time = current_time
                
                # Check if listener task is still running
                if self.listener_task.done():
                    print("❌ Blockchain listener task stopped unexpectedly")
                    break
            
            print(f"\n✅ Monitoring completed!")
            await self._print_summary(duration_seconds)
            
        except Exception as e:
            print(f"❌ Error during monitoring: {e}")
            import traceback
            traceback.print_exc()
    
    async def _print_status(self, elapsed_seconds: int):
        """Print current status"""
        print(f"📈 STATUS - {elapsed_seconds:.0f}s elapsed")
        print(f"   🔥 Price Updates: {len(self.price_updates)}")
        print(f"   📊 Transactions: {self.transaction_count}")
        
        if self.last_price:
            time_since = time.time() - self.last_price_time
            print(f"   💵 Last Price: ${self.last_price:.12f} ({time_since:.0f}s ago)")
        else:
            print(f"   💵 Last Price: None")
            
        # Check WebSocket connections
        if self.blockchain_listener and hasattr(self.blockchain_listener, 'ws_connections'):
            active_connections = sum(1 for ws in self.blockchain_listener.ws_connections.values() 
                                   if ws and self.blockchain_listener._is_connection_open(ws))
            print(f"   🌐 Active Connections: {active_connections}")
            
        # Check listener task status
        if self.listener_task:
            if self.listener_task.done():
                print(f"   ⚠️ Listener Task: STOPPED")
            else:
                print(f"   ✅ Listener Task: RUNNING")
            
        print()
    
    async def _print_summary(self, duration_seconds: int):
        """Print final summary"""
        print(f"\n📋 MONITORING SUMMARY")
        print(f"⏱️ Duration: {duration_seconds}s")
        print(f"🔥 Total Price Updates: {len(self.price_updates)}")
        print(f"📊 Total Transactions: {self.transaction_count}")
        
        if self.price_updates:
            update_rate = len(self.price_updates) / (duration_seconds / 60)
            print(f"⚡ Update Rate: {update_rate:.1f} updates/min")
            
            # Show recent price updates
            print(f"\n📜 RECENT PRICE UPDATES:")
            for update in self.price_updates[-5:]:
                time_ago = time.time() - update['timestamp']
                print(f"   {time_ago:.0f}s ago: ${update['price']:.12f} ({update['source']}, {update['dex_id']})")
        else:
            print(f"⚠️ No price updates received - WebSocket may not be working properly")
            
        # WebSocket diagnostics
        if self.blockchain_listener:
            if hasattr(self.blockchain_listener, 'ws_connections'):
                total_connections = len(self.blockchain_listener.ws_connections)
                active_connections = sum(1 for ws in self.blockchain_listener.ws_connections.values() 
                                       if ws and self.blockchain_listener._is_connection_open(ws))
                print(f"🌐 WebSocket Status: {active_connections}/{total_connections} active")
            
            if hasattr(self.blockchain_listener, '_pool_subscriptions'):
                print(f"📡 Pool Subscriptions: {len(self.blockchain_listener._pool_subscriptions)}")
    
    async def close(self):
        """Clean up resources"""
        try:
            # Stop blockchain listener task
            if self.listener_task and not self.listener_task.done():
                print("🛑 Stopping blockchain listener task...")
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
                
            print("✅ Resources cleaned up")
        except Exception as e:
            print(f"❌ Error during cleanup: {e}")

async def main():
    """Main monitoring function"""
    monitor = RealTimeMonitor()
    
    try:
        # Initialize
        if not await monitor.initialize():
            print("❌ Failed to initialize monitor")
            return
        
        # Use BONK token from database
        bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        
        # Start monitoring for 2 minutes
        await monitor.start_monitoring(bonk_mint, duration_seconds=120)
        
    except Exception as e:
        print(f"❌ Error in main: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await monitor.close()

if __name__ == '__main__':
    print("🎯 SupertradeX Real-Time Blockchain Monitor")
    print("=" * 80)
    asyncio.run(main()) 