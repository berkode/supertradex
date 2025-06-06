#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

# Setup environment
sys.path.append(str(Path.cwd()))
from utils.encryption import decrypt_env_file, get_encryption_password
from dotenv import dotenv_values
import io
import os

env_dir = Path('config')
env_encrypted_path = env_dir / '.env.encrypted'
if env_encrypted_path.exists():
    password = get_encryption_password()
    if password:
        decrypted_content = decrypt_env_file(env_encrypted_path, password)
        if decrypted_content:
            env_vars = dotenv_values(stream=io.StringIO(decrypted_content))
            for key, value in env_vars.items():
                if value and key not in os.environ:
                    os.environ[key] = str(value)

from data.token_database import TokenDatabase
from config.settings import Settings

async def check_saphi():
    settings = Settings()
    db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
    
    # Check Saphi token
    saphi_mint = "7ZYyESa8TkuoBVFi5seeLPr7B3MeLvyPgEgv5MDTpump"
    token = await db.get_token_by_mint(saphi_mint)
    
    if token:
        print(f"✅ Saphi token found:")
        print(f"  Symbol: {token.symbol}")
        print(f"  Mint: {token.mint}")
        print(f"  DEX ID: {token.dex_id}")
        print(f"  Pair Address: {token.pair_address}")
        print(f"  Name: {token.name}")
    else:
        print(f"❌ Saphi token not found with mint: {saphi_mint}")
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(check_saphi()) 