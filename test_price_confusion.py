#!/usr/bin/env python3

import requests
import json

def test_token_price_confusion(mint, name):
    print(f"\n=== Testing {name} ===")
    print(f"Mint: {mint}")
    
    # Jupiter API
    try:
        jupiter_url = f'https://price.jup.ag/v6/price?ids={mint}'
        jupiter_response = requests.get(jupiter_url, timeout=10)
        jupiter_data = jupiter_response.json()
        jupiter_price = jupiter_data['data'][mint]['price']
        print(f"Jupiter price: {jupiter_price} (claiming this is SOL price)")
    except Exception as e:
        print(f"Jupiter error: {e}")
        return
    
    # DexScreener API  
    try:
        dex_url = f'https://api.dexscreener.com/latest/dex/tokens/{mint}'
        dex_response = requests.get(dex_url, timeout=10)
        dex_data = dex_response.json()
        
        if dex_data.get('pairs'):
            # Find SOL pair
            sol_pair = None
            for pair in dex_data['pairs']:
                base_symbol = pair.get('baseToken', {}).get('symbol', '')
                quote_symbol = pair.get('quoteToken', {}).get('symbol', '')
                if 'SOL' in base_symbol or 'SOL' in quote_symbol:
                    sol_pair = pair
                    break
            
            if sol_pair:
                price_usd = float(sol_pair['priceUsd'])
                # Convert USD to SOL (assuming SOL = ~$240)
                sol_price_estimate = price_usd / 240
                print(f"DexScreener USD price: ${price_usd}")
                print(f"DexScreener SOL price estimate: {sol_price_estimate} SOL")
                
                # Calculate the ratio
                if sol_price_estimate > 0:
                    ratio = jupiter_price / sol_price_estimate
                    print(f"Jupiter/DexScreener ratio: {ratio:,.0f}x")
                    
                    # Check if Jupiter price is close to USD price
                    usd_ratio = jupiter_price / price_usd
                    print(f"Jupiter price vs USD price ratio: {usd_ratio:.2f}")
                    
                    if abs(usd_ratio - 1.0) < 0.1:  # Within 10%
                        print("🚨 JUPITER IS RETURNING USD PRICE, NOT SOL PRICE! 🚨")
                    else:
                        print("Jupiter price doesn't match USD price")
                        
            else:
                print("No SOL pair found on DexScreener")
        else:
            print("No pairs found on DexScreener")
    except Exception as e:
        print(f"DexScreener error: {e}")

if __name__ == "__main__":
    # Test multiple tokens from our actual database
    tokens = [
        ("6seWHZha1YeDTeQihV3zEWtwXcjrdP1tawoZkCNwpump", "Bono"),
        ("G2YTPWqXnz1LRbtMZALd6ygSHBy5jubAe6Fs7a4Do1Tm", "DEVIL"),
        ("GoyQny5V8y55io9MDCSeTMPcvnjgu9yqjrx1QYPrpump", "whatif"),
        ("9SHnqjqmgaq9TiQQ3zWUG969WDf7XagpjuqbTpWiXsuZ", "nuit"),  # Our problematic token
        ("FgAEC3TqyX4vwdMxFSnKA2HpwETvyh6RpjKxcP8jpump", "shytcoin"),  # Another one
    ]
    
    for mint, name in tokens:
        test_token_price_confusion(mint, name)
        
    print("\n" + "="*50)
    print("CONCLUSION:")
    print("If Jupiter consistently shows prices ~240x higher than")
    print("DexScreener SOL prices, then Jupiter is returning USD prices")
    print("when we're asking for SOL prices!") 