#!/usr/bin/env python3
"""
Test boolean comparison fix for SQLite
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
from sqlalchemy import select, text

async def test_boolean_fix():
    settings = Settings()
    token_db = TokenDatabase(settings.DATABASE_FILE_PATH, settings)
    await token_db.initialize()
    
    print("🔍 Testing boolean comparison fix...")
    
    # Test 1: Direct SQL check
    session = await token_db._get_session()
    async with session as session:
        result = await session.execute(text("SELECT COUNT(*) FROM tokens"))
        total_count = result.scalar()
        print(f"Total tokens in database: {total_count}")
        
        result = await session.execute(text("SELECT COUNT(*) FROM tokens WHERE is_valid = 1"))
        valid_count_sql = result.scalar()
        print(f"Valid tokens (SQL WHERE is_valid = 1): {valid_count_sql}")
        
        result = await session.execute(text("SELECT mint, symbol, is_valid FROM tokens"))
        all_tokens = result.fetchall()
        print(f"All tokens raw data:")
        for token in all_tokens:
            print(f"  Mint: {token[0][:8]}... | Symbol: {token[1]} | is_valid: {token[2]} (type: {type(token[2])})")
    
    # Test 2: Old SQLAlchemy method
    print(f"\n🔧 Testing old method (== True)...")
    session = await token_db._get_session()
    async with session as session:
        try:
            stmt = select(Token).filter(Token.is_valid == True)
            result = await session.execute(stmt)
            tokens_old = result.scalars().all()
            print(f"Old method (== True): {len(tokens_old)} tokens")
        except Exception as e:
            print(f"Old method failed: {e}")
    
    # Test 3: New SQLAlchemy method
    print(f"\n✅ Testing new method (.is_(True))...")
    session = await token_db._get_session()
    async with session as session:
        try:
            stmt = select(Token).filter(Token.is_valid.is_(True))
            result = await session.execute(stmt)
            tokens_new = result.scalars().all()
            print(f"New method (.is_(True)): {len(tokens_new)} tokens")
            if tokens_new:
                for token in tokens_new:
                    print(f"  Token: {token.symbol} | Mint: {token.mint[:8]}... | is_valid: {token.is_valid}")
        except Exception as e:
            print(f"New method failed: {e}")
    
    # Test 4: Test get_valid_tokens method
    print(f"\n🎯 Testing get_valid_tokens() method...")
    valid_tokens = await token_db.get_valid_tokens()
    print(f"get_valid_tokens() returned: {len(valid_tokens)} tokens")
    if valid_tokens:
        for token in valid_tokens:
            print(f"  Token: {token.symbol} | Mint: {token.mint[:8]}... | is_valid: {token.is_valid}")
    
    await token_db.close()

if __name__ == "__main__":
    asyncio.run(test_boolean_fix()) 