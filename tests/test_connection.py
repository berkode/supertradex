#!/usr/bin/env python3
import websockets
import asyncio
from test_token_monitoring import load_environment

async def test_connection():
    load_environment()
    from config.settings import Settings
    settings = Settings()
    
    try:
        print('Testing WebSocket connection...')
        print(f'URL: {settings.SOLANA_WSS_URL[:50]}...')
        
        async with websockets.connect(settings.SOLANA_WSS_URL) as ws:
            print('✅ WebSocket connection successful!')
            await ws.send('{"jsonrpc":"2.0","id":1,"method":"getSlot"}')
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            print('✅ Received response:', response[:100])
            return True
    except Exception as e:
        print(f'❌ Connection failed: {e}')
        return False

if __name__ == "__main__":
    result = asyncio.run(test_connection())
    print(f"Connection test result: {result}") 