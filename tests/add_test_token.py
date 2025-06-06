#!/usr/bin/env python3
"""
Add test token with explicit commit to ensure persistence
"""

import asyncio
import sys
import os
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

from config.settings import Settings
from data.token_database import TokenDatabase
from data.models import Token

async def add_test_token():
    settings = Settings()
    token_db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await token_db.initialize()
    
    print("🔧 Adding test token with explicit commit...")
    
    # Test token data
    test_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"  # BONK
    test_symbol = "BONK"
    test_pair = "8ekQ7m3fcRMUVdLhE5SuWY8HBHkG9NHyqRuYx95F7W7P"  # A real BONK/SOL pair
    test_dex = "raydium_v4"
    
    # Add using the ORM method with explicit commit
    session = await token_db._get_session()
    try:
        async with session:
            # First check if token already exists
            existing_token = await session.get(Token, test_mint)
            if existing_token:
                print(f"Token {test_symbol} already exists. Deleting first...")
                await session.delete(existing_token)
                await session.commit()
                print(f"Deleted existing token {test_symbol}")
            
            # Create new token
            new_token = Token(
                mint=test_mint,
                symbol=test_symbol,
                name="Bonk",
                pair_address=test_pair,
                dex_id=test_dex,
                price=0.000025,
                is_valid=True
            )
            
            session.add(new_token)
            await session.commit()
            print(f"✅ Added token {test_symbol} with explicit commit")
            
            # Verify it was added
            await session.refresh(new_token)
            print(f"Verification: Token ID={new_token.id}, Symbol={new_token.symbol}, is_valid={new_token.is_valid}")
            
    except Exception as e:
        print(f"❌ Error adding token: {e}")
        await session.rollback()
    finally:
        await session.close()
    
    # Now verify from a fresh session
    print(f"\n🔍 Verifying from fresh session...")
    session2 = await token_db._get_session()
    try:
        async with session2:
            from sqlalchemy import select
            stmt = select(Token).filter(Token.mint == test_mint)
            result = await session2.execute(stmt)
            token = result.scalars().first()
            if token:
                print(f"✅ Token found: {token.symbol} | is_valid: {token.is_valid}")
            else:
                print(f"❌ Token not found in fresh session")
    finally:
        await session2.close()
    
    await token_db.close()

if __name__ == "__main__":
    asyncio.run(add_test_token()) 