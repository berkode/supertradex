#!/usr/bin/env python3

import asyncio
import httpx
import json

async def test_jupiter_api_direct():
    """Test Jupiter API directly to see what it returns"""
    
    # Test tokens from our database
    test_tokens = [
        ("9SHnqjqmgaq9TiQQ3zWUG969WDf7XagpjuqbTpWiXsuZ", "nuit"),
        ("C5WyeT2WsmeSRkaJfEhUdnvscgaesimiZMSTLmxwpump", "334ig5555a"),
        ("51xjcecr9aBspDQq36gg35j2kqMEJfHft51EtQUMpump", "Meowtrix"),
    ]
    
    sol_mint = "So11111111111111111111111111111111111111112"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for mint, symbol in test_tokens:
            print(f"\n=== Testing {symbol} ({mint[:8]}...) ===")
            
            try:
                # Test 1: Get price vs SOL (what we want)
                url_vs_sol = f"https://lite-api.jup.ag/price/v2?ids={mint}&vsToken={sol_mint}"
                print(f"URL: {url_vs_sol}")
                
                response = await client.get(url_vs_sol)
                if response.status_code == 200:
                    data = response.json()
                    print(f"Response: {json.dumps(data, indent=2)}")
                    
                    if 'data' in data and mint in data['data']:
                        price_info = data['data'][mint]
                        price = price_info.get('price')
                        print(f"🎯 Jupiter price vs SOL: {price}")
                        
                        # Check if this makes sense
                        if price and float(price) > 1.0:
                            print(f"⚠️  WARNING: Price {price} SOL seems too high!")
                        elif price and float(price) < 0.000000001:
                            print(f"⚠️  WARNING: Price {price} SOL seems too low!")
                        else:
                            print(f"✅ Price {price} SOL seems reasonable")
                    else:
                        print("❌ No price data found in response")
                else:
                    print(f"❌ HTTP Error: {response.status_code}")
                    print(f"Response: {response.text}")
                    
            except Exception as e:
                print(f"❌ Error: {e}")
            
            # Test 2: Get price vs USDC (default)
            try:
                url_vs_usdc = f"https://lite-api.jup.ag/price/v2?ids={mint}"
                print(f"\nURL (vs USDC): {url_vs_usdc}")
                
                response = await client.get(url_vs_usdc)
                if response.status_code == 200:
                    data = response.json()
                    
                    if 'data' in data and mint in data['data']:
                        price_info = data['data'][mint]
                        price_usd = price_info.get('price')
                        print(f"🎯 Jupiter price vs USDC: ${price_usd}")
                    else:
                        print("❌ No USD price data found")
                else:
                    print(f"❌ HTTP Error for USD: {response.status_code}")
                    
            except Exception as e:
                print(f"❌ USD Error: {e}")
                
        # Test 3: Get SOL price itself
        print(f"\n=== Testing SOL price ===")
        try:
            url_sol = f"https://lite-api.jup.ag/price/v2?ids={sol_mint}"
            response = await client.get(url_sol)
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and sol_mint in data['data']:
                    sol_price_usd = data['data'][sol_mint]['price']
                    print(f"🎯 SOL price: ${sol_price_usd} USD")
                else:
                    print("❌ No SOL price found")
            else:
                print(f"❌ SOL price error: {response.status_code}")
        except Exception as e:
            print(f"❌ SOL price error: {e}")

if __name__ == "__main__":
    asyncio.run(test_jupiter_api_direct()) 