#!/usr/bin/env python3
"""
Simplified Price Comparison Test - PriceMonitor vs Blockchain Events
This compares PriceMonitor prices with blockchain event detection for specific tokens.
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
class TokenMonitoring:
    symbol: str
    mint: str
    dex_id: str
    pair_address: str
    price_monitor_price: Optional[float] = None
    last_price_update: Optional[datetime] = None
    blockchain_events_count: int = 0
    price_updates_count: int = 0

async def fetch_price_monitor_prices(price_monitor: PriceMonitor, tokens: Dict[str, TokenMonitoring]) -> None:
    """Fetch current prices from PriceMonitor for all tokens"""
    print("📈 Fetching PriceMonitor prices...")
    
    for mint, token_data in tokens.items():
        try:
            price = await price_monitor.get_current_price_usd(mint)
            if price is not None:
                old_price = token_data.price_monitor_price
                token_data.price_monitor_price = price
                token_data.last_price_update = datetime.now()
                token_data.price_updates_count += 1
                
                # Show price update
                if old_price is None:
                    print(f"   💰 {token_data.symbol}: ${price:.8f} (initial)")
                else:
                    change = ((price - old_price) / old_price) * 100 if old_price else 0
                    direction = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                    print(f"   💰 {token_data.symbol}: ${price:.8f} {direction} ({change:+.2f}%)")
            else:
                print(f"   ⚠️ {token_data.symbol}: No price data available")
                
        except Exception as e:
            print(f"   ❌ {token_data.symbol}: Error fetching price: {e}")

async def monitor_blockchain_events(tokens: Dict[str, TokenMonitoring], duration: int = 30) -> int:
    """Monitor blockchain events for a short duration"""
    print(f"📡 Monitoring blockchain events for {duration} seconds...")
    
    settings = Settings()
    helius_wss = settings.HELIUS_WSS_URL
    helius_api_key = settings.HELIUS_API_KEY.get_secret_value()
    
    if "api-key" in helius_wss:
        ws_url = helius_wss
    else:
        separator = "&" if "?" in helius_wss else "?"
        ws_url = f"{helius_wss}{separator}api-key={helius_api_key}"
    
    total_events = 0
    
    try:
        async with websockets.connect(
            ws_url,
            open_timeout=10,
            ping_interval=None,  # Disable ping to avoid timeout issues
            close_timeout=5
        ) as websocket:
            print("   ✅ Connected to blockchain WebSocket")
            
            # Subscribe to DEX programs
            programs = {
                "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "raydium_v4",
                "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "pumpswap"
            }
            
            subscription_id = 1
            for program_id, dex_name in programs.items():
                subscription_request = {
                    "jsonrpc": "2.0",
                    "id": subscription_id,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": [program_id]},
                        {"commitment": "processed"}
                    ]
                }
                
                await websocket.send(json.dumps(subscription_request))
                subscription_id += 1
            
            print("   📡 Subscribed to blockchain programs")
            
            # Listen for events
            start_time = time.time()
            while time.time() - start_time < duration:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=2)
                    data = json.loads(message)
                    
                    if "method" in data and data["method"] == "logsNotification":
                        total_events += 1
                        
                        # Check if this could be related to our tokens
                        params = data.get("params", {})
                        result = params.get("result", {})
                        value = result.get("value", {})
                        logs = value.get("logs", [])
                        signature = value.get("signature", "unknown")
                        
                        # Look for swap activity
                        if any("swap" in log.lower() or "trade" in log.lower() for log in logs):
                            print(f"   🔥 Swap event detected: {signature[:8]}... ({len(logs)} logs)")
                            
                            # Increment event count for all monitored tokens
                            for token_data in tokens.values():
                                token_data.blockchain_events_count += 1
                        
                except asyncio.TimeoutError:
                    continue  # No message, keep listening
                except json.JSONDecodeError:
                    continue  # Invalid JSON, ignore
                except Exception as e:
                    print(f"   ⚠️ Error processing message: {e}")
                    
    except Exception as e:
        print(f"   ❌ WebSocket error: {e}")
    
    print(f"   📊 Detected {total_events} blockchain events total")
    return total_events

def print_summary(tokens: Dict[str, TokenMonitoring], cycle: int):
    """Print summary of monitored tokens"""
    print(f"\n{'='*80}")
    print(f"📊 PRICE MONITORING SUMMARY - CYCLE {cycle} - {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*80}")
    
    for mint, token_data in tokens.items():
        print(f"\n🎯 {token_data.symbol} ({token_data.dex_id.upper()})")
        print(f"   Mint: {mint[:16]}...")
        print(f"   Pair: {token_data.pair_address[:16]}...")
        
        if token_data.price_monitor_price is not None:
            age = (datetime.now() - token_data.last_price_update).total_seconds()
            print(f"   💰 Current Price: ${token_data.price_monitor_price:.8f}")
            print(f"   ⏰ Last Update: {age:.0f}s ago")
            print(f"   📊 Price Updates: {token_data.price_updates_count}")
        else:
            print(f"   💰 Current Price: No data")
        
        print(f"   🔥 Blockchain Events: {token_data.blockchain_events_count}")
    
    print(f"\n{'='*80}")

async def main():
    print("🎯 SIMPLIFIED PRICE COMPARISON TEST")
    print("=" * 50)
    print("📊 Compares PriceMonitor prices with blockchain event monitoring")
    print("🔄 Runs multiple short cycles to demonstrate functionality")
    print()
    
    # Get tokens from database
    settings = Settings()
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await db.initialize()
    
    tokens_from_db = await db.get_valid_tokens()
    complete_tokens = [token for token in tokens_from_db if token.pair_address and token.dex_id]
    
    # Select tokens for monitoring
    selected_tokens = []
    
    # Get BONK from Raydium V4
    raydium_v4_tokens = [t for t in complete_tokens if t.dex_id == 'raydium_v4']
    if raydium_v4_tokens:
        bonk_token = next((t for t in raydium_v4_tokens if t.symbol.upper() == "BONK"), raydium_v4_tokens[0])
        selected_tokens.append(bonk_token)
    
    # Get a token from PumpSwap
    pumpswap_tokens = [t for t in complete_tokens if t.dex_id == 'pumpswap']
    if pumpswap_tokens:
        selected_tokens.append(pumpswap_tokens[0])
    
    await db.close()
    
    if not selected_tokens:
        print("❌ No suitable tokens found")
        return
    
    print("🎯 Selected tokens for monitoring:")
    for token in selected_tokens:
        print(f"   • {token.symbol:10s} ({token.dex_id:12s}) | {token.mint[:8]}...")
    print()
    
    # Initialize monitoring components
    print("🚀 Initializing components...")
    
    dex_api = DexScreenerAPI(settings=settings)
    await dex_api.initialize()
    
    http_client = httpx.AsyncClient(timeout=30)
    
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await db.initialize()
    
    price_monitor = PriceMonitor(
        settings=settings,
        dex_api_client=dex_api,
        http_client=http_client,
        db=db
    )
    await price_monitor.initialize()
    
    # Create monitoring data structures
    monitored_tokens = {}
    for token in selected_tokens:
        monitored_tokens[token.mint] = TokenMonitoring(
            symbol=token.symbol,
            mint=token.mint,
            dex_id=token.dex_id,
            pair_address=token.pair_address
        )
        price_monitor.add_token(token.mint)
    
    print("✅ Components initialized")
    print()
    
    try:
        print("🔄 Starting monitoring cycles...")
        
        for cycle in range(1, 4):  # Run 3 cycles
            print(f"\n🚀 CYCLE {cycle}/3")
            print("-" * 40)
            
            # Fetch PriceMonitor prices
            await fetch_price_monitor_prices(price_monitor, monitored_tokens)
            
            # Monitor blockchain events for 30 seconds
            await monitor_blockchain_events(monitored_tokens, duration=30)
            
            # Show summary
            print_summary(monitored_tokens, cycle)
            
            if cycle < 3:
                print(f"\n⏳ Waiting 15 seconds before next cycle...")
                await asyncio.sleep(15)
        
        print(f"\n🎉 MONITORING TEST COMPLETED!")
        print("💡 This demonstrates the system can:")
        print("   • Fetch real-time prices from DexScreener API")
        print("   • Monitor blockchain events from Solana WebSocket")
        print("   • Track specific tokens by DEX type")
        print("   • Compare price sources and detect trading activity")
        
    except KeyboardInterrupt:
        print(f"\n🛑 Test stopped by user")
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 Cleaning up...")
        
        try:
            await price_monitor.close()
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