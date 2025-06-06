#!/usr/bin/env python3

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))

from config.settings import Settings
from data.token_database import TokenDatabase

async def remove_problematic_tokens():
    settings = Settings()
    db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
    
    # Remove nuit token from active monitoring due to bad Jupiter price data
    nuit_mint = '9SHnqjqmgaq9TiQQ3zWUG969WDf7XagpjuqbTpWiXsuZ'
    
    # Update token status to inactive
    await db.update_token_monitoring_status(nuit_mint, 'monitoring_failed')
    print(f'Updated nuit token status to monitoring_failed due to unrealistic Jupiter price (20+ SOL)')
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(remove_problematic_tokens()) 