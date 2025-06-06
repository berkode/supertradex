#!/usr/bin/env python3
"""
Test price field extraction to find where the issue is
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

async def test_price_extraction():
    print("🔍 TESTING PRICE FIELD EXTRACTION\n")
    
    bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    
    try:
        from config.settings import Settings
        from data.market_data import MarketData
        
        settings = Settings()
        market_data = MarketData(settings)
        await market_data.initialize()
        
        print("📊 Testing get_token_price method...")
        price_result = await market_data.get_token_price(bonk_mint, force_refresh=True)
        
        print(f"🔍 Raw price_result:")
        print(json.dumps(price_result, indent=2))
        
        # Check specific fields
        if price_result:
            print(f"\n🎯 Field Analysis:")
            print(f"   'price' field: {price_result.get('price')} (type: {type(price_result.get('price'))})")
            print(f"   'priceUsd' field: {price_result.get('priceUsd')} (type: {type(price_result.get('priceUsd'))})")
            print(f"   'price_usd' field: {price_result.get('price_usd')} (type: {type(price_result.get('price_usd'))})")
            
            # Check for any field that might contain the price
            for key, value in price_result.items():
                if 'price' in key.lower() and value is not None:
                    try:
                        float_val = float(value)
                        if float_val > 0:
                            print(f"   ✅ Found price in '{key}': {value} -> {float_val}")
                    except:
                        print(f"   ❓ Non-numeric price in '{key}': {value}")
        
        await market_data.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_price_extraction()) 