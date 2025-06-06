#!/usr/bin/env python3
"""
Test script for the new Raydium and Jupiter price parsers
"""

import asyncio
import logging
from config.settings import Settings
from data import RaydiumPriceParser, JupiterPriceParser

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_price_parsers():
    """Test the new price parsers"""
    try:
        # Load settings
        settings = Settings()
        logger.info("Settings loaded successfully")
        
        # Test tokens (SOL and a popular token)
        test_tokens = [
            "So11111111111111111111111111111111111111112",  # SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"   # USDC
        ]
        
        # Initialize parsers
        raydium_parser = RaydiumPriceParser(settings, logger)
        jupiter_parser = JupiterPriceParser(settings, logger)
        
        logger.info("Initializing price parsers...")
        
        # Initialize parsers
        raydium_init = await raydium_parser.initialize()
        jupiter_init = await jupiter_parser.initialize()
        
        if not raydium_init:
            logger.error("Failed to initialize Raydium parser")
            return
            
        if not jupiter_init:
            logger.error("Failed to initialize Jupiter parser")
            return
            
        logger.info("✅ Both parsers initialized successfully")
        
        # Test single price fetching
        logger.info("\n=== Testing Single Price Fetching ===")
        
        for token in test_tokens:
            logger.info(f"\nTesting token: {token[:8]}...")
            
            # Test Raydium parser
            try:
                raydium_price = await raydium_parser.fetch_single_price(token)
                if raydium_price:
                    logger.info(f"📈 Raydium: ${raydium_price.get('price_usd', 'N/A'):.6f} | {raydium_price.get('price_sol', 'N/A'):.8f} SOL")
                else:
                    logger.warning("❌ Raydium: No price data")
            except Exception as e:
                logger.error(f"❌ Raydium error: {e}")
            
            # Test Jupiter parser
            try:
                jupiter_price = await jupiter_parser.fetch_single_price(token)
                if jupiter_price:
                    logger.info(f"🪐 Jupiter: ${jupiter_price.get('price_usd', 'N/A'):.6f} | {jupiter_price.get('price_sol', 'N/A'):.8f} SOL")
                else:
                    logger.warning("❌ Jupiter: No price data")
            except Exception as e:
                logger.error(f"❌ Jupiter error: {e}")
        
        # Test monitoring functionality
        logger.info("\n=== Testing Price Monitoring ===")
        
        # Add tokens to monitoring
        for token in test_tokens:
            raydium_parser.add_token_to_monitor(token)
            jupiter_parser.add_token_to_monitor(token)
        
        # Test callback function
        price_updates = []
        
        async def price_callback(price_data):
            price_updates.append(price_data)
            source = price_data.get('source', 'unknown')
            mint = price_data.get('mint', 'unknown')
            price_sol = price_data.get('price_sol')
            price_usd = price_data.get('price_usd')
            
            price_str = f"{price_sol:.8f} SOL" if price_sol else "N/A SOL"
            if price_usd:
                price_str += f" (${price_usd:.6f})"
            
            logger.info(f"💰 {source.upper()} update: {mint[:8]}... = {price_str}")
        
        # Start monitoring for a short period
        logger.info("Starting price monitoring for 30 seconds...")
        
        await raydium_parser.start_price_monitoring(callback=price_callback)
        await jupiter_parser.start_price_monitoring(callback=price_callback)
        
        # Wait for some price updates
        await asyncio.sleep(30)
        
        # Stop monitoring
        await raydium_parser.stop_price_monitoring()
        await jupiter_parser.stop_price_monitoring()
        
        logger.info(f"\n✅ Monitoring test complete. Received {len(price_updates)} price updates")
        
        # Get status
        raydium_status = raydium_parser.get_monitoring_status()
        jupiter_status = jupiter_parser.get_monitoring_status()
        
        logger.info(f"\nRaydium status: {raydium_status}")
        logger.info(f"Jupiter status: {jupiter_status}")
        
        # Clean up
        await raydium_parser.close()
        await jupiter_parser.close()
        
        logger.info("\n✅ Price parser test completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_price_parsers()) 