#!/usr/bin/env python3
"""
Focused Price Monitoring Test - Blockchain vs PriceMonitor Comparison
This tracks specific tokens and compares real-time blockchain prices with PriceMonitor prices every 60 seconds.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup environment
from utils.encryption import decrypt_env_file, get_encryption_password
from dotenv import dotenv_values
import io
import os

env_dir = project_root / "config"
env_encrypted_path = env_dir / ".env.encrypted"
if env_encrypted_path.exists():
    password = get_encryption_password()
    if password:
        decrypted_content = decrypt_env_file(env_encrypted_path, password)
        if decrypted_content:
            env_vars = dotenv_values(stream=io.StringIO(decrypted_content))
            for key, value in env_vars.items():
                if key not in os.environ:
                    os.environ[key] = value

import websockets
import httpx
from config.settings import Settings
from data.token_database import TokenDatabase
from data.price_monitor import PriceMonitor
from config.dexscreener_api import DexScreenerAPI

@dataclass
class TokenPriceData:
    symbol: str
    mint: str
    dex_id: str
    pair_address: str
    blockchain_price: Optional[float] = None
    price_monitor_price: Optional[float] = None
    last_blockchain_update: Optional[datetime] = None
    last_price_monitor_update: Optional[datetime] = None
    blockchain_update_count: int = 0
    price_monitor_update_count: int = 0

class FocusedPriceMonitor:
    def __init__(self):
        self.settings = Settings()
        self.monitored_tokens: Dict[str, TokenPriceData] = {}
        self.price_monitor = None
        self.websocket = None
        
        # DEX program IDs for filtering
        self.dex_programs = {
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "raydium_v4",
            "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "raydium_clmm",  
            "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "pumpswap"
        }
        
    async def initialize(self):
        """Initialize PriceMonitor and WebSocket connection"""
        print("🚀 Initializing focused price monitoring system...")
        
        # Initialize DexScreener API
        dex_api = DexScreenerAPI(settings=self.settings)
        await dex_api.initialize()
        
        # Create HTTP client
        http_client = httpx.AsyncClient(timeout=30)
        
        # Initialize database
        db = TokenDatabase(self.settings.DATABASE_FILE_PATH, self.settings)
        await db.initialize()
        
        # Initialize PriceMonitor
        self.price_monitor = PriceMonitor(
            settings=self.settings,
            dex_api_client=dex_api,
            http_client=http_client,
            db=db
        )
        await self.price_monitor.initialize()
        
        print("✅ PriceMonitor initialized")
        
        # Setup WebSocket connection
        await self._setup_websocket()
        
        return db, dex_api, http_client
        
    async def _setup_websocket(self):
        """Setup WebSocket connection to Helius"""
        helius_wss = self.settings.HELIUS_WSS_URL
        helius_api_key = self.settings.HELIUS_API_KEY.get_secret_value()
        
        if "api-key" in helius_wss:
            ws_url = helius_wss
        else:
            separator = "&" if "?" in helius_wss else "?"
            ws_url = f"{helius_wss}{separator}api-key={helius_api_key}"
        
        print(f"🔗 Connecting to WebSocket...")
        
        self.websocket = await websockets.connect(
            ws_url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20
        )
        
        print("✅ WebSocket connected")
        
        # Subscribe to all DEX programs
        subscription_id = 1
        for program_id, dex_name in self.dex_programs.items():
            subscription_request = {
                "jsonrpc": "2.0",
                "id": subscription_id,
                "method": "logsSubscribe",
                "params": [
                    {
                        "mentions": [program_id]
                    },
                    {
                        "commitment": "processed",
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            }
            
            await self.websocket.send(json.dumps(subscription_request))
            print(f"📡 Subscribed to {dex_name} ({program_id[:8]}...)")
            subscription_id += 1
    
    def add_token(self, symbol: str, mint: str, dex_id: str, pair_address: str):
        """Add a token to focused monitoring"""
        self.monitored_tokens[mint] = TokenPriceData(
            symbol=symbol,
            mint=mint,
            dex_id=dex_id,
            pair_address=pair_address
        )
        
        # Add to PriceMonitor
        self.price_monitor.add_token(mint)
        
        print(f"🎯 Added {symbol} ({mint[:8]}...) to focused monitoring")
    
    async def update_price_monitor_prices(self):
        """Update prices from PriceMonitor for all monitored tokens"""
        for mint, token_data in self.monitored_tokens.items():
            try:
                price = await self.price_monitor.get_current_price_usd(mint)
                if price is not None:
                    token_data.price_monitor_price = price
                    token_data.last_price_monitor_update = datetime.now()
                    token_data.price_monitor_update_count += 1
            except Exception as e:
                print(f"⚠️ Error getting PriceMonitor price for {token_data.symbol}: {e}")
    
    async def process_blockchain_message(self, data: Dict):
        """Process WebSocket message and extract price updates for monitored tokens"""
        try:
            if "method" in data and data["method"] == "logsNotification":
                params = data.get("params", {})
                result = params.get("result", {})
                value = result.get("value", {})
                
                signature = value.get("signature", "unknown")
                logs = value.get("logs", [])
                
                # Look for swap activity in logs
                if self._contains_swap_activity(logs):
                    # Try to extract token and price information
                    price_info = await self._extract_price_from_logs(logs, signature)
                    
                    if price_info:
                        mint = price_info.get("token_mint")
                        price = price_info.get("price_usd")
                        dex_id = price_info.get("dex_id")
                        
                        # Check if this is a monitored token
                        if mint in self.monitored_tokens:
                            token_data = self.monitored_tokens[mint]
                            token_data.blockchain_price = price
                            token_data.last_blockchain_update = datetime.now()
                            token_data.blockchain_update_count += 1
                            
                            print(f"💰 BLOCKCHAIN PRICE: {token_data.symbol} = ${price:.8f} (from {dex_id})")
                            
        except Exception as e:
            print(f"❌ Error processing blockchain message: {e}")
    
    def _contains_swap_activity(self, logs: List[str]) -> bool:
        """Check if logs contain swap activity"""
        swap_keywords = ["Instruction: Swap", "swap", "trade", "InitializeSwap"]
        log_text = " ".join(logs).lower()
        return any(keyword.lower() in log_text for keyword in swap_keywords)
    
    async def _extract_price_from_logs(self, logs: List[str], signature: str) -> Optional[Dict]:
        """Extract price information from transaction logs using actual DEX parsers"""
        try:
            # Initialize parsers if not already done
            if not hasattr(self, 'parsers'):
                from data import RaydiumV4Parser, PumpSwapParser, RaydiumClmmParser
                from config.blockchain_logging import setup_blockchain_logger
                
                blockchain_logger = setup_blockchain_logger("PriceExtractor")
                
                self.parsers = {
                    'raydium_v4': RaydiumV4Parser(self.settings, blockchain_logger),
                    'pumpswap': PumpSwapParser(self.settings, blockchain_logger),
                    'raydium_clmm': RaydiumClmmParser(self.settings, blockchain_logger)
                }
            
            # Try each parser to see if it can extract price info
            for dex_id, parser in self.parsers.items():
                try:
                    swap_data = await parser.parse_swap_logs(logs, signature)
                    
                    if swap_data:
                        token_mint = swap_data.get("token_mint")
                        price_usd = swap_data.get("price_usd")
                        
                        if token_mint and price_usd:
                            return {
                                "token_mint": token_mint,
                                "price_usd": price_usd,
                                "dex_id": dex_id,
                                "signature": signature,
                                "swap_data": swap_data
                            }
                            
                except Exception as e:
                    # Parser couldn't handle this transaction, try next one
                    continue
            
            return None
            
        except Exception as e:
            print(f"❌ Error extracting price from logs: {e}")
            return None
    
    def print_price_comparison(self):
        """Print 60-second price comparison summary"""
        print("\n" + "=" * 80)
        print(f"📊 PRICE COMPARISON SUMMARY - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 80)
        
        for mint, token_data in self.monitored_tokens.items():
            print(f"\n🔥 {token_data.symbol} ({token_data.dex_id.upper()})")
            print(f"   Mint: {mint[:12]}...")
            print(f"   Pair: {token_data.pair_address[:12]}...")
            
            # Blockchain price info
            if token_data.blockchain_price is not None:
                blockchain_age = (datetime.now() - token_data.last_blockchain_update).total_seconds()
                print(f"   💰 Blockchain Price: ${token_data.blockchain_price:.8f} ({blockchain_age:.0f}s ago)")
                print(f"   📊 Blockchain Updates: {token_data.blockchain_update_count}")
            else:
                print(f"   💰 Blockchain Price: No data yet")
            
            # PriceMonitor price info
            if token_data.price_monitor_price is not None:
                pm_age = (datetime.now() - token_data.last_price_monitor_update).total_seconds()
                print(f"   📈 PriceMonitor Price: ${token_data.price_monitor_price:.8f} ({pm_age:.0f}s ago)")
                print(f"   📊 PriceMonitor Updates: {token_data.price_monitor_update_count}")
            else:
                print(f"   📈 PriceMonitor Price: No data yet")
            
            # Price difference
            if token_data.blockchain_price and token_data.price_monitor_price:
                diff_pct = ((token_data.blockchain_price - token_data.price_monitor_price) / token_data.price_monitor_price) * 100
                diff_indicator = "📈" if diff_pct > 0 else "📉" if diff_pct < 0 else "➡️"
                print(f"   🔄 Difference: {diff_pct:+.2f}% {diff_indicator}")
            else:
                print(f"   🔄 Difference: Waiting for data...")
        
        print("\n" + "=" * 80)

async def main():
    print("🎯 FOCUSED PRICE MONITORING - BLOCKCHAIN vs PRICEMONITOR")
    print("=" * 70)
    print("📊 Compares real-time blockchain prices with PriceMonitor prices every 60s")
    print()
    
    # Get tokens from database
    settings = Settings()
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await db.initialize()
    
    tokens = await db.get_valid_tokens()
    complete_tokens = [token for token in tokens if token.pair_address and token.dex_id]
    
    # Select tokens by DEX type
    selected_tokens = []
    
    # Get one Raydium V4 token (BONK if available)
    raydium_v4_tokens = [t for t in complete_tokens if t.dex_id == 'raydium_v4']
    if raydium_v4_tokens:
        bonk_token = next((t for t in raydium_v4_tokens if t.symbol.upper() == "BONK"), raydium_v4_tokens[0])
        selected_tokens.append(bonk_token)
    
    # Get one PumpSwap token
    pumpswap_tokens = [t for t in complete_tokens if t.dex_id == 'pumpswap']
    if pumpswap_tokens:
        selected_tokens.append(pumpswap_tokens[0])  # Take first available
    
    await db.close()
    
    if not selected_tokens:
        print("❌ No suitable tokens found for monitoring")
        return
    
    print("🎯 Selected tokens for focused monitoring:")
    for token in selected_tokens:
        print(f"   • {token.symbol:10s} ({token.dex_id:12s}) | {token.mint[:8]}...")
    print()
    
    # Initialize focused price monitor
    monitor = FocusedPriceMonitor()
    db, dex_api, http_client = await monitor.initialize()
    
    # Add selected tokens to monitoring
    for token in selected_tokens:
        monitor.add_token(token.symbol, token.mint, token.dex_id, token.pair_address)
    
    print()
    print("🎧 Starting focused price monitoring...")
    print("   📡 Listening for blockchain price updates")
    print("   📈 Fetching PriceMonitor prices every 60 seconds")
    print("   📊 Comparison summary every 60 seconds")
    print()
    print("Press Ctrl+C to stop...")
    print("-" * 70)
    
    try:
        start_time = time.time()
        last_summary_time = start_time
        last_price_monitor_update = start_time
        
        while True:
            current_time = time.time()
            
            # Process WebSocket messages (non-blocking)
            try:
                message = await asyncio.wait_for(monitor.websocket.recv(), timeout=1)
                data = json.loads(message)
                await monitor.process_blockchain_message(data)
            except asyncio.TimeoutError:
                pass  # No message received, continue
            except json.JSONDecodeError:
                pass  # Invalid JSON, ignore
            
            # Update PriceMonitor prices every 30 seconds
            if current_time - last_price_monitor_update >= 30:
                await monitor.update_price_monitor_prices()
                last_price_monitor_update = current_time
            
            # Print summary every 60 seconds
            if current_time - last_summary_time >= 60:
                monitor.print_price_comparison()
                last_summary_time = current_time
            
            await asyncio.sleep(0.1)  # Small delay to prevent busy waiting
    
    except KeyboardInterrupt:
        print(f"\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Error during monitoring: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 Cleaning up...")
        
        try:
            if monitor.websocket:
                await monitor.websocket.close()
                print("✅ WebSocket closed")
        except:
            pass
        
        try:
            if monitor.price_monitor:
                await monitor.price_monitor.close()
                print("✅ PriceMonitor closed")
        except:
            pass
        
        try:
            await http_client.aclose()
            print("✅ HTTP client closed")
        except:
            pass
        
        try:
            await dex_api.close()
            print("✅ DexScreener API closed")
        except:
            pass
        
        try:
            await db.close()
            print("✅ Database closed")
        except:
            pass
        
        print("✅ Cleanup complete!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback
        traceback.print_exc() 