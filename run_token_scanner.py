#!/usr/bin/env python3
"""
Run Token Scanner to get REAL tokens
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from data.token_database import TokenDatabase
from data.token_scanner import TokenScanner
from data.market_data import MarketData
from config.thresholds import Thresholds
from config.dexscreener_api import DexScreenerAPI
from config.rugcheck_api import RugcheckAPI

class MinimalFilterManager:
    """Minimal filter manager for basic token scanning"""
    def __init__(self, settings, thresholds):
        self.settings = settings
        self.thresholds = thresholds
        
    async def initialize(self):
        """Initialize the minimal filter manager"""
        pass
        
    async def apply_filters(self, token_data, current_time=None, initial_scan=False):
        """Apply minimal filtering - return the token data with filter results"""
        # Add minimal filter results to the token data
        token_data['overall_filter_passed'] = True
        token_data['filter_results'] = {
            'minimal_filter': {'passed': True, 'reason': 'Minimal filtering enabled'}
        }
        return token_data
        
    async def close(self):
        """Close the filter manager"""
        pass

async def run_token_scanner():
    """Run the TokenScanner to get real tokens"""
    try:
        print("🔧 Initializing TokenScanner for REAL token scanning...")
        
        # Initialize settings and database
        settings = Settings()
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        
        # Initialize required components
        thresholds = Thresholds(settings)
        dexscreener_api = DexScreenerAPI(settings)
        rugcheck_api = RugcheckAPI(settings)
        
        # Initialize market data
        market_data = MarketData(settings, dexscreener_api, db)
        await market_data.initialize()
        
        # Create minimal filter manager
        filter_manager = MinimalFilterManager(settings, thresholds)
        await filter_manager.initialize()
        
        # Initialize token scanner
        token_scanner = TokenScanner(
            db=db,
            settings=settings,
            thresholds=thresholds,
            filter_manager=filter_manager,
            market_data=market_data,
            dexscreener_api=dexscreener_api,
            token_metrics=None,   # Skip token metrics for now
            rugcheck_api=rugcheck_api
        )
        await token_scanner.initialize()
        
        print("🚀 Starting REAL token scan...")
        await token_scanner.scan_tokens()
        
        # Check results
        tokens = await db.get_tokens_list()
        print(f"✅ Token scan complete! Found {len(tokens)} REAL tokens")
        
        if len(tokens) > 0:
            print("\n🔍 Top 10 REAL tokens by volume:")
            sorted_tokens = sorted(tokens, key=lambda x: x.volume_24h or 0, reverse=True)[:10]
            for i, token in enumerate(sorted_tokens, 1):
                # Handle None values safely
                symbol = token.symbol or "UNKNOWN"
                volume = token.volume_24h or 0
                liquidity = token.liquidity or 0
                rugcheck = token.rugcheck_score or 0
                dex_id = token.dex_id or "N/A"
                
                print(f"  {i:2d}. {symbol:8s} | Vol: ${volume:>12,.0f} | Liq: ${liquidity:>10,.0f} | Rug: {rugcheck:>4.1f} | DEX: {dex_id}")
        
        # Cleanup
        await filter_manager.close()
        await market_data.close()
        await db.close()
        
        print("🎉 REAL token scanning completed successfully!")
        
    except Exception as e:
        print(f"❌ Error running token scanner: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_token_scanner()) 