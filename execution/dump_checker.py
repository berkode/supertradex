import logging
import os
from typing import Dict, Optional
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("DumpChecker")


class DumpChecker:
    """
    Class to perform a final dump detection check using DexScreener before executing trades.
    """
    def __init__(self, http_client=None, settings=None):
        """
        Initialize the DumpChecker with shared resources and configurations.
        
        Args:
            http_client: Shared HTTP client instance
            settings: Settings instance containing configuration
        """
        self.http_client = http_client
        self.settings = settings
        
        # Load settings from Settings instance
        self.dex_screener_api_url = getattr(settings, 'DEXSCREENER_API_URL', 'https://api.dexscreener.io/latest/dex/tokens')
        self.liquidity_threshold = float(getattr(settings, 'MIN_LIQUIDITY', 1000.0))
        
        logger.info(
            "DumpChecker initialized with DexScreener API: %s and liquidity threshold: %.2f USD",
            self.dex_screener_api_url,
            self.liquidity_threshold,
        )

    def fetch_token_data(self, token_address: str) -> Optional[Dict]:
        """
        Fetch token data from DexScreener.

        Args:
            token_address (str): The blockchain address of the token.

        Returns:
            Optional[Dict]: Token data if available, None otherwise.
        """
        try:
            url = f"{self.dex_screener_api_url}/{token_address}"
            logger.debug("Fetching token data from URL: %s", url)
            response = requests.get(url)
            response.raise_for_status()
            token_data = response.json()
            logger.info("Token data fetched successfully for %s from DexScreener.", token_address)
            return token_data
        except requests.RequestException as e:
            logger.error("Failed to fetch token data for %s: %s", token_address, str(e))
            return None

    def is_dump_safe(self, token_address: str) -> bool:
        """
        Perform a final dump check on a token.

        Args:
            token_address (str): The blockchain address of the token.

        Returns:
            bool: True if the token passes the dump check, False otherwise.
        """
        token_data = self.fetch_token_data(token_address)
        if not token_data:
            logger.warning("No data available for token %s. Dump check failed.", token_address)
            return False

        # Check liquidity
        liquidity = token_data.get("liquidity", {}).get("usd", 0)
        if liquidity < self.liquidity_threshold:
            logger.warning(
                "Token %s failed dump check due to insufficient liquidity: %.2f USD (Threshold: %.2f USD).",
                token_address, liquidity, self.liquidity_threshold,
            )
            return False

        logger.info("Token %s passed the final dump check with liquidity: %.2f USD.", token_address, liquidity)
        return True

    def validate_token(self, mint: str) -> bool:
        """
        Wrapper to validate the token before executing trades.

        Args:
            mint (str): The blockchain address of the token.

        Returns:
            bool: True if the token passes validation, False otherwise.
        """
        logger.info("Starting final dump check for token %s.", mint)
        return self.is_dump_safe(mint) 