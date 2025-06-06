import os
import requests
import logging
from typing import Dict, Any, Optional
import httpx
from config.settings import Settings

# Configure logging for the module
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RaydiumAPI")


class RaydiumAPI:
    """Class to interact with the Raydium V3 API."""

    def __init__(self, settings: Settings):
        """Initialize with settings."""
        self.settings = settings
        self.api_url = settings.RAYDIUM_API_URL
        self.http_timeout = settings.HTTP_TIMEOUT
        logger.debug(f"RaydiumAPI initialized with URL: {self.api_url}")

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
        url = f"{self.api_url}{endpoint}"
        try:
            logger.info(f"Making request to {url} with params: {params}")
            response = requests.get(url, params=params, timeout=self.http_timeout)
            response.raise_for_status()
            data = response.json()

            if not data.get("success", False):
                error_msg = data.get("msg", "Unknown error")
                logger.error(f"API error: {error_msg}")
                raise Exception(f"API error: {error_msg}")

            return data["data"]
        except requests.RequestException as e:
            logger.exception(f"Request failed for {url}: {e}")
            raise

    def get_version(self):
        """Fetch the current UI version of Raydium V3.

        Returns:
            dict: Version information.
        """
        return self._make_request("/main/version")

    def get_chain_time(self):
        """Fetch the current chain time from the Raydium API.

        Returns:
            dict: Chain time information.
        """
        return self._make_request("/main/chain-time")

    def get_tvl_and_volume(self):
        """Fetch the total value locked (TVL) and 24-hour trading volume.

        Returns:
            dict: TVL and volume data.
        """
        return self._make_request("/main/info")

    def get_stake_pools(self):
        """Fetch the available stake pools.

        Returns:
            dict: Stake pool data.
        """
        return self._make_request("/main/stake-pools")

    def get_pool_info_by_ids(self, pool_ids):
        """Fetch pool information by pool IDs.

        Args:
            pool_ids (list): List of pool IDs.

        Returns:
            dict: Pool information.
        """
        params = {"pool_ids": ",".join(pool_ids)}
        return self._make_request("/pools/info/ids", params=params)

    def get_farm_pool_info(self, farm_ids):
        """Fetch farm pool information by IDs.

        Args:
            farm_ids (list): List of farm pool IDs.

        Returns:
            dict: Farm pool information.
        """
        params = {"farm_ids": ",".join(farm_ids)}
        return self._make_request("/farms/info/ids", params=params)

    def get_mint_price(self, mint_address):
        """Fetch the mint price for a specific mint address.

        Args:
            mint_address (str): The mint address.

        Returns:
            dict: Mint price information.
        """
        params = {"mint": mint_address}
        return self._make_request("/mint/price", params=params)