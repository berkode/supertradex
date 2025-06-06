import asyncio
import aiohttp
from filters.rugcheck_api import RugcheckAPI
from config.settings import Settings

async def test_rugcheck():
    settings = Settings()
    api = RugcheckAPI(settings)
    
    # Test with multiple tokens
    tokens = [
        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
        'So11111111111111111111111111111111111111112',   # Wrapped SOL
        '7v91N7iZ9mNicL8WfG6cgSCKyRXydQjLh6UYBWwm6y1Q'  # Random token
    ]
    
    for token in tokens:
        result = await api.get_token_score(token)
        print(f'\nRugcheck result for {token}:', result)

if __name__ == '__main__':
    asyncio.run(test_rugcheck()) 