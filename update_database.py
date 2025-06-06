#!/usr/bin/env python3
"""
Update Database with New Tokens from TokenScanner
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from data.token_database import TokenDatabase

async def update_database_with_new_tokens():
    """Update database with new tokens by running the existing TokenScanner"""
    try:
        print("🔄 UPDATING DATABASE WITH NEW TOKENS")
        print("=" * 60)
        
        # Get current token count
        settings = Settings()
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        current_tokens = await db.get_tokens_list()
        initial_count = len(current_tokens)
        print(f"📊 Current database contains {initial_count} tokens")
        await db.close()
        
        # Run the existing token scanner script
        print("🔍 Running TokenScanner to find new tokens...")
        import subprocess
        result = subprocess.run([
            sys.executable, "run_token_scanner.py"
        ], capture_output=True, text=True, cwd=str(Path(__file__).parent))
        
        if result.returncode != 0:
            print(f"❌ TokenScanner failed with error: {result.stderr}")
            return
        
        # Check new token count
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        updated_tokens = await db.get_tokens_list()
        final_count = len(updated_tokens)
        new_tokens_found = final_count - initial_count
        
        print(f"\n✅ Database update completed!")
        print(f"📊 Total tokens: {final_count}")
        print(f"🆕 New tokens found: {new_tokens_found}")
        
        if new_tokens_found > 0:
            print("\n🔍 Latest tokens in database:")
            # Sort by volume and show top tokens
            sorted_tokens = sorted(updated_tokens, key=lambda x: x.volume_24h or 0, reverse=True)
            for i, token in enumerate(sorted_tokens[:min(10, final_count)], 1):
                symbol = token.symbol or "UNKNOWN"
                volume = token.volume_24h or 0
                liquidity = token.liquidity or 0
                rugcheck = token.rugcheck_score or 0
                dex_id = token.dex_id or "N/A"
                
                print(f"  {i:2d}. {symbol:8s} | Vol: ${volume:>12,.0f} | Liq: ${liquidity:>10,.0f} | Rug: {rugcheck:>4.1f} | DEX: {dex_id}")
        else:
            print("📊 No new tokens found - database is up to date")
        
        await db.close()
        
    except Exception as e:
        print(f"❌ Error updating database: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Main function"""
    await update_database_with_new_tokens()

if __name__ == "__main__":
    asyncio.run(main()) 