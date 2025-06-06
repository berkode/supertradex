#!/usr/bin/env python3
"""
Test script to manually trigger a token scan and test liquidity data extraction
"""
import asyncio
import sys
import os
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from data.token_database import TokenDatabase
from config.dexscreener_api import DexScreenerAPI
from config.thresholds import Thresholds
from config.filters_config import FiltersConfig
from filters.filter_manager import FilterManager
from data.token_metrics import TokenMetrics
from data.market_data import MarketData
from data.token_scanner import TokenScanner
from utils.logger import get_logger
import httpx

logger = get_logger(__name__)

async def test_manual_scan():
    """Test a manual token scan to verify liquidity data extraction"""
    
    logger.info("=== Manual Token Scan Test ===")
    
    try:
        # Initialize settings
        settings = Settings()
        logger.info("Settings loaded successfully")
        
        # Initialize database
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        logger.info("Database initialized")
        
        # Initialize thresholds
        thresholds = Thresholds(settings)
        logger.info("Thresholds initialized")
        
        # Initialize filters config
        filters_config = FiltersConfig()
        logger.info("FiltersConfig initialized")
        
        # Initialize HTTP client
        http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("HTTP client initialized")
        
        # Initialize DexScreener API
        dexscreener_api = DexScreenerAPI(settings)
        logger.info("DexScreener API initialized")
        
        # Initialize TokenMetrics
        token_metrics = TokenMetrics(settings)
        logger.info("TokenMetrics initialized")
        
        # Initialize MarketData (simplified)
        market_data = MarketData(db=db, settings=settings)
        logger.info("MarketData initialized")
        
        # Initialize FilterManager (simplified)
        filter_manager = FilterManager(
            settings=settings,
            thresholds=thresholds,
            filters_config=filters_config,
            rugcheck_api=None,  # Simplified for testing
            solsniffer_api=None,
            twitter_check=None
        )
        logger.info("FilterManager initialized")
        
        # Initialize TokenScanner
        token_scanner = TokenScanner(
            db=db,
            settings=settings,
            thresholds=thresholds,
            filter_manager=filter_manager,
            market_data=market_data,
            dexscreener_api=dexscreener_api,
            token_metrics=token_metrics,
            rugcheck_api=None
        )
        logger.info("TokenScanner initialized")
        
        # Initialize the scanner
        await token_scanner.initialize()
        logger.info("TokenScanner components initialized")
        
        # Run a manual scan
        logger.info("🚀 Starting manual token scan...")
        await token_scanner.scan_tokens()
        logger.info("✅ Manual token scan completed")
        
        # Check database for results
        logger.info("Checking database for scan results...")
        
        # Simple database check
        from simple_db_check import check_database
        await check_database()
        
        # Close resources
        await token_scanner.close()
        await market_data.close()
        await dexscreener_api.close()
        await db.close()
        await http_client.aclose()
        
        logger.info("=== Manual scan test completed successfully ===")
        
    except Exception as e:
        logger.error(f"Error during manual scan test: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_manual_scan()) 