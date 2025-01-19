import os
import time
import logging
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configure logging
log_file = os.getenv("LOG_FILE", "price_monitor.log")
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler() if os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true" else None
    ]
)


class PriceMonitor:
    def __init__(self):
        self.dex_screener_api = os.getenv("DEX_SCREENER_API_BASE_URL", "https://api.dexscreener.com")
        self.poll_interval = int(os.getenv("POLL_INTERVAL", 30))  # Default poll interval: 30 seconds

        if not self.dex_screener_api:
            raise ValueError("DEX_SCREENER_API_BASE_URL must be set in the environment variables.")

    def fetch_token_price_and_order_book(self, token_address: str) -> dict:
        """
        Fetch token price and order book data from DexScreener.

        Args:
            token_address (str): Token mint address.

        Returns:
            dict: Data including price, order book, and trading volume.
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

            pair_data = pairs[0]  # Use the first pair data
            logging.info(f"Fetched price and order book data for token {token_address}")
            return {
                "price_usd": float(pair_data.get("priceUsd", 0.0)),
                "volume_24h_usd": float(pair_data.get("volume", {}).get("usd", 0.0)),
                "order_book": pair_data.get("orderBook", {}),
                "price_change_24h_percent": float(pair_data.get("priceChange", {}).get("percentage", 0.0))
            }
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error while fetching data for token {token_address}: {e}")
            return {}
        except Exception as e:
            logging.error(f"Unexpected error while fetching data for token {token_address}: {e}")
            return {}

    def monitor_prices(self, token_addresses: list):
        """
        Continuously monitor token prices and order book data.

        Args:
            token_addresses (list): List of token mint addresses to monitor.
        """
        logging.info(f"Starting price monitor for tokens: {token_addresses}")
        try:
            while True:
                for token_address in token_addresses:
                    data = self.fetch_token_price_and_order_book(token_address)
                    if data:
                        logging.info(f"Token: {token_address}")
                        logging.info(f"  Price (USD): ${data['price_usd']:.4f}")
                        logging.info(f"  24h Volume (USD): ${data['volume_24h_usd']:.2f}")
                        logging.info(f"  24h Price Change: {data['price_change_24h_percent']:.2f}%")
                        logging.info(f"  Order Book: {data['order_book']}")
                    else:
                        logging.warning(f"No data available for token: {token_address}")
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logging.info("Price monitor stopped manually.")
        except Exception as e:
            logging.error(f"Error in price monitoring loop: {e}")

