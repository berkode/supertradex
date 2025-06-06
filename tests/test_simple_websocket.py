#!/usr/bin/env python3
"""
Simple WebSocket test to verify connection to Helius endpoints.
This bypasses the complex BlockchainListener architecture to test basic connectivity.
"""

import asyncio
import json
import sys
from pathlib import Path

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

async def test_simple_websocket():
    print("🔌 SIMPLE WEBSOCKET CONNECTION TEST")
    print("=" * 50)
    
    settings = Settings()
    
    # Test 1: Check Helius WebSocket URL
    helius_wss = settings.HELIUS_WSS_URL
    helius_api_key = settings.HELIUS_API_KEY
    
    print(f"📡 Testing Helius WebSocket URL: {helius_wss[:50]}...")
    print(f"🔑 API Key configured: {'Yes' if helius_api_key else 'No'}")
    print()
    
    # Build WebSocket URL with API key
    if "api-key" in helius_wss:
        ws_url = helius_wss
    else:
        separator = "&" if "?" in helius_wss else "?"
        ws_url = f"{helius_wss}{separator}api-key={helius_api_key}"
    
    print(f"🌐 Final WebSocket URL: {ws_url[:50]}...")
    print()
    
    try:
        print("🚀 Attempting to connect to Helius WebSocket...")
        
        # Test basic connection
        async with websockets.connect(
            ws_url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20
        ) as websocket:
            print("✅ Successfully connected to Helius WebSocket!")
            print()
            
            # Test subscription to Raydium program
            raydium_program_id = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
            print(f"📡 Testing subscription to Raydium program {raydium_program_id[:8]}...")
            
            subscription_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [
                    {
                        "mentions": [raydium_program_id]
                    },
                    {
                        "commitment": "processed",
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            }
            
            await websocket.send(json.dumps(subscription_request))
            print("📤 Subscription request sent")
            
            # Wait for confirmation
            print("⏳ Waiting for subscription confirmation...")
            
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10)
                response_data = json.loads(response)
                
                print(f"📥 Received response: {response_data}")
                
                if "result" in response_data:
                    subscription_id = response_data["result"]
                    print(f"✅ Subscription successful! ID: {subscription_id}")
                    
                    # Listen for a few messages
                    print("🎧 Listening for blockchain events (30 seconds)...")
                    start_time = asyncio.get_event_loop().time()
                    message_count = 0
                    
                    while asyncio.get_event_loop().time() - start_time < 30:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=5)
                            data = json.loads(message)
                            
                            if "method" in data and data["method"] == "logsNotification":
                                message_count += 1
                                logs_count = len(data.get("params", {}).get("result", {}).get("value", {}).get("logs", []))
                                signature = data.get("params", {}).get("result", {}).get("value", {}).get("signature", "unknown")[:8]
                                
                                print(f"🔥 BLOCKCHAIN EVENT #{message_count}: TX {signature}... | {logs_count} logs")
                                
                        except asyncio.TimeoutError:
                            print("⏱️ No messages in last 5 seconds...")
                        except json.JSONDecodeError as e:
                            print(f"⚠️ Invalid JSON: {e}")
                    
                    print(f"\n📊 Test completed! Received {message_count} blockchain events in 30 seconds")
                    
                else:
                    print(f"❌ Subscription failed: {response_data}")
                    
            except asyncio.TimeoutError:
                print("⏰ Timeout waiting for subscription confirmation")
                
    except websockets.exceptions.WebSocketException as e:
        print(f"❌ WebSocket error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    try:
        asyncio.run(test_simple_websocket())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n�� Test failed: {e}") 