#!/usr/bin/env python3
import logging
import asyncio
import httpx
from config.settings import Settings
from config.dexscreener_api import DexScreenerAPI
from data.price_monitor import PriceMonitor
from data.token_database import TokenDatabase

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_price_monitor")

# Test token address from the error logs
TEST_TOKEN = "4WdRBeTP84y9K7bkVPbZ7j2LVz4pUfB76d9bAo2Zpump"  # NKYS token

async def main():
    logger.info("Starting PriceMonitor test...")
    settings = Settings()
    
    # Initialize http client
    http_client = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT)
    logger.info(f"Created HTTP client with timeout: {settings.HTTP_TIMEOUT}s")
    
    # Initialize DexScreenerAPI
    dex_api = DexScreenerAPI(settings=settings)
    logger.info("Initialized DexScreenerAPI")
    
    # Initialize database
    db = TokenDatabase(db_path=settings.DATABASE_FILE_PATH)
    await db.initialize()
    logger.info(f"Initialized database at: {settings.DATABASE_FILE_PATH}")
    
    # Initialize PriceMonitor
    price_monitor = PriceMonitor(
        settings=settings, 
        dex_api_client=dex_api, 
        http_client=http_client,
        db=db
    )
    initialized = await price_monitor.initialize()
    logger.info(f"PriceMonitor initialized: {initialized}")
    
    # Start monitoring the test token
    await price_monitor.start_monitoring(TEST_TOKEN)
    logger.info(f"Started monitoring token: {TEST_TOKEN}")
    
    # Start the monitoring loop in the background
    monitor_task = asyncio.create_task(price_monitor.run_monitor_loop())
    logger.info("Started monitoring loop in background")
    
    # Wait for a few seconds to allow the PriceMonitor to fetch data
    logger.info("Waiting 10 seconds for data fetching...")
    await asyncio.sleep(10)
    
    # Check if the price is available
    price = await price_monitor.get_price(TEST_TOKEN)
    logger.info(f"Price for {TEST_TOKEN}: ${price}")
    
    # Get latest price data
    latest_data = price_monitor.get_latest_price(TEST_TOKEN)
    if latest_data:
        logger.info(f"Latest price data: {latest_data}")
    else:
        logger.warning(f"No latest price data found for {TEST_TOKEN}")
    
    # Get token data cache
    token_data = await price_monitor.get_latest_data(TEST_TOKEN)
    if token_data:
        logger.info(f"Token data cache: {token_data}")
    else:
        logger.warning(f"No token data in cache for {TEST_TOKEN}")
    
    # Clean up
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        logger.info("Monitor task cancelled")
    
    await price_monitor.close()
    logger.info("PriceMonitor closed")
    
    await db.close()
    logger.info("Database connection closed")
    
    await http_client.aclose()
    logger.info("HTTP client closed")
    
    logger.info("Test completed")

if __name__ == "__main__":
    asyncio.run(main()) 