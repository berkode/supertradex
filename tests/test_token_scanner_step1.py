import asyncio
import logging
import os
from unittest.mock import patch, AsyncMock
from dotenv import load_dotenv
from data.token_scanner import TokenScanner
from config.settings import Settings
from config.logging_config import LoggingConfig
from utils.token_scanner_utils import TokenScannerUtils
from utils.logger import get_logger
import pytest

# Explicitly setup logging *before* other initializations
LoggingConfig.setup_logging()

# Configure logger for this script *after* setup
logger = get_logger(__name__)
# logging.basicConfig(level=logging.DEBUG) # BasicConfig might interfere, rely on setup_logging

# --- Mock Rugcheck API Response --- 
def mock_get_token_score(token_address):
    """Simulates responses from rugcheck_api.get_token_score"""
    # Simulate some tokens failing, some passing
    # Example: Make tokens ending in even numbers fail
    if int(token_address[-1], 16) % 2 == 0:
        # Simulate failing score (above threshold)
        logger.debug(f"MOCK Rugcheck: Failing score for {token_address}")
        return {'score_normalised': 80, 'details': {'reason': 'mock failure'}}
    else:
        # Simulate passing score (below threshold)
        logger.debug(f"MOCK Rugcheck: Passing score for {token_address}")
        return {'score_normalised': 30, 'details': {'reason': 'mock pass'}}
# --- End Mock --- 

@pytest.mark.asyncio
async def test_token_scanner_pipeline():
    """Test the initial steps of the token scanner pipeline."""
    logger.info("Starting test_token_scanner_pipeline...")

    # Ensure environment is clean if needed, though Settings should handle override
    # os.environ.pop('MIN_VOLUME_24H', None) # Example of cleaning up env var if needed

    try:
        # Mock validations and external API calls
        logger.info("Setting up mocks...")
        # NOTE: Ensure the paths ('config.twitter_config.TwitterConfig.validate_config', etc.)
        # correctly point to where these methods are DEFINED, not necessarily where they are used.
        with patch('config.twitter_config.TwitterConfig.validate_config', return_value=True), \
             patch('config.filters_config.FiltersConfig._load_criteria', return_value={}), \
             patch('data.token_scanner.RugcheckAPI.get_token_score', new_callable=AsyncMock, side_effect=mock_get_token_score):

            logger.info("Initializing Settings and Scanner inside test context...")
            # Initialize Settings - This should load from config/.env now
            settings = Settings()
            logger.debug(f"Settings initialized: {settings.__dict__}") # Log settings attributes

            # Initialize FiltersConfig and TwitterConfig using the initialized Settings
            filters_config = FiltersConfig(settings)
            twitter_config = TwitterConfig(settings)

            # Initialize TokenScanner with mocked dependencies
            logger.info("Initializing TokenScanner...")
            scanner = TokenScanner(settings, filters_config, twitter_config)
            logger.info("TokenScanner initialized.")

            # --- Simulate step 1: Fetching initial data ---
            # Since we are focusing on initialization and env var loading,
            # we might not need to call complex methods yet.
            # Let's just check if the initialization worked.
            assert scanner is not None
            assert scanner.settings is not None
            assert scanner.filters_config is not None
            assert scanner.twitter_config is not None
            logger.info("Basic scanner initialization assertions passed.")

            # Example: Check if a setting loaded correctly
            assert settings.MIN_VOLUME_24H > 0 # Check if a critical env var is loaded and has a valid type/value
            logger.info(f"Checked MIN_VOLUME_24H: {settings.MIN_VOLUME_24H}")


            # --- (Optional) Simulate step 2: Calling a method that uses loaded settings ---
            # Example: If scanner has a method that uses RugcheckAPI mock
            # await scanner.evaluate_token("valid_token_address")
            # mock_get_token_score.assert_called_once_with("valid_token_address")
            # logger.info("Mocked external API call verified.")


    except Exception as e:
        logger.error(f"Error during test execution: {e}", exc_info=True)
        pytest.fail(f"Test failed due to exception: {e}")

    logger.info("test_token_scanner_pipeline finished successfully.")

if __name__ == "__main__":
    asyncio.run(test_token_scanner_pipeline()) 