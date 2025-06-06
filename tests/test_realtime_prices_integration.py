#!/usr/bin/env python3
"""
Test real-time price monitoring integration to verify blockchain listener is working
with proper price extraction and logging before integrating with main.py
"""

import asyncio
import sys
import os
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

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
                if value and key not in os.environ:
                    os.environ[key] = str(value)

class RealTimePriceTest:
    def __init__(self):
        self.settings = None
        self.market_data = None
        self.token_db = None
        self.blockchain_listener = None
        
        # Tracking
        self.price_updates = []
        self.event_count = 0
        self.last_price = None
        self.start_time = None
        
    async def initialize(self):
        """Initialize all components"""
        try:
            from config.settings import Settings
            from data.market_data import MarketData
            from data.token_database import TokenDatabase
            
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
                # Set our callback to capture price events
                self.blockchain_listener.set_callback(self._price_event_callback)
                print("✅ Blockchain listener callback set")
                
            print("✅ All components initialized successfully")
            return True
            
        except Exception as e:
            print(f"❌ Error initializing: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _price_event_callback(self, event_data: Dict):
        """Process blockchain events for real-time price updates"""
        try:
            self.event_count += 1
            event_type = event_data.get('type', 'unknown')
            dex_id = event_data.get('dex_id', 'unknown')
            
            # Log all events for debugging
            if self.event_count % 10 == 1:  # Log every 10th event
                print(f"📡 Event #{self.event_count}: {event_type} on {dex_id}")
            
            # Extract price from different event types
            price = None
            source = None
            
            if event_type == 'log_update':
                price, source = await self._extract_price_from_logs(event_data)
            elif event_type == 'account_update':
                price, source = await self._extract_price_from_account(event_data)
                
            if price and price > 0:
                await self._record_price_update(price, source, event_data)
                
            # Forward to MarketData if it has its own handler
            if hasattr(self.market_data, '_handle_blockchain_update'):
                await self.market_data._handle_blockchain_update(event_data)
                
        except Exception as e:
            print(f"❌ Error in price event callback: {e}")
    
    async def _extract_price_from_logs(self, event_data: Dict) -> tuple[Optional[float], Optional[str]]:
        """Extract price from swap transaction logs"""
        try:
            dex_id = event_data.get('dex_id', 'unknown')
            logs = event_data.get('logs', [])
            signature = event_data.get('signature', 'N/A')[:8]
            
            if not logs:
                return None, None
                
            price = None
            source = f"blockchain_swap_{dex_id}"
            
            # Try to use MarketData parsers
            if dex_id == 'raydium_v4' and hasattr(self.market_data, '_parse_raydium_v4_swap_log'):
                swap_info = self.market_data._parse_raydium_v4_swap_log(logs)
                if swap_info and swap_info.get('found_swap'):
                    amount_in = swap_info.get('amount_in')
                    amount_out = swap_info.get('amount_out')
                    if amount_in and amount_out and amount_in > 0:
                        price = amount_out / amount_in
                        # Apply decimal adjustments
                        in_decimals = swap_info.get('amount_in_decimals', 9)
                        out_decimals = swap_info.get('amount_out_decimals', 6)
                        if in_decimals != out_decimals:
                            decimal_factor = 10 ** (in_decimals - out_decimals)
                            price = price * decimal_factor
                            
            elif dex_id == 'pumpswap' and hasattr(self.market_data, '_parse_pumpswap_swap_log'):
                swap_info = self.market_data._parse_pumpswap_swap_log(logs)
                if swap_info and swap_info.get('found_swap'):
                    virtual_token_reserves = swap_info.get('virtual_token_reserves')
                    virtual_sol_reserves = swap_info.get('virtual_sol_reserves')
                    if virtual_token_reserves and virtual_sol_reserves and virtual_token_reserves > 0:
                        price = virtual_sol_reserves / virtual_token_reserves
                        
            return price, source
            
        except Exception as e:
            print(f"❌ Error extracting price from logs: {e}")
            return None, None
    
    async def _extract_price_from_account(self, event_data: Dict) -> tuple[Optional[float], Optional[str]]:
        """Extract price from account state updates"""
        try:
            dex_id = event_data.get('dex_id', 'unknown')
            
            # For now, account updates are less reliable for direct price extraction
            # This would require more complex parsing of account state data
            return None, f"blockchain_account_{dex_id}"
            
        except Exception as e:
            print(f"❌ Error extracting price from account: {e}")
            return None, None
    
    async def _record_price_update(self, price: float, source: str, event_data: Dict):
        """Record and display a price update"""
        try:
            current_time = time.time()
            elapsed = current_time - self.start_time if self.start_time else 0
            
            # Format price display
            if price >= 0.001:
                price_str = f"${price:.6f}"
            else:
                price_str = f"${price:.12f}"
            
            # Calculate change if we have a previous price
            change_str = ""
            if self.last_price and self.last_price > 0:
                change_pct = ((price - self.last_price) / self.last_price) * 100
                change_str = f" ({change_pct:+.2f}%)"
                
            # Extract additional info
            dex_id = event_data.get('dex_id', 'unknown')
            signature = event_data.get('signature', 'N/A')[:8]
            
            print(f"💰 {elapsed:>7.1f}s | {price_str:<15} | {dex_id:<10} | {source:<20} | {signature}{change_str}")
            
            # Store update
            self.price_updates.append({
                'timestamp': current_time,
                'price': price,
                'source': source,
                'dex_id': dex_id,
                'change_pct': change_pct if self.last_price else None
            })
            
            self.last_price = price
            
        except Exception as e:
            print(f"❌ Error recording price update: {e}")
    
    async def test_token_monitoring(self, mint: str, duration_seconds: int = 120):
        """Test real-time monitoring for a specific token"""
        try:
            # Get token info from database
            token_info = await self.token_db.get_token_info(mint)
            if not token_info:
                print(f"❌ Token {mint} not found in database")
                return False
                
            symbol = token_info.get('symbol', 'Unknown')
            pair_address = token_info.get('pair_address')
            dex_id = token_info.get('dex_id', 'raydium_v4')
            
            print(f"\n🚀 TESTING REAL-TIME PRICE MONITORING")
            print(f"📊 Token: {symbol} ({mint[:8]}...)")
            print(f"🔗 Pair: {pair_address}")
            print(f"🏢 DEX: {dex_id}")
            print(f"⏱️ Duration: {duration_seconds}s")
            print("=" * 90)
            
            # Start blockchain listener
            print("🚀 Starting blockchain listener...")
            listener_task = asyncio.create_task(self.blockchain_listener.run_forever())
            
            # Wait for listener to start
            await asyncio.sleep(2)
            
            # Check if listener started
            if listener_task.done():
                exception = listener_task.exception()
                if exception:
                    print(f"❌ Blockchain listener failed: {exception}")
                    return False
                    
            print("✅ Blockchain listener started")
            
            # Start streaming for this token
            print(f"📡 Starting price monitoring for {symbol}...")
            await self.market_data.start_streaming(mint, pair_address, dex_id)
            
            # Monitor for specified duration
            self.start_time = time.time()
            print(f"\n💰 REAL-TIME PRICE FEED ({symbol}):")
            print(f"{'Time':<8} | {'Price':<15} | {'DEX':<10} | {'Source':<20} | {'TX'}")
            print("-" * 90)
            
            last_status = self.start_time
            
            while time.time() - self.start_time < duration_seconds:
                await asyncio.sleep(0.1)
                
                current_time = time.time()
                
                # Print status every 30 seconds
                if current_time - last_status >= 30:
                    elapsed = current_time - self.start_time
                    print(f"📊 Status: {elapsed:.1f}s elapsed | {len(self.price_updates)} price updates | {self.event_count} events")
                    last_status = current_time
                
                # Check if listener is still running
                if listener_task.done():
                    print("❌ Blockchain listener stopped")
                    break
            
            # Stop streaming
            print(f"\n🛑 Stopping monitoring for {symbol}...")
            await self.market_data.stop_streaming(mint)
            
            # Cancel listener
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
                
            # Print final results
            print(f"\n✅ MONITORING COMPLETE")
            print(f"📊 Total Events: {self.event_count}")
            print(f"💰 Price Updates: {len(self.price_updates)}")
            
            if self.price_updates:
                first_price = self.price_updates[0]['price']
                last_price = self.price_updates[-1]['price']
                change = ((last_price - first_price) / first_price) * 100
                print(f"📈 Price Change: {change:+.2f}% (${first_price:.8f} → ${last_price:.8f})")
                
                # Show price sources
                sources = {}
                for update in self.price_updates:
                    source = update['source']
                    sources[source] = sources.get(source, 0) + 1
                print(f"📡 Sources: {sources}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error in token monitoring test: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def close(self):
        """Clean up resources"""
        try:
            if self.market_data:
                await self.market_data.close()
            if self.token_db:
                await self.token_db.close()
                
        except Exception as e:
            print(f"❌ Error during cleanup: {e}")

async def main():
    """Main test function"""
    monitor = RealTimePriceTest()
    
    try:
        # Initialize
        success = await monitor.initialize()
        if not success:
            print("❌ Failed to initialize")
            return
        
        # Get first token from database for testing
        tokens = await monitor.token_db.get_valid_tokens()
        if not tokens:
            print("❌ No tokens found in database")
            return
            
        # Find a token with valid pair address and dex_id
        test_token = None
        for token in tokens:
            if hasattr(token, 'pair_address') and hasattr(token, 'dex_id') and token.pair_address and token.dex_id:
                test_token = token
                break
                
        if not test_token:
            print("❌ No valid tokens found with pair_address and dex_id")
            return
            
        mint = test_token.mint
        
        # Test monitoring
        await monitor.test_token_monitoring(mint, duration_seconds=60)
        
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await monitor.close()

if __name__ == "__main__":
    asyncio.run(main()) 