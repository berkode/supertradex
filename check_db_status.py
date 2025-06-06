#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))

from data.token_database import TokenDatabase
from config.settings import Settings

async def show_db_status():
    settings = Settings()
    db = TokenDatabase(settings)
    await db.initialize()
    
    print('🔍 TOKEN SCANNER RESULTS FROM DATABASE')
    print('=' * 60)
    
    # Get all tokens
    all_tokens = await db.get_tokens_list()
    print(f'📊 Total tokens in database: {len(all_tokens)}')
    
    if all_tokens:
        print('\n📈 Recent tokens (last 10):')
        recent_tokens = sorted(all_tokens, key=lambda x: x.last_updated or x.created_at, reverse=True)[:10]
        
        for i, token in enumerate(recent_tokens, 1):
            print(f'{i:2d}. {token.symbol} ({token.mint[:8]}...)')
            print(f'    💰 Price: ${token.price:.8f}' if token.price else '    💰 Price: N/A')
            print(f'    💧 Liquidity: ${token.liquidity:,.2f}' if token.liquidity else '    💧 Liquidity: N/A')
            print(f'    📊 Volume 24h: ${token.volume_24h:,.2f}' if token.volume_24h else '    📊 Volume 24h: N/A')
            print(f'    ✅ Filter Passed: {token.overall_filter_passed}')
            print(f'    🎯 Status: {token.monitoring_status}')
            print(f'    🏪 DEX: {token.dex_id}')
            print()
    
    # Get best token for trading
    print('🎯 BEST TOKEN FOR TRADING:')
    print('-' * 30)
    best_token = await db.get_best_token_for_trading(include_inactive_tokens=True)
    if best_token:
        print(f'🏆 Selected: {best_token.symbol} ({best_token.mint[:8]}...)')
        print(f'💰 Price: ${best_token.price:.8f}' if best_token.price else '💰 Price: N/A')
        print(f'💧 Liquidity: ${best_token.liquidity:,.2f}' if best_token.liquidity else '💧 Liquidity: N/A')
        print(f'📊 Volume 24h: ${best_token.volume_24h:,.2f}' if best_token.volume_24h else '📊 Volume 24h: N/A')
        print(f'🛡️ Rug Score: {best_token.rugcheck_score}' if best_token.rugcheck_score else '🛡️ Rug Score: N/A')
        print(f'🎯 Status: {best_token.monitoring_status}')
        print(f'🏪 DEX: {best_token.dex_id}')
        print(f'📍 Pair: {best_token.pair_address}')
    else:
        print('❌ No suitable token found for trading')
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(show_db_status()) 