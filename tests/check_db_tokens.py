#!/usr/bin/env python3
"""
Check tokens available in database for real-time price testing
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

env_dir = project_root / "config"
env_encrypted_path = env_dir / ".env.encrypted"
if env_encrypted_path.exists():
    password = get_encryption_password()
    if password:
        decrypted_content = decrypt_env_file(env_encrypted_path, password)
        if decrypted_content:
            env_vars = dotenv_values(stream=io.StringIO(decrypted_content))
            import os
            for key, value in env_vars.items():
                if key not in os.environ:
                    os.environ[key] = value

from data.token_database import TokenDatabase
from config.settings import Settings

async def check_tokens():
    settings = Settings()
    db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await db.initialize()
    
    print("=" * 60)
    print("TOKENS AVAILABLE FOR REAL-TIME PRICE TESTING")
    print("=" * 60)
    
    tokens = await db.get_valid_tokens()
    print(f'Found {len(tokens)} valid tokens in database:')
    print()
    
    for i, token in enumerate(tokens[:10]):  # Show first 10
        print(f'{i+1:2d}. {token.symbol:10s} | {token.mint[:8]}... | {token.dex_id:12s} | Pair: {token.pair_address[:8] if token.pair_address else "None"}...')
    
    if len(tokens) > 10:
        print(f"... and {len(tokens) - 10} more tokens")
        
    print()
    print("Looking for tokens with complete data (pair_address and dex_id):")
    
    complete_tokens = []
    for token in tokens:
        if token.pair_address and token.dex_id:
            complete_tokens.append(token)
    
    if complete_tokens:
        print(f"Found {len(complete_tokens)} tokens with complete data:")
        for i, token in enumerate(complete_tokens[:5]):
            print(f"  {i+1}. {token.symbol} ({token.mint[:8]}...) - {token.dex_id} - Pair: {token.pair_address[:8]}...")
    else:
        print("No tokens found with both pair_address and dex_id")
    
    await db.close()
    return complete_tokens

if __name__ == "__main__":
    tokens = asyncio.run(check_tokens()) 