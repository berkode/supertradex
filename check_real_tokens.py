#!/usr/bin/env python3
"""
Check Real Tokens in Database
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from data.token_database import TokenDatabase

async def check_real_tokens():
    """Check what real tokens are in the database"""
    try:
        print("🔧 Checking database for real tokens...")
        
        # Initialize settings and database
        settings = Settings()
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        
        # Get all tokens
        tokens = await db.get_tokens_list()
        print(f"📊 Database contains {len(tokens)} tokens")
        
        if len(tokens) > 0:
            print("\n🔍 All tokens in database:")
            sorted_tokens = sorted(tokens, key=lambda x: x.volume_24h or 0, reverse=True)
            for i, token in enumerate(sorted_tokens, 1):
                status_emoji = "🟢" if token.monitoring_status == "active" else "🔴" if token.monitoring_status == "monitoring_failed" else "🟡"
                
                # Handle None values safely
                symbol = token.symbol or "N/A"
                volume = token.volume_24h or 0
                liquidity = token.liquidity or 0
                rugcheck = token.rugcheck_score or 0
                dex_id = token.dex_id or "N/A"
                
                print(f"  {i:2d}. {status_emoji} {symbol:8s} | Vol: ${volume:>12,.0f} | Liq: ${liquidity:>10,.0f} | Rug: {rugcheck:>4.1f} | DEX: {dex_id}")
                print(f"      Mint: {token.mint}")
                print(f"      Pair: {token.pair_address}")
                print(f"      Filter Passed: {token.overall_filter_passed}")
                print()
        else:
            print("❌ No tokens found in database!")
        
        # Cleanup
        await db.close()
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_real_tokens()) 