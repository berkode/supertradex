import os
import requests
import logging
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configure logging
log_file = os.getenv("LOG_FILE", "token_metrics.log")
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler() if os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true" else None
    ]
)


class TokenMetrics:
    def __init__(self):
        self.dex_screener_api = os.getenv("DEX_SCREENER_API_BASE_URL", "https://api.dexscreener.com")
        self.default_currency = os.getenv("DEFAULT_CURRENCY", "usd")

        if not self.dex_screener_api:
            raise ValueError("DEX_SCREENER_API_BASE_URL is not set in the environment variables.")

    def fetch_token_data(self, token_address: str) -> dict:
        """
        Fetch token data from DexScreener.

        Args:
            token_address (str): Token mint address.

        Returns:
            dict: Token data including price, market cap, and trading volume.
        """
        try:
            url = f"{self.dex_screener_api}/latest/dex/pairs/solana/{token_address}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            pairs = data.get("pairs", [])
            if not pairs:
                logging.warning(f"No data found for token: {token_address}")
                return {}

            logging.info(f"Fetched data from DexScreener for {token_address}")
            return pairs[0]  # Use the first pair data
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error while fetching data for token {token_address}: {e}")
            return {}
        except Exception as e:
            logging.error(f"Unexpected error while fetching data for token {token_address}: {e}")
            return {}

    def generate_metrics(self, token_address: str) -> dict:
        """
        Generate metrics for a token using DexScreener data.

        Args:
            token_address (str): Token mint address.

        Returns:
            dict: Metrics including price, market cap, price changes, and trading volume.
        """
        token_data = self.fetch_token_data(token_address)

        if not token_data:
            logging.warning(f"Metrics generation failed for token {token_address}: No data available.")
            return {}

        # Extract relevant data
        try:
            price = float(token_data.get("priceUsd", 0.0))
            volume_24h = float(token_data.get("volume", {}).get("usd", 0.0))
            price_change_24h = float(token_data.get("priceChange", {}).get("percentage", 0.0))
            market_cap = float(token_data.get("fdv", 0.0))  # Fully diluted valuation as market cap

            metrics = {
                "price_usd": price,
                "market_cap_usd": market_cap,
                "volume_24h_usd": volume_24h,
                "price_change_24h_percent": price_change_24h
            }

            logging.info(f"Generated metrics for token {token_address}: {metrics}")
            return metrics
        except (TypeError, ValueError) as e:
            logging.error(f"Error processing data for token {token_address}: {e}")
            return {}

    def validate_token_address(self, token_address: str):
        """
        Validate the format of the token address.

        Args:
            token_address (str): Token mint address.

        Returns:
            bool: True if valid, False otherwise.
        """
        if not token_address or len(token_address) != 44:
            logging.error(f"Invalid token address: {token_address}")
            raise ValueError("Invalid token address. Ensure it is a valid 44-character Solana mint address.")

