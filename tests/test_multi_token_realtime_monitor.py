#!/usr/bin/env python3
"""
Multi-Token Real-Time Price Monitor
Monitors all tokens in database for live price updates from blockchain transactions.
Shows real-time price feeds for multiple tokens with DEX source information.
"""

import asyncio
import sys
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import json
from collections import defaultdict

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

class MultiTokenPriceMonitor:
    def __init__(self):
        self.settings = None
        self.token_db = None
        self.market_data = None
        self.blockchain_listener = None
        
        # Token tracking
        self.tokens = {}  # mint -> token_info
        self.price_histories = defaultdict(list)  # mint -> [price_updates]
        self.last_prices = {}  # mint -> latest_price
        self.last_price_times = {}  # mint -> timestamp
        self.price_update_counts = defaultdict(int)  # mint -> count
        self.start_time = None
        
        # Display settings
        self.max_display_tokens = 10  # Show top N tokens with recent activity
        
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
        
    def _get_token_symbol(self, mint: str) -> str:
        """Get token symbol or shortened mint address"""
        if mint in self.tokens:
            symbol = self.tokens[mint].get('symbol', '')
            if symbol:
                return symbol
        return mint[:8] + "..."
        
    async def initialize(self):
        """Initialize all components and load tokens"""
        try:
            print("🔧 Initializing Multi-Token Price Monitor...")
            
            self.settings = Settings()
            
            # Initialize database
            self.token_db = TokenDatabase(self.settings.DATABASE_FILE_PATH, self.settings)
            await self.token_db.initialize()
            
            # Load all tokens from database
            await self._load_tokens()
            
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
                
            print("✅ Multi-Token Price Monitor initialized")
            return True
            
        except Exception as e:
            print(f"❌ Error initializing: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    async def _load_tokens(self):
        """Load all tokens from database"""
        try:
            print("📊 Loading tokens from database...")
            
            # Get all valid tokens
            token_objects = await self.token_db.get_valid_tokens()
            
            for token in token_objects:
                mint = token.mint
                token_info = {
                    'id': token.id,
                    'mint': mint,
                    'symbol': token.symbol,
                    'name': token.name,
                    'pair_address': token.pair_address,
                    'dex_id': token.dex_id,
                    'is_valid': token.is_valid,
                    'status': token.monitoring_status
                }
                self.tokens[mint] = token_info
                
            print(f"✅ Loaded {len(self.tokens)} tokens for monitoring:")
            for mint, token in self.tokens.items():
                symbol = token.get('symbol', 'Unknown')
                dex_id = token.get('dex_id', 'unknown')
                print(f"   • {symbol:<10} | {mint[:8]}... | {dex_id}")
                
        except Exception as e:
            print(f"❌ Error loading tokens: {e}")
            raise
    
    async def _price_event_callback(self, event_data: Dict[str, Any]):
        """Process blockchain events for price updates"""
        try:
            # Get token address from event
            token_address = event_data.get('token_address') or event_data.get('mint')
            if not token_address or token_address not in self.tokens:
                return  # Not one of our monitored tokens
                
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
                
                self.price_histories[token_address].append(price_info)
                self.last_prices[token_address] = price
                self.last_price_times[token_address] = timestamp
                self.price_update_counts[token_address] += 1
                
                # Print immediate price update
                time_str = self._format_timestamp(timestamp)
                price_str = self._format_price(price)
                symbol = self._get_token_symbol(token_address)
                print(f"🔥 {time_str} | {symbol:<10} | {price_str:<15} | {dex_id:<12} | {event_type}")
                
                # Keep only last 50 updates per token for performance
                if len(self.price_histories[token_address]) > 50:
                    self.price_histories[token_address] = self.price_histories[token_address][-50:]
                    
        except Exception as e:
            print(f"❌ Error in price callback: {e}")
    
    async def start_monitoring(self, duration_seconds: int = 300):
        """Start monitoring all tokens for specified duration"""
        try:
            print(f"\n🚀 STARTING MULTI-TOKEN REAL-TIME PRICE MONITORING")
            print(f"📊 Monitoring {len(self.tokens)} tokens")
            print(f"⏱️ Duration: {duration_seconds}s")
            print("=" * 90)
            
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
            
            # Start streaming for all tokens
            print(f"📡 Setting up monitoring for all tokens...")
            for mint, token_info in self.tokens.items():
                pair_address = token_info.get('pair_address')
                dex_id = token_info.get('dex_id', 'raydium_v4')
                
                if pair_address:
                    try:
                        await self.market_data.start_streaming(mint, pair_address, dex_id)
                        symbol = token_info.get('symbol', 'Unknown')
                        print(f"   ✅ Started monitoring {symbol} on {dex_id}")
                    except Exception as e:
                        symbol = token_info.get('symbol', 'Unknown')
                        print(f"   ❌ Failed to start monitoring {symbol}: {e}")
                else:
                    symbol = token_info.get('symbol', 'Unknown')
                    print(f"   ⚠️ No pair address for {symbol}")
            
            # Monitor for the specified duration
            self.start_time = time.time()
            last_status_time = self.start_time
            
            print(f"\n💰 LIVE MULTI-TOKEN PRICE FEED:")
            print(f"{'Time':<12} | {'Token':<10} | {'Price':<15} | {'DEX':<12} | {'Event':<10}")
            print("-" * 90)
            
            while time.time() - self.start_time < duration_seconds:
                await asyncio.sleep(0.1)  # Check frequently for responsiveness
                
                current_time = time.time()
                
                # Print periodic status every 45 seconds
                if current_time - last_status_time >= 45:
                    await self._print_status(current_time - self.start_time)
                    last_status_time = current_time
                
                # Check if listener is still running
                if self.listener_task.done():
                    print("❌ Blockchain listener stopped unexpectedly")
                    break
            
            print(f"\n✅ Multi-token monitoring completed!")
            await self._print_summary(duration_seconds)
            
        except Exception as e:
            print(f"❌ Error during monitoring: {e}")
            import traceback
            traceback.print_exc()
    
    async def _print_status(self, elapsed_seconds: int):
        """Print current monitoring status"""
        print(f"\n📈 STATUS UPDATE - {elapsed_seconds:.0f}s elapsed")
        
        # Count total updates
        total_updates = sum(self.price_update_counts.values())
        active_tokens = len([mint for mint in self.price_update_counts if self.price_update_counts[mint] > 0])
        
        print(f"   🔥 Total Price Updates: {total_updates}")
        print(f"   📊 Active Tokens: {active_tokens}/{len(self.tokens)}")
        
        # Show most active tokens
        if self.price_update_counts:
            sorted_tokens = sorted(self.price_update_counts.items(), key=lambda x: x[1], reverse=True)
            print(f"   🏆 Most Active Tokens:")
            for i, (mint, count) in enumerate(sorted_tokens[:5]):
                if count > 0:
                    symbol = self._get_token_symbol(mint)
                    last_price = self.last_prices.get(mint)
                    if last_price:
                        price_str = self._format_price(last_price)
                        time_since = time.time() - self.last_price_times[mint]
                        print(f"      {i+1}. {symbol:<10} | {count:>3} updates | {price_str} ({time_since:.0f}s ago)")
        
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
        print(f"\n📋 MULTI-TOKEN MONITORING SUMMARY")
        print(f"⏱️ Duration: {duration_seconds}s")
        
        total_updates = sum(self.price_update_counts.values())
        active_tokens = len([mint for mint in self.price_update_counts if self.price_update_counts[mint] > 0])
        
        print(f"🔥 Total Price Updates: {total_updates}")
        print(f"📊 Active Tokens: {active_tokens}/{len(self.tokens)}")
        
        if total_updates > 0:
            update_rate = total_updates / (duration_seconds / 60)
            print(f"⚡ Overall Update Rate: {update_rate:.1f} updates/min")
            
            # Show detailed token statistics
            print(f"\n📊 TOKEN PERFORMANCE:")
            print(f"{'Token':<12} | {'Updates':<8} | {'Latest Price':<15} | {'DEX':<12} | {'Rate/min':<8}")
            print("-" * 80)
            
            sorted_tokens = sorted(self.price_update_counts.items(), key=lambda x: x[1], reverse=True)
            for mint, count in sorted_tokens:
                if count > 0:
                    symbol = self._get_token_symbol(mint)
                    last_price = self.last_prices.get(mint, 0)
                    price_str = self._format_price(last_price) if last_price else "No data"
                    dex_id = self.tokens[mint].get('dex_id', 'unknown')
                    rate = count / (duration_seconds / 60)
                    
                    print(f"{symbol:<12} | {count:<8} | {price_str:<15} | {dex_id:<12} | {rate:.1f}")
            
            # Show price volatility for most active tokens
            print(f"\n📈 PRICE VOLATILITY (Top 3 Active Tokens):")
            for mint, count in sorted_tokens[:3]:
                if count > 1 and mint in self.price_histories:
                    symbol = self._get_token_symbol(mint)
                    prices = [p['price'] for p in self.price_histories[mint]]
                    
                    if len(prices) > 1:
                        min_price = min(prices)
                        max_price = max(prices)
                        avg_price = sum(prices) / len(prices)
                        volatility = ((max_price - min_price) / min_price) * 100 if min_price > 0 else 0
                        
                        print(f"   {symbol}: Min: {self._format_price(min_price)} | Max: {self._format_price(max_price)} | Avg: {self._format_price(avg_price)} | Vol: {volatility:.2f}%")
        else:
            print(f"⚠️ No price updates received for any token")
            print(f"   - Check WebSocket connections")
            print(f"   - Verify tokens are actively trading")
            print(f"   - Check DEX subscriptions")
    
    async def close(self):
        """Clean up resources"""
        try:
            print("\n🛑 Shutting down Multi-Token Price Monitor...")
            
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
                
            print("✅ Multi-Token Price Monitor shut down cleanly")
        except Exception as e:
            print(f"❌ Error during shutdown: {e}")

async def main():
    """Main monitoring function"""
    monitor = MultiTokenPriceMonitor()
    
    try:
        # Initialize
        if not await monitor.initialize():
            print("❌ Failed to initialize Multi-Token Price Monitor")
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
    print("🎯 SupertradeX Multi-Token Real-Time Price Monitor")
    print("=" * 90)
    asyncio.run(main()) 