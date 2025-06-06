#!/usr/bin/env python3
"""
Debug price extraction issue for BONK token
"""

import asyncio
import sys
import os
import json
from pathlib import Path
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

async def debug_price_issue():
    print("🔍 DEBUGGING BONK PRICE ISSUE\n")
    
    # BONK token details
    bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    
    # Test 1: Direct DexScreener API call
    print("📡 Testing direct DexScreener API call...")
    try:
        from config.dexscreener_api import DexScreenerAPI
        
        dex_api = DexScreenerAPI()
        print(f"DexScreener API Base URL: {dex_api.base_url}")
        
        # Test the token endpoint directly
        url = f"https://api.dexscreener.com/latest/dex/tokens/{bonk_mint}"
        print(f"Testing URL: {url}")
        
        response = await dex_api.get_token_data(bonk_mint)
        print(f"\n📊 Raw API Response:")
        print(json.dumps(response, indent=2)[:1000] + "..." if len(str(response)) > 1000 else json.dumps(response, indent=2))
        
        # Check if there are pairs and extract price from first pair
        if response and 'pairs' in response:
            pairs = response['pairs']
            print(f"\n🔗 Found {len(pairs)} pairs")
            for i, pair in enumerate(pairs[:3]):  # Show first 3 pairs
                price_usd = pair.get('priceUsd', 'N/A')
                pair_address = pair.get('pairAddress', 'N/A')
                dex_id = pair.get('dexId', 'N/A')
                liquidity_usd = pair.get('liquidity', {}).get('usd', 'N/A')
                print(f"  Pair {i+1}: Price=${price_usd}, DEX={dex_id}, Liquidity=${liquidity_usd}")
                print(f"    Pair Address: {pair_address}")
        
        await dex_api.close()
        
    except Exception as e:
        print(f"❌ Error with direct API call: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60 + "\n")
    
    # Test 2: Through PriceMonitor
    print("📈 Testing through PriceMonitor...")
    try:
        from config.settings import Settings
        from data.price_monitor import PriceMonitor
        from config.dexscreener_api import DexScreenerAPI
        
        settings = Settings()
        dex_api = DexScreenerAPI()
        price_monitor = PriceMonitor(settings, dex_api_client=dex_api)
        await price_monitor.initialize()
        
        # Add BONK to monitoring
        price_monitor.add_token(bonk_mint)
        
        # Fetch prices
        print(f"🔄 Fetching price for BONK...")
        await price_monitor.fetch_current_prices()
        
        # Get the price data
        price_data = price_monitor.get_token_price(bonk_mint)
        print(f"📊 PriceMonitor result:")
        print(json.dumps(price_data, indent=2) if price_data else "None")
        
        await price_monitor.close()
        
    except Exception as e:
        print(f"❌ Error with PriceMonitor: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60 + "\n")
    
    # Test 3: Through MarketData
    print("💰 Testing through MarketData...")
    try:
        from config.settings import Settings
        from data.market_data import MarketData
        
        settings = Settings()
        market_data = MarketData(settings)
        await market_data.initialize()
        
        # Get token price
        price_result = await market_data.get_token_price(bonk_mint, force_refresh=True)
        print(f"📊 MarketData result:")
        print(json.dumps(price_result, indent=2) if price_result else "None")
        
        await market_data.close()
        
    except Exception as e:
        print(f"❌ Error with MarketData: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_price_issue()) 