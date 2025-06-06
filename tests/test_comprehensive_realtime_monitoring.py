#!/usr/bin/env python3
"""
Comprehensive real-time blockchain monitoring with proper price calculation.
Implements the complete fallback hierarchy:
1. PRIMARY: Helius WebSocket with swap transaction parsing
2. FALLBACK 1: Public RPC WebSocket with swap transaction parsing  
3. FALLBACK 2: DexScreener API polling

For Raydium V4: Subscribes to pool logs to capture swap events and calculates prices from swap amounts.
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

class ComprehensiveRealTimeMonitor:
    def __init__(self):
        self.settings = None
        self.market_data = None
        self.token_db = None
        self.blockchain_listener = None
        
        # Price tracking
        self.last_price = None
        self.last_price_time = None
        self.price_updates_count = 0
        self.transaction_count = 0
        self.price_sources = {'blockchain': 0, 'api': 0}
        
        # Connection status
        self.helius_connected = False
        self.public_rpc_connected = False
        self.api_fallback_active = False
        
        # Current token being monitored
        self.current_mint = None
        self.current_symbol = None
        self.current_pair = None
        self.current_dex = None
        
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
                # Replace the callback to capture events
                self.blockchain_listener.set_callback(self._blockchain_event_callback)
                
                # START the run_forever task - this is critical for WebSocket connections
                print("🚀 Starting blockchain listener task...")
                self.market_data._blockchain_listener_task = asyncio.create_task(
                    self.blockchain_listener.run_forever()
                )
                # Give it a moment to start up
                await asyncio.sleep(2)
                print("✅ Blockchain listener initialized and callback set")
                
            print("✅ Comprehensive real-time monitor initialized")
            return True
            
        except Exception as e:
            print(f"❌ Error initializing: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _blockchain_event_callback(self, event_data: Dict):
        """Process blockchain events - primary source for price updates"""
        try:
            event_type = event_data.get('type')
            
            if event_type == 'log_update':
                await self._handle_swap_transaction(event_data)
            elif event_type == 'account_update':
                await self._handle_account_update(event_data)
            
            # Update connection status
            source = event_data.get('source', '')
            if 'helius' in source.lower():
                self.helius_connected = True
            elif any(endpoint in source.lower() for endpoint in ['mainnet-beta', 'solana']):
                self.public_rpc_connected = True
                
            # Also forward to the original MarketData callback
            if hasattr(self.market_data, '_handle_blockchain_update'):
                await self.market_data._handle_blockchain_update(event_data)
                
        except Exception as e:
            print(f"❌ Error in blockchain callback: {e}")
    
    async def _handle_swap_transaction(self, event_data: Dict):
        """Handle swap transactions to extract real-time prices"""
        try:
            dex_id = event_data.get('dex_id')
            pool_address = event_data.get('pool_address')
            logs = event_data.get('logs', [])
            signature = event_data.get('signature', 'unknown')
            
            if not logs or pool_address != self.current_pair:
                return
                
            self.transaction_count += 1
            
            # Parse swap based on DEX
            swap_data = None
            
            if dex_id == 'raydium_v4':
                swap_data = await self._parse_raydium_v4_swap_precise(logs, pool_address)
            elif dex_id == 'pumpswap':
                swap_data = await self._parse_pumpswap_swap_precise(logs, pool_address)
            elif dex_id == 'raydium_clmm':
                swap_data = await self._parse_raydium_clmm_swap_precise(logs, pool_address)
            
            if swap_data and swap_data.get('price'):
                await self._update_realtime_price(
                    price=swap_data['price'],
                    source=f"blockchain_swap_{dex_id}",
                    metadata=swap_data,
                    signature=signature[:8]
                )
                
        except Exception as e:
            print(f"❌ Error handling swap transaction: {e}")
    
    async def _handle_account_update(self, event_data: Dict):
        """Handle account state updates for direct price calculation"""
        try:
            dex_id = event_data.get('dex_id')
            pool_address = event_data.get('pool_address')
            
            if pool_address != self.current_pair:
                return
            
            # For now, just log that we received an account update
            # Real price calculation from account state requires more complex implementation
            print(f"📊 Account update for {dex_id} pool {pool_address[:8]}...")
            
        except Exception as e:
            print(f"❌ Error handling account update: {e}")
    
    async def _parse_raydium_v4_swap_precise(self, logs: List[str], pool_address: str) -> Optional[Dict]:
        """Precise parsing of Raydium V4 swap transactions"""
        try:
            # Use the existing parser but enhance it
            if hasattr(self.market_data, '_parse_raydium_v4_swap_log'):
                swap_info = self.market_data._parse_raydium_v4_swap_log(logs)
                
                if swap_info and swap_info.get('found_swap'):
                    amount_in = swap_info.get('amount_in')
                    amount_out = swap_info.get('amount_out')
                    
                    if amount_in and amount_out and amount_in > 0:
                        # Calculate price based on swap direction
                        # For BONK/SOL: price = SOL_amount / BONK_amount
                        price = amount_out / amount_in
                        
                        # Adjust for decimals if available
                        in_decimals = swap_info.get('amount_in_decimals', 9)  # Default SOL decimals
                        out_decimals = swap_info.get('amount_out_decimals', 5)  # BONK has 5 decimals
                        
                        if in_decimals and out_decimals:
                            price = price * (10 ** (in_decimals - out_decimals))
                        
                        return {
                            'price': price,
                            'amount_in': amount_in,
                            'amount_out': amount_out,
                            'swap_direction': swap_info.get('swap_direction'),
                            'in_decimals': in_decimals,
                            'out_decimals': out_decimals,
                            'confidence': swap_info.get('parsing_confidence', 0.7),
                            'source': 'raydium_v4_swap_logs'
                        }
            
            return None
            
        except Exception as e:
            print(f"❌ Error parsing Raydium V4 swap: {e}")
            return None
    
    async def _parse_pumpswap_swap_precise(self, logs: List[str], pool_address: str) -> Optional[Dict]:
        """Precise parsing of PumpSwap swap transactions"""
        try:
            if hasattr(self.market_data, '_parse_pumpswap_amm_log'):
                swap_info = self.market_data._parse_pumpswap_amm_log(logs)
                if swap_info and swap_info.get('price'):
                    return {
                        'price': swap_info['price'],
                        'confidence': 0.8,
                        'source': 'pumpswap_swap_logs'
                    }
            return None
            
        except Exception as e:
            print(f"❌ Error parsing PumpSwap swap: {e}")
            return None
    
    async def _parse_raydium_clmm_swap_precise(self, logs: List[str], pool_address: str) -> Optional[Dict]:
        """Precise parsing of Raydium CLMM swap transactions"""
        try:
            if hasattr(self.market_data, '_parse_raydium_clmm_swap_log'):
                swap_info = self.market_data._parse_raydium_clmm_swap_log(logs)
                if swap_info and swap_info.get('price'):
                    return {
                        'price': swap_info['price'],
                        'confidence': 0.8,
                        'source': 'raydium_clmm_swap_logs'
                    }
            return None
            
        except Exception as e:
            print(f"❌ Error parsing Raydium CLMM swap: {e}")
            return None
    
    async def _update_realtime_price(self, price: float, source: str, metadata: Dict = None, signature: str = None):
        """Update and display real-time price with enhanced information"""
        try:
            if not price or price <= 0:
                return
                
            self.last_price = price
            self.last_price_time = time.time()
            self.price_updates_count += 1
            
            # Track price sources
            if 'blockchain' in source:
                self.price_sources['blockchain'] += 1
            elif 'api' in source:
                self.price_sources['api'] += 1
            
            # Smart price formatting for BONK (very small prices)
            if price >= 1:
                price_str = f"${price:.6f}"
            elif price >= 0.001:
                price_str = f"${price:.8f}"
            elif price >= 0.000001:
                price_str = f"${price:.10f}"
            else:
                price_str = f"${price:.12f}"
            
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
            
            # Determine source emoji
            source_emoji = "🔥" if 'blockchain' in source else "🔄"
            
            print(f"{source_emoji} [{timestamp}] LIVE UPDATE #{self.price_updates_count}")
            print(f"   💵 Price: {price_str}")
            print(f"   📊 Source: {source}")
            if signature:
                print(f"   🔗 Tx: {signature}...")
            
            # Additional metadata
            if metadata:
                confidence = metadata.get('confidence', 0.0)
                print(f"   🎯 Confidence: {confidence:.1f}")
                
                if metadata.get('amount_in') and metadata.get('amount_out'):
                    print(f"   💱 Swap: {metadata['amount_in']:.0f} → {metadata['amount_out']:.0f}")
                
                if metadata.get('swap_direction'):
                    print(f"   🔄 Direction: {metadata['swap_direction']}")
            
            print()
            
        except Exception as e:
            print(f"❌ Error updating real-time price: {e}")
    
    async def start_monitoring(self, mint: str, duration_seconds: int = 300):
        """Start comprehensive real-time monitoring with fallback hierarchy"""
        try:
            # Get token info
            token_info = await self.token_db.get_token_info(mint)
            if not token_info:
                print(f"❌ Token {mint} not found in database")
                return False
                
            self.current_mint = mint
            self.current_symbol = token_info.get('symbol', 'Unknown')
            self.current_pair = token_info.get('pair_address')
            self.current_dex = token_info.get('dex_id', 'raydium_v4')
            
            if not self.current_pair:
                print(f"❌ No pair address found for {self.current_symbol}")
                return False
            
            await self._print_monitoring_header(duration_seconds)
            
            # STEP 1: Try to establish blockchain monitoring (Helius first, then public RPC)
            blockchain_success = await self._establish_blockchain_monitoring()
            
            if not blockchain_success:
                print("⚠️ Blockchain monitoring failed, falling back to API only")
                self.api_fallback_active = True
            
            # Start monitoring loop
            await self._run_monitoring_loop(duration_seconds)
            
            # Print final results
            await self._print_final_results(duration_seconds)
            
        except Exception as e:
            print(f"❌ Error during monitoring: {e}")
            import traceback
            traceback.print_exc()
    
    async def _print_monitoring_header(self, duration_seconds: int):
        """Print comprehensive monitoring header"""
        print(f"🚀 COMPREHENSIVE REAL-TIME BLOCKCHAIN MONITORING")
        print(f"📊 Token: {self.current_symbol} ({self.current_mint[:8]}...)")
        print(f"🔗 Pair: {self.current_pair}")
        print(f"🏢 DEX: {self.current_dex}")
        print(f"⏱️ Duration: {duration_seconds}s")
        print(f"🔄 Fallback Hierarchy:")
        print(f"   1️⃣ PRIMARY: Helius WebSocket → Swap Transaction Parsing")
        print(f"   2️⃣ FALLBACK 1: Public RPC WebSocket → Swap Transaction Parsing")
        print(f"   3️⃣ FALLBACK 2: DexScreener API → Price Polling")
        print("="*70)
    
    async def _establish_blockchain_monitoring(self) -> bool:
        """Establish blockchain monitoring with WebSocket subscription"""
        try:
            print(f"🔌 Establishing blockchain WebSocket monitoring...")
            
            # Start streaming for the token - this will try Helius first, then public RPC
            await self.market_data.start_streaming(self.current_mint, self.current_pair, self.current_dex)
            
            # Wait a moment to see if connection is established
            await asyncio.sleep(3)
            
            # Check connection status
            if self.blockchain_listener and hasattr(self.blockchain_listener, 'ws_connections'):
                active_connections = sum(1 for ws in self.blockchain_listener.ws_connections.values() 
                                       if ws and self.blockchain_listener._is_connection_open(ws))
                
                if active_connections > 0:
                    print(f"✅ Blockchain monitoring established ({active_connections} connections)")
                    return True
                else:
                    print(f"❌ No active WebSocket connections established")
                    return False
            else:
                print(f"❌ BlockchainListener not available")
                return False
                
        except Exception as e:
            print(f"❌ Error establishing blockchain monitoring: {e}")
            return False
    
    async def _run_monitoring_loop(self, duration_seconds: int):
        """Main monitoring loop with status updates and fallback management"""
        start_time = time.time()
        last_status_time = start_time
        last_api_check_time = start_time
        
        while time.time() - start_time < duration_seconds:
            await asyncio.sleep(2)  # Check every 2 seconds
            
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Print status every 30 seconds
            if current_time - last_status_time >= 30:
                await self._print_status_update(elapsed)
                last_status_time = current_time
            
            # API fallback check every 60 seconds if no blockchain updates
            if current_time - last_api_check_time >= 60:
                if self.price_updates_count == 0 or self.api_fallback_active:
                    await self._check_api_fallback()
                last_api_check_time = current_time
    
    async def _print_status_update(self, elapsed_seconds: int):
        """Print detailed status update"""
        print(f"📈 STATUS UPDATE - {elapsed_seconds:.0f}s elapsed")
        print(f"   🔥 Price Updates: {self.price_updates_count} (Blockchain: {self.price_sources['blockchain']}, API: {self.price_sources['api']})")
        print(f"   📊 Transactions Seen: {self.transaction_count}")
        
        if self.last_price:
            time_since_update = time.time() - self.last_price_time
            print(f"   💵 Last Price: {self.current_symbol} = ${self.last_price:.10f} ({time_since_update:.0f}s ago)")
        
        # Connection status
        print(f"   🔌 Connections: Helius: {'✅' if self.helius_connected else '❌'}, Public RPC: {'✅' if self.public_rpc_connected else '❌'}")
        
        # WebSocket health
        if self.blockchain_listener and hasattr(self.blockchain_listener, 'ws_connections'):
            active_connections = sum(1 for ws in self.blockchain_listener.ws_connections.values() 
                                   if ws and self.blockchain_listener._is_connection_open(ws))
            print(f"   🌐 Active WebSocket Connections: {active_connections}")
        
        print()
    
    async def _check_api_fallback(self):
        """Check and activate API fallback if needed"""
        try:
            print(f"🔄 Checking DexScreener API fallback...")
            
            price_data = await self.market_data.get_token_price(self.current_mint, force_refresh=True)
            
            if price_data and price_data.get('priceUsd'):
                price = float(price_data['priceUsd'])
                
                if price > 0:
                    await self._update_realtime_price(
                        price=price,
                        source="api_fallback_dexscreener",
                        metadata={'confidence': 0.6, 'source': 'dexscreener_api'}
                    )
                    print(f"✅ API fallback successful: ${price:.10f}")
                else:
                    print(f"⚠️ API returned zero price")
            else:
                print(f"❌ API fallback failed - no price data")
                
        except Exception as e:
            print(f"❌ API fallback error: {e}")
    
    async def _print_final_results(self, duration_seconds: int):
        """Print comprehensive final results"""
        print(f"\n📊 FINAL MONITORING RESULTS ({duration_seconds}s)")
        print(f"{'='*50}")
        print(f"   🔥 Total Price Updates: {self.price_updates_count}")
        print(f"   📊 Blockchain Updates: {self.price_sources['blockchain']}")
        print(f"   🔄 API Fallback Updates: {self.price_sources['api']}")
        print(f"   📈 Transactions Monitored: {self.transaction_count}")
        
        if self.price_updates_count > 0:
            update_rate = self.price_updates_count / (duration_seconds / 60)
            print(f"   ⚡ Update Rate: {update_rate:.1f} updates/minute")
        
        if self.last_price:
            print(f"   💵 Final Price: {self.current_symbol} = ${self.last_price:.12f}")
        
        # System assessment
        print(f"\n🎯 SYSTEM ASSESSMENT:")
        
        if self.price_sources['blockchain'] > 0:
            print(f"   ✅ Real-time blockchain monitoring: WORKING")
            print(f"   🔥 Primary objective achieved - live price from blockchain transactions")
        elif self.price_sources['api'] > 0:
            print(f"   ⚠️ Blockchain monitoring: Limited/Failed")
            print(f"   🔄 API fallback: Working")
            print(f"   💡 Consider checking WebSocket connectivity or pair trading activity")
        else:
            print(f"   ❌ All monitoring methods: Failed")
            print(f"   🔧 Requires investigation of connectivity and token pair activity")
    
    async def close(self):
        """Clean up resources"""
        try:
            if self.market_data:
                await self.market_data.close()
            if self.token_db:
                await self.token_db.close()
            print("✅ Resources cleaned up")
        except Exception as e:
            print(f"❌ Cleanup error: {e}")

async def main():
    monitor = ComprehensiveRealTimeMonitor()
    
    try:
        # Initialize
        success = await monitor.initialize()
        if not success:
            return
        
        # Get BONK from database and start monitoring
        bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        
        print("🎯 Starting comprehensive real-time blockchain monitoring...")
        print("🔥 Focus: Live price calculation from swap transactions")
        print("⚡ Fallback: Helius → Public RPC → DexScreener API\n")
        
        # Start monitoring for 3 minutes to test
        await monitor.start_monitoring(bonk_mint, duration_seconds=180)
        
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