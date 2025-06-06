#!/usr/bin/env python3

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))

from config.settings import Settings
from data.token_database import TokenDatabase

async def check_nuit_token():
    settings = Settings()
    db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
    
    nuit_mint = '9SHnqjqmgaq9TiQQ3zWUG969WDf7XagpjuqbTpWiXsuZ'
    token = await db.get_token_by_mint(nuit_mint)
    
    if token:
        print(f'NUIT Token Details:')
        print(f'  Symbol: {token.symbol}')
        print(f'  Name: {token.name}')
        print(f'  DEX: {token.dex_id}')
        print(f'  Pair: {token.pair_address}')
        print(f'  Volume 24h: ${token.volume_24h:,.2f}' if token.volume_24h else '  Volume 24h: N/A')
        print(f'  Liquidity: ${token.liquidity:,.2f}' if token.liquidity else '  Liquidity: N/A')
        print(f'  Price USD: ${token.price_usd}' if token.price_usd else '  Price USD: N/A')
        print(f'  Rug Score: {token.rugcheck_score}')
        print(f'  Status: {token.monitoring_status}')
        print(f'  Filter Passed: {token.overall_filter_passed}')
    else:
        print('NUIT token not found in database')
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(check_nuit_token()) 