import asyncio
import logging
import time
from data.token_scanner import TokenScanner
from config.settings import Settings
from utils.logger import get_logger

# Configure logging
logger = get_logger(__name__)
logging.basicConfig(level=logging.INFO)

async def main():
    try:
        # Initialize settings
        settings = Settings()
        
        # Initialize token scanner
        scanner = TokenScanner(settings)
        
        while True:  # Run continuously
            try:
                # Run token scanner
                logger.info("Starting token scanner...")
                results = await scanner.scan_tokens()
                
                # Print results
                logger.info(f"Found {len(results)} tokens:")
                for token in results:
                    logger.info(f"""
Token: {token.get('symbol', 'N/A')}
Address: {token.get('address', 'N/A')}
Market Cap: ${token.get('market_cap', 0):,.2f}
Age: {token.get('age_minutes', 0)} minutes
Volume 24h: ${token.get('volume_24h', 0):,.2f}
Liquidity: ${token.get('liquidity', 0):,.2f}
Rugcheck Score: {token.get('rugcheck_score', 0)}
SolSniffer Score: {token.get('solsniffer_score', 0)}
Twitter Followers: {token.get('twitter_followers', 0)}
Category: {token.get('category', 'N/A')}
                    """)
                
                # Wait for the configured poll interval before next scan
                logger.info(f"Waiting {settings.POLL_INTERVAL} seconds before next scan...")
                await asyncio.sleep(settings.POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in scan cycle: {str(e)}")
                # Wait for error retry interval before retrying
                await asyncio.sleep(settings.ERROR_RETRY_INTERVAL)
            
    except Exception as e:
        logger.error(f"Error running token scanner: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())