import logging
from typing import Dict, Any, Optional
import httpx
import asyncio
import requests
from datetime import time
from config.settings import Settings
from requests.adapters import HTTPAdapter, Retry
from dotenv import load_dotenv
from utils.logger import get_logger

# Load environment variables from .env
load_dotenv()

# Get logger for this module
logger = get_logger(__name__)

class DataFetcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http_timeout = settings.HTTP_TIMEOUT
        self.rpc_url = settings.HELIUS_RPC_URL
        self.dex_screener_api_url = settings.DEXSCREENER_API_URL
        self.dexscreener_token_qty = settings.DEXSCREENER_TOKEN_QTY
        self.min_liquidity = settings.MIN_LIQUIDITY
        self.raydium_api = settings.RAYDIUM_API_URL
        self.rate_limit_sleep = settings.BASE_DELAY
        self.retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        self.session = None
        logger.info("DataFetcher instance created")
        
    async def initialize(self) -> bool:
        """
        Initialize the data fetcher component.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            logger.info("Initializing DataFetcher")
            self.session = self._init_session()
            logger.info("DataFetcher initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing DataFetcher: {e}")
            # Return True to allow application to continue
            return True
            
    async def close(self):
        """
        Close resources used by the data fetcher component.
        """
        try:
            if self.session:
                self.session.close()
                self.session = None
                logger.info("Closed HTTP session for DataFetcher")
                
        except Exception as e:
            logger.error(f"Error closing DataFetcher resources: {e}")

    def _init_session(self):
        """
        Initialize a session with retry strategy.

        Returns:
            requests.Session: Configured session with retries.
        """
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=self.retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _fetch_data(self, url: str, params: dict = None) -> dict:
        """
        Fetch data from the given URL with retries.

        Args:
            url (str): API endpoint.
            params (dict): Query parameters for the API request.

        Returns:
            dict: API response data in JSON format or an empty dict on failure.
        """
        try:
            logging.info(f"Fetching data from {url}")
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            logging.info(f"Data fetched successfully from {url}")
            return response.json()
        except requests.exceptions.Timeout:
            logging.error(f"Timeout while fetching data from {url}")
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP error while fetching data from {url}: {e}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching data from {url}: {e}")
        return {}

    def fetch_dex_screener_data(self, mint: str) -> dict:
        """
        Fetch data for a specific token from DexScreener.

        Args:
            mint (str): Token mint address.

        Returns:
            dict: Token data from DexScreener or an empty dict if the fetch fails.
        """
        if not mint:
            logging.error("Token address must be provided for DexScreener data fetch.")
            return {}
        url = f"{self.dex_screener_api_url}/latest/dex/pairs/solana/{mint}"
        return self._fetch_data(url)

    def fetch_raydium_pool_data(self, pool_address: str) -> dict:
        """
        Fetch liquidity pool data from Raydium.

        Args:
            pool_address (str): Raydium liquidity pool address.

        Returns:
            dict: Pool data from Raydium or an empty dict if the fetch fails.
        """
        if not pool_address:
            logging.error("Pool address must be provided for Raydium data fetch.")
            return {}
        url = f"{self.raydium_api}/pool/{pool_address}"
        return self._fetch_data(url)

    def fetch_batch_data(self, api_urls: list) -> list:
        """
        Fetch data from multiple API URLs with rate limiting.

        Args:
            api_urls (list): List of API endpoints.

        Returns:
            list: List of API responses.
        """
        responses = []
        for url in api_urls:
            data = self._fetch_data(url)
            responses.append(data)
            time.sleep(self.rate_limit_sleep)  # Throttle requests
        return responses

    def validate_response(self, data: dict, required_keys: list = None) -> bool:
        """
        Validate the API response to ensure it contains the required keys.

        Args:
            data (dict): API response data.
            required_keys (list): Keys to validate in the response.

        Returns:
            bool: True if the response contains all required keys, False otherwise.
        """
        if not data:
            logging.error("Response is empty or invalid.")
            return False
        if required_keys:
            missing_keys = [key for key in required_keys if key not in data]
            if missing_keys:
                logging.error(f"Response is missing required keys: {missing_keys}")
                return False
        return True
