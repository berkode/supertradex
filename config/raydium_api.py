import os
import requests
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging for the module
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RaydiumAPI")

class RaydiumAPI:
    """Class to interact with the Raydium V3 API."""

    BASE_URL = os.getenv("RAYDIUM_API_BASE_URL", "https://api-v3.raydium.io")

    @staticmethod
    def _make_request(endpoint, params=None):
        """Helper function to make GET requests to the API.

        Args:
            endpoint (str): API endpoint.
            params (dict): Query parameters for the request.

        Returns:
            dict: Response data if successful.

        Raises:
            Exception: For any API errors or failures.
        """
        url = f"{RaydiumAPI.BASE_URL}{endpoint}"
        try:
            logger.info(f"Making request to {url} with params: {params}")
            response = requests.get(url, params=params)
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

    @classmethod
    def get_version(cls):
        """Fetch the current UI version of Raydium V3.

        Returns:
            dict: Version information.
        """
        return cls._make_request("/main/version")

    @classmethod
    def get_chain_time(cls):
        """Fetch the current chain time from the Raydium API.

        Returns:
            dict: Chain time information.
        """
        return cls._make_request("/main/chain-time")

    @classmethod
    def get_tvl_and_volume(cls):
        """Fetch the total value locked (TVL) and 24-hour trading volume.

        Returns:
            dict: TVL and volume data.
        """
        return cls._make_request("/main/info")

    @classmethod
    def get_stake_pools(cls):
        """Fetch the available stake pools.

        Returns:
            dict: Stake pool data.
        """
        return cls._make_request("/main/stake-pools")

    @classmethod
    def get_pool_info_by_ids(cls, pool_ids):
        """Fetch pool information by pool IDs.

        Args:
            pool_ids (list): List of pool IDs.

        Returns:
            dict: Pool information.
        """
        params = {"pool_ids": ",".join(pool_ids)}
        return cls._make_request("/pools/info/ids", params=params)

    @classmethod
    def get_farm_pool_info(cls, farm_ids):
        """Fetch farm pool information by IDs.

        Args:
            farm_ids (list): List of farm pool IDs.

        Returns:
            dict: Farm pool information.
        """
        params = {"farm_ids": ",".join(farm_ids)}
        return cls._make_request("/farms/info/ids", params=params)

    @classmethod
    def get_mint_price(cls, mint_address):
        """Fetch the mint price for a specific mint address.

        Args:
            mint_address (str): The mint address.

        Returns:
            dict: Mint price information.
        """
        params = {"mint": mint_address}
        return cls._make_request("/mint/price", params=params)

