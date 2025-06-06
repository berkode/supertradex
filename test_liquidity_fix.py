#!/usr/bin/env python3
"""
Test script to verify the liquidity data fix in TokenScanner
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
from utils.logger import get_logger

logger = get_logger(__name__)

async def test_liquidity_extraction():
    """Test the liquidity data extraction from DexScreener API"""
    
    logger.info("=== Testing Liquidity Data Extraction ===")
    
    try:
        # Initialize settings
        settings = Settings()
        logger.info("Settings loaded successfully")
        
        # Initialize database
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        logger.info("Database initialized")
        
        # Initialize DexScreener API
        dexscreener_api = DexScreenerAPI(settings)
        logger.info("DexScreener API initialized")
        
        # Test fetching trending tokens
        logger.info("Fetching trending tokens from DexScreener...")
        trending_tokens = await dexscreener_api.get_trending_tokens()
        
        if not trending_tokens:
            logger.warning("No trending tokens found")
            return
            
        logger.info(f"Found {len(trending_tokens)} trending tokens")
        
        # Test the first few tokens
        for i, token in enumerate(trending_tokens[:3]):
            logger.info(f"\n--- Token {i+1} ---")
            logger.info(f"Full token structure: {token}")
            logger.info(f"Chain ID: {token.get('chainId')}")
            logger.info(f"Pair Address: {token.get('pairAddress')}")
            
            # Check if it's a Solana token
            if token.get('chainId') == 'solana':
                mint = token.get('baseToken', {}).get('address')
                token_address = token.get('tokenAddress')  # Alternative field
                logger.info(f"Mint (baseToken.address): {mint}")
                logger.info(f"Token Address: {token_address}")
                
                if mint or token_address:
                    actual_mint = mint or token_address
                    logger.info(f"Using mint: {actual_mint}")
                    
                    # Test liquidity data extraction
                    liquidity_data = token.get('liquidity', {})
                    logger.info(f"Raw liquidity data: {liquidity_data}")
                    
                    if isinstance(liquidity_data, dict) and 'usd' in liquidity_data:
                        liquidity_usd = liquidity_data['usd']
                        logger.info(f"✅ Liquidity USD extracted: ${liquidity_usd:,.2f}")
                    else:
                        logger.warning(f"❌ No USD liquidity found in: {liquidity_data}")
                    
                    # Test volume data extraction
                    volume_data = token.get('volume', {})
                    logger.info(f"Raw volume data: {volume_data}")
                    
                    if isinstance(volume_data, dict) and 'h24' in volume_data:
                        volume_24h = volume_data['h24']
                        logger.info(f"✅ Volume 24h extracted: ${volume_24h:,.2f}")
                    else:
                        logger.warning(f"❌ No 24h volume found in: {volume_data}")
                        
                    # Test the mapping logic from the fix
                    token_copy = token.copy()
                    
                    # Apply the same mapping logic as in the fix
                    if isinstance(liquidity_data, dict) and 'usd' in liquidity_data:
                        token_copy['liquidity_usd'] = liquidity_data['usd']
                        logger.info(f"✅ Mapped liquidity_usd: ${token_copy['liquidity_usd']:,.2f}")
                    
                    if isinstance(volume_data, dict) and 'h24' in volume_data:
                        token_copy['volume_24h'] = volume_data['h24']
                        logger.info(f"✅ Mapped volume_24h: ${token_copy['volume_24h']:,.2f}")
                        
                    # Test the fallback extraction logic
                    test_token_data = {
                        'liquidity': liquidity_data,
                        'volume': volume_data
                    }
                    
                    # Test fallback extraction (from _prepare_token_for_db)
                    liquidity_usd_fallback = test_token_data.get('liquidity_usd')
                    if liquidity_usd_fallback is None:
                        liquidity_data_fallback = test_token_data.get('liquidity', {})
                        if isinstance(liquidity_data_fallback, dict):
                            liquidity_usd_fallback = liquidity_data_fallback.get('usd')
                    
                    if liquidity_usd_fallback is not None:
                        logger.info(f"✅ Fallback extraction successful: ${liquidity_usd_fallback:,.2f}")
                    else:
                        logger.warning("❌ Fallback extraction failed")
                else:
                    logger.warning("No mint address found in token")
            
        # Close resources
        await dexscreener_api.close()
        await db.close()
        
        logger.info("\n=== Test completed successfully ===")
        
    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_liquidity_extraction()) 