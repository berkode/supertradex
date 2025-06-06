#!/usr/bin/env python3
"""
Minimal script to test TokenScanner initialization and identify the issue.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import necessary modules
from config.settings import Settings
from utils.logger import get_logger

async def test_scanner():
    """Test TokenScanner initialization"""
    
    logger = get_logger(__name__)
    
    logger.info("Testing TokenScanner initialization...")
    
    try:
        # Load settings
        logger.info("Loading settings...")
        settings = Settings()
        logger.info("Settings loaded successfully")
        
        # Log the TOKEN_SCAN_INTERVAL value
        logger.info(f"TOKEN_SCAN_INTERVAL: {getattr(settings, 'TOKEN_SCAN_INTERVAL', 'NOT DEFINED')}")
        
        # Try to access it directly
        if hasattr(settings, 'TOKEN_SCAN_INTERVAL'):
            logger.info(f"TOKEN_SCAN_INTERVAL value: {settings.TOKEN_SCAN_INTERVAL}")
        else:
            logger.error("TOKEN_SCAN_INTERVAL is not defined in settings!")
            
    except Exception as e:
        logger.error(f"Error during settings initialization: {e}", exc_info=True)
        return
    
    logger.info("Test completed")

if __name__ == "__main__":
    asyncio.run(test_scanner()) 