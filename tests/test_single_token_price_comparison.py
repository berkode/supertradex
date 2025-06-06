#!/usr/bin/env python3
"""
Single Token Price Comparison: Blockchain vs API
This test monitors ONE specific token and compares:
- Real-time price from blockchain WebSocket logs 
- API price from PriceMonitor
Every 60 seconds, showing the comparison.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime
import re

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
from config.settings import Settings
from data.token_database import TokenDatabase
from data.price_monitor import PriceMonitor
from data.dex_screener_api import DexScreenerAPI
import httpx

class SingleTokenPriceMonitor:
    def __init__(self, token, settings):
        self.token = token
        self.settings = settings
        self.blockchain_price = None
        self.api_price = None
        self.last_blockchain_update = None
        self.last_api_update = None
        self.blockchain_events_count = 0
        self.price_extractions_count = 0
        
    def extract_price_from_logs(self, logs, signature):
        """Extract price information from transaction logs."""
        try:
            # Look for swap-related logs that might contain price info
            for log in logs:
                # Pattern for Raydium swap logs
                if "Instruction: Swap" in log:
                    # Try to extract amounts from log
                    # Example: "Instruction: Swap base_in: 1000000000, quote_out: 50000000"
                    amounts = re.findall(r'(\d+)', log)
                    if len(amounts) >= 2:
                        base_amount = int(amounts[0])
                        quote_amount = int(amounts[1])
                        
                        # Simple price calculation (this is DEX-specific)
                        if base_amount > 0:
                            price = quote_amount / base_amount
                            return price
                
                # Pattern for PumpSwap logs
                elif "swap" in log.lower() and "amount" in log.lower():
                    amounts = re.findall(r'amount[:\s]*(\d+)', log.lower())
                    if len(amounts) >= 2:
                        try:
                            amount1 = int(amounts[0])
                            amount2 = int(amounts[1])
                            if amount1 > 0:
                                price = amount2 / amount1
                                return price
                        except:
                            continue
                
                # Look for price mentions in logs
                elif "price" in log.lower():
                    price_matches = re.findall(r'price[:\s]*(\d*\.?\d+)', log.lower())
                    if price_matches:
                        try:
                            return float(price_matches[0])
                        except:
                            continue
        
        except Exception as e:
            print(f"      ⚠️ Error extracting price: {e}")
        
        return None
    
    def update_blockchain_price(self, price):
        """Update blockchain price and timestamp."""
        if price and price > 0:
            self.blockchain_price = price
            self.last_blockchain_update = datetime.now()
            self.price_extractions_count += 1
            return True
        return False
    
    async def update_api_price(self, price_monitor):
        """Update API price from PriceMonitor."""
        try:
            price = await price_monitor.get_current_price_usd(self.token.mint)
            if price and price > 0:
                self.api_price = price
                self.last_api_update = datetime.now()
                return True
        except Exception as e:
            print(f"      ⚠️ Error getting API price: {e}")
        return False
    
    def get_status_summary(self):
        """Get current status summary."""
        blockchain_status = f"${self.blockchain_price:.8f}" if self.blockchain_price else "No data"
        api_status = f"${self.api_price:.8f}" if self.api_price else "No data"
        
        # Calculate difference if both prices available
        difference = ""
        if self.blockchain_price and self.api_price:
            diff_pct = ((self.blockchain_price - self.api_price) / self.api_price) * 100
            difference = f" ({diff_pct:+.2f}%)"
        
        return {
            "blockchain": blockchain_status,
            "api": api_status, 
            "difference": difference,
            "events_count": self.blockchain_events_count,
            "extractions_count": self.price_extractions_count
        }

async def monitor_single_token_prices():
    print("🎯 SINGLE TOKEN PRICE COMPARISON: BLOCKCHAIN vs API")
    print("=" * 70)
    print("📊 This test monitors ONE token and compares prices every 60 seconds")
    print()
    
    settings = Settings()
    
    # Get target token from database
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await db.initialize()
    
    tokens = await db.get_valid_tokens()
    complete_tokens = [token for token in tokens if token.pair_address and token.dex_id]
    
    if not complete_tokens:
        print("❌ No tokens found in database")
        await db.close()
        return
    
    # Select BONK if available, otherwise first available
    target_token = None
    for token in complete_tokens:
        if token.symbol.upper() == "BONK":
            target_token = token
            break
    
    if not target_token:
        target_token = complete_tokens[0]
    
    print(f"🎯 TARGET TOKEN: {target_token.symbol}")
    print(f"   🆔 Mint: {target_token.mint}")
    print(f"   🏪 DEX: {target_token.dex_id}")
    print(f"   📈 Pair: {target_token.pair_address}")
    print()
    
    # Initialize price monitor
    print("🚀 Initializing PriceMonitor for API prices...")
    
    dex_api = DexScreenerAPI(settings=settings)
    await dex_api.initialize()
    
    http_client = httpx.AsyncClient(timeout=30)
    
    price_monitor = PriceMonitor(
        settings=settings,
        dex_api_client=dex_api,
        http_client=http_client,
        db=db
    )
    
    await price_monitor.initialize()
    price_monitor.add_token(target_token.mint)
    
    print("✅ PriceMonitor initialized")
    
    # Initialize price tracker
    tracker = SingleTokenPriceMonitor(target_token, settings)
    
    # Get initial API price
    print("📡 Getting initial API price...")
    await tracker.update_api_price(price_monitor)
    
    print(f"✅ Initial API price: ${tracker.api_price:.8f}" if tracker.api_price else "❌ No initial API price")
    print()
    
    # Set up WebSocket connection for blockchain monitoring
    helius_wss = settings.HELIUS_WSS_URL
    helius_api_key = settings.HELIUS_API_KEY.get_secret_value()
    
    if "api-key" in helius_wss:
        ws_url = helius_wss
    else:
        separator = "&" if "?" in helius_wss else "?"
        ws_url = f"{helius_wss}{separator}api-key={helius_api_key}"
    
    print(f"🔗 Connecting to blockchain for {target_token.symbol} monitoring...")
    
    try:
        async with websockets.connect(
            ws_url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20
        ) as websocket:
            print("✅ Connected to Helius WebSocket!")
            
            # Get program ID for the token's DEX
            program_id = settings.DEX_PROGRAM_IDS.get(target_token.dex_id)
            if not program_id:
                print(f"❌ No program ID found for DEX: {target_token.dex_id}")
                return
            
            print(f"📡 Subscribing to {target_token.dex_id} program ({program_id[:8]}...)...")
            
            # Subscribe to the specific DEX program
            subscription_request = {
                "jsonrpc": "2.0",
                "id": 1,
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
            
            await websocket.send(json.dumps(subscription_request))
            
            # Wait for subscription confirmation
            print("⏳ Waiting for subscription confirmation...")
            response = await asyncio.wait_for(websocket.recv(), timeout=10)
            data = json.loads(response)
            
            if "result" in data:
                print(f"✅ Subscription confirmed: {data['result']}")
            else:
                print(f"❌ Subscription failed: {data}")
                return
            
            print()
            print("🎧 MONITORING STARTED")
            print(f"   🎯 Token: {target_token.symbol}")
            print(f"   ⏱️ Price comparison every 60 seconds")
            print(f"   🔥 Blockchain events will be processed for price extraction")
            print()
            print("-" * 70)
            
            # Start monitoring loop
            start_time = time.time()
            last_summary_time = start_time
            max_runtime = 600  # 10 minutes
            
            while time.time() - start_time < max_runtime:
                try:
                    # Listen for blockchain events
                    message = await asyncio.wait_for(websocket.recv(), timeout=5)
                    data = json.loads(message)
                    
                    if "method" in data and data["method"] == "logsNotification":
                        tracker.blockchain_events_count += 1
                        
                        # Extract event details
                        params = data.get("params", {})
                        result = params.get("result", {})
                        value = result.get("value", {})
                        
                        signature = value.get("signature", "unknown")
                        logs = value.get("logs", [])
                        
                        print(f"🔥 Blockchain Event #{tracker.blockchain_events_count} - TX: {signature[:12]}...")
                        
                        # Try to extract price from logs
                        extracted_price = tracker.extract_price_from_logs(logs, signature)
                        
                        if extracted_price:
                            if tracker.update_blockchain_price(extracted_price):
                                print(f"   💰 PRICE EXTRACTED: ${extracted_price:.8f}")
                            else:
                                print(f"   ⚠️ Invalid price extracted: {extracted_price}")
                        else:
                            print(f"   📄 No price data in this transaction")
                
                except asyncio.TimeoutError:
                    # No messages - this is normal
                    pass
                except json.JSONDecodeError:
                    print("   ⚠️ Invalid JSON received")
                except Exception as e:
                    print(f"   ❌ Error processing message: {e}")
                
                # Show 60-second summary
                current_time = time.time()
                if current_time - last_summary_time >= 60:  # Every 60 seconds
                    print("\n" + "=" * 70)
                    print(f"📊 60-SECOND PRICE COMPARISON - {datetime.now().strftime('%H:%M:%S')}")
                    print("=" * 70)
                    
                    # Update API price
                    await tracker.update_api_price(price_monitor)
                    
                    # Get status summary
                    status = tracker.get_status_summary()
                    
                    print(f"🎯 Token: {target_token.symbol} ({target_token.mint[:8]}...)")
                    print(f"📡 Blockchain Price: {status['blockchain']}")
                    print(f"🌐 API Price:        {status['api']}")
                    print(f"📊 Difference:       {status['difference']}")
                    print(f"🔥 Blockchain Events: {status['events_count']}")
                    print(f"💰 Price Extractions: {status['extractions_count']}")
                    
                    if tracker.last_blockchain_update:
                        print(f"⏰ Last Blockchain Update: {tracker.last_blockchain_update.strftime('%H:%M:%S')}")
                    if tracker.last_api_update:
                        print(f"⏰ Last API Update: {tracker.last_api_update.strftime('%H:%M:%S')}")
                    
                    print("=" * 70)
                    print()
                    
                    last_summary_time = current_time
            
            print(f"\n⏰ Monitoring completed after {time.time() - start_time:.1f} seconds")
            
            # Final summary
            final_status = tracker.get_status_summary()
            print("\n📋 FINAL SUMMARY:")
            print(f"   Total blockchain events: {final_status['events_count']}")
            print(f"   Successful price extractions: {final_status['extractions_count']}")
            print(f"   Final blockchain price: {final_status['blockchain']}")
            print(f"   Final API price: {final_status['api']}")
            
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n🧹 Cleaning up...")
        
        # Cleanup
        await price_monitor.close()
        await http_client.aclose()
        await dex_api.close()
        await db.close()
        
        print("✅ Cleanup completed")

if __name__ == "__main__":
    try:
        asyncio.run(monitor_single_token_prices())
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback
        traceback.print_exc() 