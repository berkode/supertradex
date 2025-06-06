#!/usr/bin/env python3
"""
Test Helius API key and permissions.
This will verify if our API key works for both HTTP and WebSocket access.
"""

import asyncio
import json
import sys
import httpx
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

from config.settings import Settings

async def test_helius_api():
    print("🔍 HELIUS API KEY AND PERMISSIONS TEST")
    print("=" * 50)
    
    settings = Settings()
    
    helius_rpc = settings.HELIUS_RPC_URL
    helius_wss = settings.HELIUS_WSS_URL  
    helius_api_key = settings.HELIUS_API_KEY.get_secret_value()
    
    print(f"📡 Helius RPC URL: {helius_rpc}")
    print(f"🌐 Helius WSS URL: {helius_wss}")
    print(f"🔑 API Key: {helius_api_key[:10]}...{helius_api_key[-4:]}")
    print()
    
    # Test 1: HTTP RPC Request
    print("🧪 Test 1: HTTP RPC Request")
    print("-" * 30)
    
    try:
        # Construct RPC URL with API key
        if "api-key" in helius_rpc:
            rpc_url = helius_rpc
        else:
            separator = "&" if "?" in helius_rpc else "?"
            rpc_url = f"{helius_rpc}{separator}api-key={helius_api_key}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            # Simple getVersion request
            rpc_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getVersion"
            }
            
            response = await client.post(rpc_url, json=rpc_request)
            
            print(f"   Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ HTTP RPC Success: {data}")
            elif response.status_code == 401:
                print(f"   ❌ HTTP 401 Unauthorized - API key invalid")
                print(f"   Response: {response.text}")
            else:
                print(f"   ❌ HTTP Error: {response.status_code}")
                print(f"   Response: {response.text}")
                
    except Exception as e:
        print(f"   💥 HTTP Request Failed: {e}")
    
    print()
    
    # Test 2: Check API Key Format
    print("🧪 Test 2: API Key Format Validation")
    print("-" * 40)
    
    # Helius API keys are typically UUIDs
    if len(helius_api_key) == 36 and helius_api_key.count('-') == 4:
        print("   ✅ API key format looks correct (UUID format)")
    else:
        print(f"   ⚠️ API key format unusual (length: {len(helius_api_key)}, dashes: {helius_api_key.count('-')})")
    
    print()
    
    # Test 3: Check Helius Account Limits
    print("🧪 Test 3: Helius Account Plan Check")
    print("-" * 40)
    
    try:
        # Use a specific Helius endpoint to check account
        if "api-key" in helius_rpc:
            rpc_url = helius_rpc
        else:
            separator = "&" if "?" in helius_rpc else "?"
            rpc_url = f"{helius_rpc}{separator}api-key={helius_api_key}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            # Try getAccountInfo for SOL mint (should work on any plan)
            rpc_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    "So11111111111111111111111111111111111111112",
                    {"encoding": "base64"}
                ]
            }
            
            response = await client.post(rpc_url, json=rpc_request)
            
            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    print("   ✅ Basic RPC access working")
                else:
                    print(f"   ⚠️ Unexpected response: {data}")
            else:
                print(f"   ❌ Account info request failed: {response.status_code}")
                print(f"   Response: {response.text}")
                
    except Exception as e:
        print(f"   💥 Account check failed: {e}")
    
    print()
    
    # Test 4: Check WebSocket Permissions
    print("🧪 Test 4: WebSocket Permissions Check")
    print("-" * 40)
    
    try:
        # Check what WebSocket methods might be restricted
        if "api-key" in helius_wss:
            ws_url = helius_wss
        else:
            separator = "&" if "?" in helius_wss else "?"
            ws_url = f"{helius_wss}{separator}api-key={helius_api_key}"
        
        print(f"   WebSocket URL: {ws_url[:50]}...")
        
        # Test WebSocket connection with different subscription types
        import websockets
        
        try:
            async with websockets.connect(ws_url, open_timeout=10) as websocket:
                print("   ✅ WebSocket connection successful!")
                
                # Try accountSubscribe (should work on most plans)
                account_sub = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "accountSubscribe",
                    "params": [
                        "So11111111111111111111111111111111111111112",
                        {"encoding": "base64", "commitment": "processed"}
                    ]
                }
                
                await websocket.send(json.dumps(account_sub))
                response = await asyncio.wait_for(websocket.recv(), timeout=5)
                data = json.loads(response)
                
                if "result" in data:
                    print(f"   ✅ accountSubscribe works: {data['result']}")
                    
                    # Now try logsSubscribe
                    logs_sub = {
                        "jsonrpc": "2.0", 
                        "id": 2,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": ["675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"]},
                            {"commitment": "processed"}
                        ]
                    }
                    
                    await websocket.send(json.dumps(logs_sub))
                    response2 = await asyncio.wait_for(websocket.recv(), timeout=5)
                    data2 = json.loads(response2)
                    
                    if "result" in data2:
                        print(f"   ✅ logsSubscribe works: {data2['result']}")
                        print("   🎉 WebSocket permissions look good!")
                    elif "error" in data2:
                        print(f"   ❌ logsSubscribe failed: {data2['error']}")
                        print("   💡 Your plan might not support logsSubscribe")
                    
                elif "error" in data:
                    print(f"   ❌ accountSubscribe failed: {data['error']}")
                    
        except websockets.exceptions.InvalidStatusCode as e:
            if e.status_code == 401:
                print("   ❌ WebSocket 401 Unauthorized")
                print("   💡 API key lacks WebSocket permissions")
            else:
                print(f"   ❌ WebSocket error: {e}")
        except Exception as e:
            print(f"   💥 WebSocket test failed: {e}")
            
    except Exception as e:
        print(f"   💥 WebSocket preparation failed: {e}")
    
    print()
    print("📋 SUMMARY:")
    print("- If HTTP RPC works but WebSocket doesn't: upgrade your Helius plan")
    print("- If both fail with 401: check your API key")
    print("- If logsSubscribe fails: you might need a higher tier plan")
    print("- Free tier typically doesn't support WebSocket subscriptions")

if __name__ == "__main__":
    try:
        asyncio.run(test_helius_api())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted")
    except Exception as e:
        print(f"\n�� Test failed: {e}") 