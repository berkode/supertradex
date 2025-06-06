#!/usr/bin/env python3
"""
Check tokens available in database by DEX type for focused price monitoring
"""

import asyncio
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

from data.token_database import TokenDatabase
from config.settings import Settings

async def check_tokens_by_dex():
    settings = Settings()
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await db.initialize()
    
    print("=" * 70)
    print("TOKENS BY DEX TYPE - FOR FOCUSED PRICE MONITORING")
    print("=" * 70)
    
    tokens = await db.get_valid_tokens()
    print(f'Found {len(tokens)} valid tokens in database\n')
    
    # Group tokens by DEX type
    dex_tokens = {
        'raydium_clmm': [],
        'raydium_v4': [],
        'pumpswap': []
    }
    
    for token in tokens:
        if token.pair_address and token.dex_id:  # Only complete tokens
            if token.dex_id == 'raydium_clmm':
                dex_tokens['raydium_clmm'].append(token)
            elif token.dex_id == 'raydium_v4':
                dex_tokens['raydium_v4'].append(token)
            elif token.dex_id == 'pumpswap':
                dex_tokens['pumpswap'].append(token)
    
    # Display tokens by DEX
    for dex_name, dex_token_list in dex_tokens.items():
        print(f"🔥 {dex_name.upper()} TOKENS ({len(dex_token_list)} available)")
        print("-" * 50)
        
        if dex_token_list:
            for i, token in enumerate(dex_token_list[:5]):  # Show first 5
                print(f"{i+1:2d}. {token.symbol:12s} | {token.mint[:8]}... | Pair: {token.pair_address[:8]}...")
            
            if len(dex_token_list) > 5:
                print(f"    ... and {len(dex_token_list) - 5} more tokens")
        else:
            print("    ❌ No tokens available for this DEX")
        
        print()
    
    # Recommend tokens for testing
    print("🎯 RECOMMENDED TOKENS FOR FOCUSED MONITORING:")
    print("-" * 50)
    
    recommendations = {}
    
    for dex_name, dex_token_list in dex_tokens.items():
        if dex_token_list:
            # Prefer BONK if available, otherwise first token
            selected_token = None
            for token in dex_token_list:
                if token.symbol.upper() == "BONK":
                    selected_token = token
                    break
            
            if not selected_token:
                selected_token = dex_token_list[0]
            
            recommendations[dex_name] = selected_token
            print(f"{dex_name:15s}: {selected_token.symbol:10s} | {selected_token.mint[:12]}...")
    
    print()
    print("✅ These tokens will be used for 60-second blockchain vs PriceMonitor comparison")
    
    await db.close()
    return recommendations

if __name__ == "__main__":
    asyncio.run(check_tokens_by_dex()) 