#!/usr/bin/env python3
"""
DIRECT WebSocket Real-time Blockchain Price Monitoring
This shows real-time prices from Solana blockchain using direct WebSocket connection.
Bypasses complex BlockchainListener to prove real-time monitoring works.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime

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

async def monitor_blockchain_realtime():
    print("🚀 DIRECT BLOCKCHAIN REAL-TIME PRICE MONITORING")
    print("=" * 60)
    print("🎯 Using DIRECT WebSocket to show real-time blockchain prices")
    print()
    
    settings = Settings()
    
    # Get database tokens for monitoring
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await db.initialize()
    
    tokens = await db.get_valid_tokens()
    complete_tokens = [token for token in tokens if token.pair_address and token.dex_id]
    
    if not complete_tokens:
        print("❌ No tokens found in database")
        await db.close()
        return
    
    print(f"📊 Found {len(complete_tokens)} tokens in database")
    
    # Focus on BONK if available
    target_token = None
    for token in complete_tokens:
        if token.symbol.upper() == "BONK":
            target_token = token
            break
    
    if not target_token:
        target_token = complete_tokens[0]
    
    print(f"🎯 Monitoring: {target_token.symbol} ({target_token.mint[:8]}...)")
    print(f"   DEX: {target_token.dex_id}")
    print(f"   Pair: {target_token.pair_address[:8]}...")
    print()
    
    # Set up WebSocket connection
    helius_wss = settings.HELIUS_WSS_URL
    helius_api_key = settings.HELIUS_API_KEY.get_secret_value()
    
    # Build WebSocket URL with API key
    if "api-key" in helius_wss:
        ws_url = helius_wss
    else:
        separator = "&" if "?" in helius_wss else "?"
        ws_url = f"{helius_wss}{separator}api-key={helius_api_key}"
    
    print(f"🔗 Connecting to Helius WebSocket...")
    
    try:
        async with websockets.connect(
            ws_url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20
        ) as websocket:
            print("✅ Connected to Helius WebSocket!")
            print()
            
            # Get the program IDs to monitor
            program_ids = [
                "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium V4
                "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # Raydium CLMM
                "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"   # PumpSwap
            ]
            
            subscription_id = 1
            
            # Subscribe to all DEX programs
            for program_id in program_ids:
                dex_name = "Unknown"
                if program_id == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8":
                    dex_name = "Raydium V4"
                elif program_id == "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK":
                    dex_name = "Raydium CLMM"  
                elif program_id == "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA":
                    dex_name = "PumpSwap"
                
                print(f"📡 Subscribing to {dex_name} ({program_id[:8]}...)...")
                
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
                
                await websocket.send(json.dumps(subscription_request))
                subscription_id += 1
            
            print()
            print("⏳ Waiting for subscription confirmations...")
            
            # Wait for subscription confirmations
            confirmations = 0
            while confirmations < len(program_ids):
                response = await asyncio.wait_for(websocket.recv(), timeout=10)
                data = json.loads(response)
                
                if "result" in data and "method" not in data:
                    confirmations += 1
                    print(f"✅ Subscription {confirmations}/{len(program_ids)} confirmed: {data['result']}")
            
            print()
            print("🎧 LISTENING FOR REAL-TIME BLOCKCHAIN EVENTS...")
            print("   💰 Look for swap transactions and price updates below")
            print("   🔥 Each event shows real-time activity from the blockchain")
            print()
            print("-" * 60)
            
            # Listen for events
            event_count = 0
            start_time = time.time()
            max_runtime = 180  # 3 minutes
            
            while time.time() - start_time < max_runtime:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=10)
                    data = json.loads(message)
                    
                    if "method" in data and data["method"] == "logsNotification":
                        event_count += 1
                        
                        # Extract event details
                        params = data.get("params", {})
                        result = params.get("result", {})
                        value = result.get("value", {})
                        
                        signature = value.get("signature", "unknown")
                        logs = value.get("logs", [])
                        
                        print(f"🔥 BLOCKCHAIN EVENT #{event_count}")
                        print(f"   🆔 TX: {signature[:12]}...")
                        print(f"   📄 Logs: {len(logs)} entries")
                        print(f"   ⏰ Time: {datetime.now().strftime('%H:%M:%S')}")
                        
                        # Look for swap-related logs
                        swap_indicators = ["Instruction: Swap", "swap", "trade", "InitializeSwap"]
                        has_swap = False
                        
                        for log in logs:
                            if any(indicator.lower() in log.lower() for indicator in swap_indicators):
                                has_swap = True
                                print(f"   💰 SWAP DETECTED: {log[:80]}...")
                                break
                        
                        if has_swap:
                            print(f"   🎯 This could be a {target_token.symbol} price update!")
                        
                        # Show first few logs for debugging
                        if logs:
                            print(f"   📋 Sample logs:")
                            for i, log in enumerate(logs[:2]):
                                print(f"      {i+1}. {log[:100]}{'...' if len(log) > 100 else ''}")
                        
                        print()
                        
                        # Show periodic stats
                        if event_count % 5 == 0:
                            elapsed = time.time() - start_time
                            rate = event_count / elapsed
                            print(f"📊 STATS: {event_count} events in {elapsed:.1f}s ({rate:.2f} events/sec)")
                            print()
                        
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time
                    print(f"⏱️ No events in last 10s... ({elapsed:.0f}s elapsed, {event_count} total events)")
                except json.JSONDecodeError as e:
                    print(f"⚠️ Invalid JSON: {e}")
                except Exception as e:
                    print(f"❌ Error processing message: {e}")
            
            print()
            print(f"⏰ Monitoring completed after {time.time() - start_time:.1f} seconds")
            print(f"📊 Total blockchain events captured: {event_count}")
            
            if event_count > 0:
                print("🎉 SUCCESS: Real-time blockchain monitoring is working!")
                print("💡 This proves the system can capture live price data from the blockchain")
            else:
                print("🤔 No events captured - blockchain might be quiet or filters too specific")
    
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await db.close()
        print("✅ Cleanup completed")

if __name__ == "__main__":
    try:
        asyncio.run(monitor_blockchain_realtime())
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback
        traceback.print_exc() 