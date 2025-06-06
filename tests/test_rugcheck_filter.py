import asyncio
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.absolute())
sys.path.append(project_root)

from config.settings import Settings, initialize_settings
from filters.rugcheck_api import RugcheckAPI
from utils.logger import get_logger

async def test_rugcheck_filtering():
    # Initialize settings
    initialize_settings()
    settings = Settings()
    
    # Initialize rugcheck API
    rugcheck = RugcheckAPI(settings)
    
    # Sample tokens to test
    tokens = [
        {
            'mint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            'name': 'USDC',
            'symbol': 'USDC'
        },
        {
            'mint': 'So11111111111111111111111111111111111111112',  # Wrapped SOL
            'name': 'Wrapped SOL',
            'symbol': 'SOL'
        },
        {
            'mint': '7v91N7iZ9mNicL8WfG6cgSCKyRXydQjLh6UYBWwm6y1Q',  # Random token
            'name': 'Random Token',
            'symbol': 'RND'
        }
    ]
    
    # Get rugcheck scores for all tokens
    for token in tokens:
        print(f"\nChecking token: {token['name']} ({token['symbol']})")
        print(f"Mint: {token['mint']}")
        
        score_data = await rugcheck.get_token_score(token['mint'])
        if score_data:
            print(f"Rugcheck score: {score_data.get('rugcheck_score_normalised', 'N/A')}")
            print(f"Score: {score_data.get('rugcheck_score', 'N/A')}")
            print(f"Risks: {score_data.get('risks', [])}")
            print(f"Rugged: {score_data.get('rugged', False)}")
            
            # Check if token passes the filter
            if score_data.get('rugcheck_score_normalised', 100) <= settings.MAX_RUGCHECK_SCORE:
                print("✅ Token PASSES rugcheck filter")
            else:
                print("❌ Token FAILS rugcheck filter")
        else:
            print("❌ Could not get rugcheck score for token")

if __name__ == "__main__":
    asyncio.run(test_rugcheck_filtering()) 