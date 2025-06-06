#!/usr/bin/env python3
"""
PROOF OF CONCEPT: Real-time Blockchain Price vs API Price Comparison
Shows side-by-side price updates every 15 seconds to prove functionality.
"""

import asyncio
import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.encryption import decrypt_env_file, get_encryption_password
from dotenv import dotenv_values
import io

# Setup environment
env_dir = Path(__file__).parent / "config"
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

class BlockchainVsApiPriceComparison:
    def __init__(self):
        self.settings = None
        self.market_data = None
        self.token_db = None
        self.blockchain_listener = None
        
        # Price tracking
        self.blockchain_prices = []  # List of (timestamp, price, source, confidence)
        self.api_prices = []  # List of (timestamp, price, source)
        self.last_blockchain_price = None
        self.last_api_price = None
        self.price_updates_count = 0
        self.transaction_count = 0
        
        # Monitoring
        self.start_time = None
        self.monitoring_token = None
        
    async def initialize(self):
        """Initialize all components"""
        try:
            from config.settings import Settings
            from data.market_data import MarketData
            from data.token_database import TokenDatabase
            
            self.settings = Settings()
            
            # Initialize database
            self.token_db = TokenDatabase(self.settings.DATABASE_FILE_PATH, self.settings)
            await self.token_db.initialize()
            
            # Initialize market data with blockchain listening
            self.market_data = MarketData(self.settings, token_db=self.token_db)
            await self.market_data.initialize()
            
            # CRITICAL: Initialize blockchain listener separately
            print("🔌 Initializing blockchain listener...")
            await self.market_data.initialize_blockchain_listener()
            
            # Set up our callback for blockchain events
            if self.market_data.blockchain_listener:
                self.blockchain_listener = self.market_data.blockchain_listener
                
                # START the run_forever task - this is critical for WebSocket connections
                print("🚀 Starting blockchain listener task...")
                self.market_data._blockchain_listener_task = asyncio.create_task(
                    self.blockchain_listener.run_forever()
                )
                # Give it a moment to start up
                await asyncio.sleep(2)
                
                # Override the callback to capture real-time price updates
                self.blockchain_listener.set_callback(self._blockchain_event_callback)
                print("✅ Blockchain listener initialized and callback set")
                
            print("✅ Price comparison monitor initialized")
            return True
            
        except Exception as e:
            print(f"❌ Error initializing: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _blockchain_event_callback(self, event_data: Dict):
        """Process blockchain events and extract real-time prices"""
        try:
            self.transaction_count += 1
            event_type = event_data.get('type')
            
            if event_type == 'log_update':
                await self._handle_swap_transaction(event_data)
            elif event_type == 'account_update':
                await self._handle_account_update(event_data)
                
            # Also forward to the original MarketData callback
            if hasattr(self.market_data, '_handle_blockchain_update'):
                await self.market_data._handle_blockchain_update(event_data)
                
        except Exception as e:
            print(f"Error in blockchain callback: {e}")
    
    async def _handle_swap_transaction(self, event_data: Dict):
        """Extract price from swap transaction logs"""
        try:
            dex_id = event_data.get('dex_id')
            logs = event_data.get('logs', [])
            signature = event_data.get('signature', 'N/A')
            
            if not logs:
                return
                
            price_info = None
            
            # Parse based on DEX type
            if dex_id == 'raydium_v4':
                price_info = await self._extract_raydium_v4_price(logs, signature)
            elif dex_id == 'pumpswap':
                price_info = await self._extract_pumpswap_price(logs, signature)
            elif dex_id == 'raydium_clmm':
                price_info = await self._extract_raydium_clmm_price(logs, signature)
                
            if price_info and price_info.get('price') and price_info['price'] > 0:
                await self._record_blockchain_price(price_info, signature)
                
        except Exception as e:
            print(f"Error handling swap transaction: {e}")
    
    async def _handle_account_update(self, event_data: Dict):
        """Extract price from account state updates"""
        try:
            dex_id = event_data.get('dex_id')
            raw_data = event_data.get('raw_data')
            pool_address = event_data.get('pool_address', 'N/A')
            
            if not raw_data or not isinstance(raw_data, list) or not raw_data:
                return
                
            price_info = None
            
            if dex_id == 'pumpswap':
                price_info = await self._extract_pumpswap_account_price(raw_data[0], pool_address)
                
            if price_info and price_info.get('price') and price_info['price'] > 0:
                await self._record_blockchain_price(price_info, f"account:{pool_address[:8]}")
                
        except Exception as e:
            print(f"Error handling account update: {e}")
    
    async def _extract_raydium_v4_price(self, logs: List[str], signature: str) -> Optional[Dict]:
        """Extract price from Raydium V4 swap logs"""
        try:
            if hasattr(self.market_data, '_parse_raydium_v4_swap_log'):
                swap_info = self.market_data._parse_raydium_v4_swap_log(logs)
                if swap_info:
                    # Debug: print what we got
                    print(f"Raydium V4 parsed data: {swap_info}")
                    
                    if swap_info.get('found_swap'):
                        amount_in = swap_info.get('amount_in')
                        amount_out = swap_info.get('amount_out')
                        
                        if amount_in and amount_out and amount_in > 0:
                            # Raw price calculation
                            raw_price = amount_out / amount_in
                            
                            # Apply decimal adjustments - this is crucial for accurate pricing
                            # For BONK: 5 decimals, SOL: 9 decimals
                            token_decimals = swap_info.get('token_decimals', 6)  # Default to 6
                            sol_decimals = 9
                            
                            # Adjust for decimal differences
                            if token_decimals != sol_decimals:
                                decimal_adjustment = 10 ** (sol_decimals - token_decimals)
                                adjusted_price = raw_price * decimal_adjustment
                            else:
                                adjusted_price = raw_price
                            
                            print(f"Raydium V4 price calculation: raw={raw_price}, decimals={token_decimals}, adjusted={adjusted_price}")
                            
                            return {
                                'price': adjusted_price,
                                'raw_price': raw_price,
                                'amount_in': amount_in,
                                'amount_out': amount_out,
                                'token_decimals': token_decimals,
                                'source': 'raydium_v4_swap',
                                'confidence': 0.8,
                                'signature': signature,
                                'direction': swap_info.get('direction', 'unknown')
                            }
            return None
        except Exception as e:
            print(f"Error extracting Raydium V4 price: {e}")
            return None
    
    async def _extract_pumpswap_price(self, logs: List[str], signature: str) -> Optional[Dict]:
        """Extract price from PumpSwap logs"""
        try:
            if hasattr(self.market_data, '_parse_pumpswap_amm_log'):
                swap_info = self.market_data._parse_pumpswap_amm_log(logs)
                if swap_info:
                    # Debug: print what we got
                    print(f"PumpSwap parsed data: {swap_info}")
                    
                    # Try different price fields that might be available
                    price = None
                    if 'price' in swap_info and swap_info['price']:
                        price = float(swap_info['price'])
                    elif 'price_per_token' in swap_info and swap_info['price_per_token']:
                        price = float(swap_info['price_per_token'])
                    elif 'calculated_price' in swap_info and swap_info['calculated_price']:
                        price = float(swap_info['calculated_price'])
                    
                    # Try to calculate from amounts if no direct price
                    if not price and 'sol_amount' in swap_info and 'token_amount' in swap_info:
                        sol_amount = swap_info.get('sol_amount', 0)
                        token_amount = swap_info.get('token_amount', 0)
                        if token_amount > 0:
                            price = sol_amount / token_amount
                    
                    if price and price > 0:
                        return {
                            'price': price,
                            'source': 'pumpswap_swap',
                            'confidence': 0.9,
                            'signature': signature,
                            'direction': swap_info.get('direction', 'unknown'),
                            'sol_amount': swap_info.get('sol_amount'),
                            'token_amount': swap_info.get('token_amount'),
                            **swap_info
                        }
            return None
        except Exception as e:
            print(f"Error extracting PumpSwap price: {e}")
            return None
    
    async def _extract_raydium_clmm_price(self, logs: List[str], signature: str) -> Optional[Dict]:
        """Extract price from Raydium CLMM logs"""
        try:
            if hasattr(self.market_data, '_parse_raydium_clmm_swap_log'):
                swap_info = self.market_data._parse_raydium_clmm_swap_log(logs)
                if swap_info and swap_info.get('found_swap'):
                    # Try to calculate from amounts
                    amount_a = swap_info.get('amount_a')
                    amount_b = swap_info.get('amount_b')
                    
                    if amount_a and amount_b and amount_a != 0:
                        price = abs(amount_b / amount_a)
                        return {
                            'price': price,
                            'amount_a': amount_a,
                            'amount_b': amount_b,
                            'source': 'raydium_clmm_swap',
                            'confidence': 0.7,
                            'signature': signature
                        }
                        
                    # Try to extract from sqrt_price if available
                    sqrt_price = swap_info.get('sqrt_price')
                    if sqrt_price and sqrt_price > 0 and sqrt_price < 2**96:
                        # Convert sqrt_price to actual price
                        price = (sqrt_price ** 2) / (2 ** 128)
                        return {
                            'price': price,
                            'sqrt_price': sqrt_price,
                            'source': 'raydium_clmm_sqrt',
                            'confidence': 0.6,
                            'signature': signature
                        }
            return None
        except Exception as e:
            print(f"Error extracting Raydium CLMM price: {e}")
            return None
    
    async def _extract_pumpswap_account_price(self, account_data_b64: str, pool_address: str) -> Optional[Dict]:
        """Extract price from PumpSwap account state"""
        try:
            if hasattr(self.blockchain_listener, '_pumpswap_amm_layout'):
                layout = self.blockchain_listener._pumpswap_amm_layout
                if layout:
                    import base64
                    decoded_data = base64.b64decode(account_data_b64)
                    parsed_state = layout.parse(decoded_data)
                    
                    token_decimals = parsed_state.decimals
                    sol_decimals = 9
                    token_balance_raw = parsed_state.token_balance
                    sol_balance_raw = parsed_state.sol_balance

                    if token_balance_raw > 0 and sol_balance_raw > 0 and token_decimals is not None:
                        price = (sol_balance_raw / (10**sol_decimals)) / (token_balance_raw / (10**token_decimals))
                        return {
                            'price': price,
                            'token_reserve': token_balance_raw / (10**token_decimals),
                            'sol_reserve': sol_balance_raw / (10**sol_decimals),
                            'source': 'pumpswap_account',
                            'confidence': 0.9
                        }
            return None
        except Exception as e:
            print(f"Error extracting PumpSwap account price: {e}")
            return None
    
    async def _record_blockchain_price(self, price_info: Dict, signature: str):
        """Record a new blockchain price update"""
        timestamp = time.time()
        price = price_info['price']
        source = price_info['source']
        confidence = price_info.get('confidence', 0.5)
        
        self.blockchain_prices.append((timestamp, price, source, confidence))
        self.last_blockchain_price = price
        self.price_updates_count += 1
        
        # Format price appropriately
        if price >= 1:
            price_str = f"${price:.6f}"
        elif price >= 0.001:
            price_str = f"${price:.8f}"
        else:
            price_str = f"${price:.12f}"
        
        print(f"🔥 BLOCKCHAIN PRICE UPDATE #{self.price_updates_count}")
        print(f"   💵 Price: {price_str}")
        print(f"   📊 Source: {source}")
        print(f"   🎯 Confidence: {confidence:.1f}")
        print(f"   🔗 Signature: {signature[:16]}...")
        
        # Show additional details for debugging
        if price_info.get('direction'):
            direction_emoji = "🟢" if price_info['direction'] == 'buy' else "🔴"
            print(f"   {direction_emoji} Direction: {price_info['direction'].upper()}")
        
        if price_info.get('amount_in') and price_info.get('amount_out'):
            print(f"   💱 Amounts: {price_info['amount_in']:.2e} → {price_info['amount_out']:.2e}")
        
        if price_info.get('raw_price'):
            print(f"   📐 Raw Price: {price_info['raw_price']:.2e}")
        
        print()
        
        # Immediately compare with API if we have recent API data
        if self.last_api_price:
            await self._show_quick_comparison(price, self.last_api_price)
    
    async def _get_api_price(self) -> Optional[float]:
        """Get current price from DexScreener API"""
        try:
            if not self.monitoring_token:
                return None
                
            price_data = await self.market_data.get_token_price(self.monitoring_token, force_refresh=True)
            if price_data and price_data.get('priceUsd'):
                return float(price_data['priceUsd'])
            return None
        except Exception as e:
            print(f"Error getting API price: {e}")
            return None
    
    async def _record_api_price(self, price: float):
        """Record a new API price update"""
        timestamp = time.time()
        self.api_prices.append((timestamp, price, 'dexscreener_api'))
        self.last_api_price = price
        
        # Format and display API price update
        if price >= 1:
            price_str = f"${price:.6f}"
        elif price >= 0.001:
            price_str = f"${price:.8f}"
        else:
            price_str = f"${price:.12f}"
        
        print(f"🌐 API PRICE UPDATE: {price_str}")
    
    async def _show_quick_comparison(self, blockchain_price: float, api_price: float):
        """Show quick price comparison immediately when blockchain price updates"""
        if blockchain_price and api_price:
            difference = abs(blockchain_price - api_price)
            percentage_diff = (difference / api_price) * 100 if api_price > 0 else 0
            
            print(f"   ⚡ INSTANT COMPARISON:")
            print(f"   🔗 Blockchain: ${blockchain_price:.10f}")
            print(f"   🌐 API:        ${api_price:.10f}")
            print(f"   📊 Diff:       {percentage_diff:.2f}%")
            
            if percentage_diff < 5:
                print(f"   ✅ VERY CLOSE!")
            elif percentage_diff < 15:
                print(f"   ⚠️ REASONABLY CLOSE")
            else:
                print(f"   ❌ SIGNIFICANT DIFFERENCE")
            print()
    
    async def _print_price_comparison(self, elapsed_seconds: int):
        """Print detailed price comparison every 15 seconds"""
        print("=" * 80)
        print(f"📊 PRICE COMPARISON UPDATE - {elapsed_seconds:.0f}s elapsed")
        print("=" * 80)
        
        # Get current API price
        api_price = await self._get_api_price()
        if api_price:
            await self._record_api_price(api_price)
        
        # Format prices
        blockchain_price_str = "N/A"
        api_price_str = "N/A"
        
        if self.last_blockchain_price:
            if self.last_blockchain_price >= 1:
                blockchain_price_str = f"${self.last_blockchain_price:.6f}"
            elif self.last_blockchain_price >= 0.001:
                blockchain_price_str = f"${self.last_blockchain_price:.8f}"
            else:
                blockchain_price_str = f"${self.last_blockchain_price:.12f}"
        
        if api_price:
            if api_price >= 1:
                api_price_str = f"${api_price:.6f}"
            elif api_price >= 0.001:
                api_price_str = f"${api_price:.8f}"
            else:
                api_price_str = f"${api_price:.12f}"
        
        # Print comparison
        print(f"🔗 BLOCKCHAIN PRICE: {blockchain_price_str}")
        print(f"🌐 API PRICE:        {api_price_str}")
        
        # Calculate difference if both prices available
        if self.last_blockchain_price and api_price:
            difference = abs(self.last_blockchain_price - api_price)
            percentage_diff = (difference / api_price) * 100 if api_price > 0 else 0
            
            print(f"📏 DIFFERENCE:       ${difference:.10f}")
            print(f"📊 PERCENTAGE DIFF:  {percentage_diff:.2f}%")
            
            if percentage_diff < 5:
                print("✅ PRICES ARE VERY CLOSE! (<5% difference)")
            elif percentage_diff < 15:
                print("⚠️ PRICES ARE REASONABLY CLOSE! (<15% difference)")
            else:
                print("❌ PRICES HAVE SIGNIFICANT DIFFERENCE! (>15% difference)")
        
        # Statistics
        print(f"📈 BLOCKCHAIN UPDATES: {self.price_updates_count}")
        print(f"📊 TOTAL TRANSACTIONS: {self.transaction_count}")
        print(f"⚡ UPDATE RATE: {self.price_updates_count / (elapsed_seconds / 60):.1f} updates/min")
        
        # Recent price history with more details
        if len(self.blockchain_prices) > 0:
            print(f"📜 RECENT BLOCKCHAIN PRICES:")
            recent_prices = self.blockchain_prices[-5:]  # Last 5 prices
            for ts, price, source, conf in recent_prices:
                time_ago = time.time() - ts
                if price >= 0.001:
                    price_str = f"${price:.8f}"
                else:
                    price_str = f"${price:.12f}"
                print(f"     {time_ago:.0f}s ago: {price_str} ({source}, conf:{conf:.1f})")
        
        if len(self.api_prices) > 0:
            print(f"🌐 RECENT API PRICES:")
            recent_api = self.api_prices[-5:]  # Last 5 prices
            for ts, price, source in recent_api:
                time_ago = time.time() - ts
                if price >= 0.001:
                    price_str = f"${price:.8f}"
                else:
                    price_str = f"${price:.12f}"
                print(f"     {time_ago:.0f}s ago: {price_str} ({source})")
        
        # Price trend analysis
        if len(self.blockchain_prices) >= 2:
            latest_blockchain = self.blockchain_prices[-1][1]
            previous_blockchain = self.blockchain_prices[-2][1]
            trend = "📈 UP" if latest_blockchain > previous_blockchain else "📉 DOWN"
            change = ((latest_blockchain - previous_blockchain) / previous_blockchain) * 100
            print(f"📊 BLOCKCHAIN TREND: {trend} ({change:+.2f}%)")
        
        if len(self.api_prices) >= 2:
            latest_api = self.api_prices[-1][1]
            previous_api = self.api_prices[-2][1]
            trend = "📈 UP" if latest_api > previous_api else "📉 DOWN"
            change = ((latest_api - previous_api) / previous_api) * 100
            print(f"🌐 API TREND: {trend} ({change:+.2f}%)")
        
        print("=" * 80)
        print()
    
    async def start_monitoring(self, mint: str, duration_seconds: int = 300):
        """Start comprehensive price monitoring with comparison"""
        try:
            # Get token info from database
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
            
            print(f"🚀 STARTING BLOCKCHAIN vs API PRICE COMPARISON")
            print(f"📊 Token: {symbol} ({mint[:8]}...)")
            print(f"🔗 Pair: {pair_address}")
            print(f"🏢 DEX: {dex_id}")
            print(f"⏱️ Duration: {duration_seconds}s")
            print(f"📊 Update Interval: Every 15 seconds")
            print(f"🔄 Sources: Blockchain WebSocket vs DexScreener API")
            print("=" * 80)
            
            # Start blockchain streaming for the token
            await self.market_data.start_streaming(mint, pair_address, dex_id)
            
            # Initial API price
            initial_api_price = await self._get_api_price()
            if initial_api_price:
                await self._record_api_price(initial_api_price)
                print(f"💰 Initial API Price: ${initial_api_price:.10f}")
            
            # Wait and monitor with 15-second updates
            self.start_time = time.time()
            last_update_time = self.start_time
            last_api_fetch_time = self.start_time
            
            while time.time() - self.start_time < duration_seconds:
                await asyncio.sleep(2)  # Check every 2 seconds for more responsiveness
                
                current_time = time.time()
                
                # Fetch API price every 10 seconds
                if current_time - last_api_fetch_time >= 10:
                    api_price = await self._get_api_price()
                    if api_price:
                        await self._record_api_price(api_price)
                    last_api_fetch_time = current_time
                
                # Print comparison every 15 seconds
                if current_time - last_update_time >= 15:
                    await self._print_price_comparison(current_time - self.start_time)
                    last_update_time = current_time
            
            print(f"\n✅ Monitoring completed!")
            await self._print_final_comparison(duration_seconds)
            
        except Exception as e:
            print(f"❌ Error during monitoring: {e}")
            import traceback
            traceback.print_exc()
    
    async def _print_final_comparison(self, duration_seconds: int):
        """Print final comparison summary"""
        print("=" * 80)
        print(f"📊 FINAL COMPARISON SUMMARY ({duration_seconds}s)")
        print("=" * 80)
        
        print(f"🔥 Total Blockchain Price Updates: {self.price_updates_count}")
        print(f"📊 Total Transactions Processed: {self.transaction_count}")
        print(f"📈 Total API Price Fetches: {len(self.api_prices)}")
        print(f"⚡ Blockchain Update Rate: {self.price_updates_count / (duration_seconds / 60):.1f} updates/min")
        
        if self.last_blockchain_price and self.last_api_price:
            difference = abs(self.last_blockchain_price - self.last_api_price)
            percentage_diff = (difference / self.last_api_price) * 100
            
            print(f"\n🎯 FINAL PRICE COMPARISON:")
            print(f"   🔗 Final Blockchain Price: ${self.last_blockchain_price:.10f}")
            print(f"   🌐 Final API Price:        ${self.last_api_price:.10f}")
            print(f"   📏 Final Difference:       ${difference:.10f}")
            print(f"   📊 Final Percentage Diff:  {percentage_diff:.2f}%")
            
            if percentage_diff < 5:
                print(f"   ✅ EXCELLENT: Blockchain and API prices are very close!")
            elif percentage_diff < 15:
                print(f"   ⚠️ GOOD: Blockchain and API prices are reasonably close!")
            else:
                print(f"   ❌ ATTENTION: Significant difference between sources!")
        
        # Source breakdown
        if self.blockchain_prices:
            sources = {}
            for _, _, source, _ in self.blockchain_prices:
                sources[source] = sources.get(source, 0) + 1
            
            print(f"\n📊 BLOCKCHAIN PRICE SOURCES:")
            for source, count in sources.items():
                print(f"   {source}: {count} updates")
        
        if self.price_updates_count > 0:
            print(f"\n✅ PROOF OF FUNCTIONALITY: Real-time blockchain monitoring is WORKING!")
            print(f"   📈 Successfully extracted {self.price_updates_count} price updates from live transactions")
            print(f"   🔗 Successfully compared with {len(self.api_prices)} API price fetches")
        else:
            print(f"\n⚠️ No blockchain price updates extracted - need to investigate parsing logic")
    
    async def close(self):
        """Clean up resources"""
        try:
            # Cancel blockchain listener task if running
            if hasattr(self.market_data, '_blockchain_listener_task') and self.market_data._blockchain_listener_task:
                print("🛑 Stopping blockchain listener task...")
                self.market_data._blockchain_listener_task.cancel()
                try:
                    await self.market_data._blockchain_listener_task
                except asyncio.CancelledError:
                    pass  # Expected when cancelling
                    
            if self.market_data:
                await self.market_data.close()
            if self.token_db:
                await self.token_db.close()
            print("✅ Resources cleaned up")
        except Exception as e:
            print(f"Error during cleanup: {e}")

async def main():
    monitor = BlockchainVsApiPriceComparison()
    
    try:
        # Initialize
        success = await monitor.initialize()
        if not success:
            return
        
        # Get BONK from database and start monitoring
        bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        
        print("🎯 Starting 2-minute PROOF-OF-CONCEPT: Blockchain vs API Price Comparison...")
        await monitor.start_monitoring(bonk_mint, duration_seconds=120)  # 2 minutes
        
    except KeyboardInterrupt:
        print("\n⏹️ Monitoring stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await monitor.close()

if __name__ == "__main__":
    asyncio.run(main()) 