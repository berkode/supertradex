import os
import requests
import logging
from requests.adapters import HTTPAdapter, Retry
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging for the module
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DexScreenerAPI")

class DexScreenerAPI:
    """Class to interact with the Dex Screener API."""

    BASE_URL = os.getenv("DEX_SCREENER_API_BASE_URL", "https://api.dexscreener.com")

    def __init__(self):
        """Initialize the session with retry mechanisms for robust API communication."""
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _make_request(self, endpoint, params=None):
        """Helper function to make GET requests to the API.

        Args:
            endpoint (str): API endpoint.
            params (dict): Query parameters for the request.

        Returns:
            dict: Response data if successful.

        Raises:
            Exception: For any API errors or failures.
        """
        url = f"{self.BASE_URL}{endpoint}"
        try:
            logger.info(f"Making request to {url} with params: {params}")
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data
        except requests.RequestException as e:
            logger.exception(f"Request failed for {url}: {e}")
            raise

    def get_latest_token_profiles(self):
        """Fetch the latest token profiles.

        Returns:
            dict: Token profiles data.
        """
        return self._make_request("/token-profiles/latest/v1")

    def get_latest_boosted_tokens(self):
        """Fetch the latest boosted tokens.

        Returns:
            dict: Boosted tokens data.
        """
        return self._make_request("/token-boosts/latest/v1")

    def get_top_boosted_tokens(self):
        """Fetch tokens with the most active boosts.

        Returns:
            dict: Top boosted tokens data.
        """
        return self._make_request("/token-boosts/top/v1")

    def get_orders(self, chain_id, token_address):
        """Fetch orders paid for a token.

        Args:
            chain_id (str): Blockchain chain ID.
            token_address (str): Token address.

        Returns:
            dict: Orders data.
        """
        endpoint = f"/orders/v1/{chain_id}/{token_address}"
        return self._make_request(endpoint)

    def get_pairs_by_chain_and_address(self, chain_id, pair_id):
        """Fetch one or multiple pairs by chain and pair address.

        Args:
            chain_id (str): Blockchain chain ID.
            pair_id (str): Pair address.

        Returns:
            dict: Pairs data.
        """
        endpoint = f"/latest/dex/pairs/{chain_id}/{pair_id}"
        return self._make_request(endpoint)

    def search_pairs(self, query):
        """Search for pairs matching a query.

        Args:
            query (str): Search query.

        Returns:
            dict: Search results.
        """
        params = {"q": query}
        return self._make_request("/latest/dex/search", params=params)

    def get_token_pools(self, chain_id, token_address):
        """Fetch the pools of a given token address.

        Args:
            chain_id (str): Blockchain chain ID.
            token_address (str): Token address.

        Returns:
            dict: Token pools data.
        """
        endpoint = f"/token-pairs/v1/{chain_id}/{token_address}"
        return self._make_request(endpoint)

    def get_tokens_by_address(self, chain_id, token_addresses):
        """Fetch one or multiple pairs by token address.

        Args:
            chain_id (str): Blockchain chain ID.
            token_addresses (list): List of token addresses.

        Returns:
            dict: Token pairs data.
        """
        token_addresses_str = ",".join(token_addresses)
        endpoint = f"/tokens/v1/{chain_id}/{token_addresses_str}"
        return self._make_request(endpoint)


