import os
import logging
import time
import random
import aiohttp
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Any, Union, TYPE_CHECKING
from config.settings import Settings
from utils.logger import get_logger
from utils.proxy_manager import ProxyManager
import json

# Import Settings for type hinting only
if TYPE_CHECKING:
    from config.settings import Settings
    from utils.proxy_manager import ProxyManager # Import if type hint needed

# Get logger for this module
logger = get_logger(__name__)

# Define constants
SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"
PUMPSWAP_DEX_ID = "pump"

class DexScreenerAPI:
    """
    Client for interacting with the DexScreener API to retrieve trending tokens
    and detailed token information.
    Requires a Settings object for configuration.
    """

    def __init__(self, settings: 'Settings', proxy_manager: Optional['ProxyManager'] = None):
        """Initialize the DexScreener API client.
        
        Args:
            settings: The application Settings instance.
            proxy_manager: Optional ProxyManager instance.
        """
        # Ensure settings is provided
        if not settings:
            # This should ideally not happen if instantiated correctly from main.py
            logger.critical("Settings object not provided to DexScreenerAPI. Cannot initialize.")
            raise ValueError("Settings object is required for DexScreenerAPI")
            
        self.settings = settings
        self.proxy_manager = proxy_manager
        
        # Get URLs and config from the provided settings object
        try:
            self.base_url = self.settings.DEXSCREENER_API_URL
            self.trending_endpoint = self.settings.DEXSCREENER_API_LATEST
            self.details_endpoint = self.settings.DEXSCREENER_API_DETAILS
            http_timeout_seconds = getattr(self.settings, 'HTTP_TIMEOUT', 30.0)
            self.timeout = aiohttp.ClientTimeout(total=http_timeout_seconds)
        except AttributeError as e:
             logger.critical(f"Missing required setting for DexScreenerAPI: {e}")
             raise ValueError(f"Missing required setting for DexScreenerAPI: {e}")
        
        # API request settings (could also be moved to settings if needed)
        self.max_retries = 3
        self.base_delay = 3
        self.max_delay = 30
        self.session: Optional[aiohttp.ClientSession] = None # Initialize as None
        self._logged_first_trending_token = False
        self._rate_limit_semaphore = asyncio.Semaphore(5) # Limit concurrent API calls
        
        logger.info(f"DexScreenerAPI initialized (Base: {self.base_url}, Timeout: {http_timeout_seconds}s)")
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an HTTP session."""
        logger.debug(f"DexScreenerAPI._get_session called. Current self.session: {self.session}, closed: {self.session.closed if self.session else 'N/A'}")
        # Creates session on first use
        if self.session is None or self.session.closed:
            logger.info(f"DexScreenerAPI: self.session is None or closed. Attempting to create new session. Was None: {self.session is None}, Was Closed: {self.session.closed if self.session else 'N/A'}")
            headers = {
                "Accept": "application/json",
                "User-Agent": "SupertradeX/1.0" # Example User-Agent
            }
            # Timeout is already set in self.timeout
            try:
                new_session = aiohttp.ClientSession(timeout=self.timeout, headers=headers)
                logger.info(f"DexScreenerAPI: New aiohttp.ClientSession created: {new_session}")
                self.session = new_session
            except Exception as e:
                logger.error(f"DexScreenerAPI: Exception during aiohttp.ClientSession creation: {e}", exc_info=True)
                # If session creation fails, self.session might remain None or the old closed session.
                # We should probably raise an error here or return None to indicate failure.
                # For now, let it proceed to see if self.session is None later.
                raise # Re-raise the exception to make the failure explicit
        logger.debug(f"DexScreenerAPI._get_session returning. New self.session: {self.session}, closed: {self.session.closed if self.session else 'N/A'}")
        return self.session
        
    async def close(self):
        """Close the HTTP session if it exists and is open."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Closed DexScreenerAPI aiohttp session.")
            self.session = None # Reset session variable
            
    async def initialize(self) -> bool:
        """Initialize the client (primarily tests connection)."""
        # Session is created lazily by _get_session if needed
        return await self.test_connection()
            
    async def _make_request(self, url: str, method: str = "GET", **kwargs) -> Union[Dict, List]:
        """Make HTTP request with retry logic, semaphore, and proxy support."""
        async with self._rate_limit_semaphore: # Acquire semaphore before making request
            session = await self._get_session()
            
            for attempt in range(self.max_retries):
                proxy = None
                proxy_url_str = None # For logging/marking failure
                if self.proxy_manager:
                    proxy_url_str = self.proxy_manager.get_proxy()
                    if proxy_url_str: proxy = proxy_url_str 
                
                try:
                    logger.debug(f"Attempt {attempt+1}/{self.max_retries}: {method} {url} (Proxy: {proxy_url_str or 'None'})")
                    async with session.request(
                        method, url, proxy=proxy, **kwargs
                    ) as response:
                        
                        # Handle specific status codes for retry/failure
                        if response.status == 429: # Rate limit
                            logger.warning(f"Rate limit hit (429) on attempt {attempt+1} for {url}. Retrying after delay...")
                            # Mark proxy failure only if rate limited?
                            # if proxy_url_str and self.proxy_manager: self.proxy_manager.mark_proxy_failure(proxy_url_str)
                        elif response.status >= 500: # Server errors
                            logger.warning(f"Server error ({response.status}) on attempt {attempt+1} for {url}. Retrying after delay...")
                            if proxy_url_str and self.proxy_manager: self.proxy_manager.mark_proxy_failure(proxy_url_str)
                        else:
                            response.raise_for_status() # Raise for other 4xx errors immediately
                            # Success or non-retryable error
                            try:
                                data = await response.json()
                                return data
                            except aiohttp.ContentTypeError:
                                text_response = await response.text()
                                logger.error(f"Non-JSON response from {url}. Status: {response.status}. Response: {text_response[:500]}")
                                raise aiohttp.ClientError("Non-JSON response")

                        # If we need to retry (429 or 5xx)
                        if attempt < self.max_retries - 1:
                            wait_time = min(self.base_delay * (2 ** attempt) + random.uniform(0, 1), self.max_delay)
                            logger.info(f"Waiting {wait_time:.1f}s before retry {attempt + 2}...")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(f"Request failed after {self.max_retries} attempts due to status {response.status}.")
                            response.raise_for_status() # Raise the final error

                except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                    logger.warning(f"Network/Timeout error on attempt {attempt+1} for {url}: {e}")
                    if proxy_url_str and self.proxy_manager: self.proxy_manager.mark_proxy_failure(proxy_url_str)
                    if attempt < self.max_retries - 1:
                         wait_time = min(self.base_delay * (2 ** attempt) + random.uniform(0, 1), self.max_delay)
                         logger.info(f"Waiting {wait_time:.1f}s before retry {attempt + 2}...")
                         await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"Request failed after {self.max_retries} attempts due to {type(e).__name__}.")
                        raise # Re-raise the final error
                except aiohttp.ClientResponseError as e: # Non-retryable client errors (e.g., 404)
                    logger.error(f"Client response error for {url}: {e.status} {e.message}")
                    raise # Don't retry 4xx errors unless specifically handled
                except Exception as e:
                    logger.error(f"Unexpected error during request to {url} (Attempt {attempt+1}): {e}", exc_info=True)
                    # Decide if retry makes sense for unexpected errors
                    if attempt < self.max_retries - 1:
                         wait_time = min(self.base_delay * (2 ** attempt) + random.uniform(0, 1), self.max_delay)
                         logger.info(f"Waiting {wait_time:.1f}s before retry {attempt + 2} due to unexpected error...")
                         await asyncio.sleep(wait_time)
                    else:
                        raise # Re-raise unexpected errors after retries
                        
        # This should ideally not be reached if raise occurs in loop
        logger.critical(f"Request failed for {url} after all retries and error handling.")
        raise aiohttp.ClientError(f"Request failed definitively for {url}")
        
    async def test_connection(self) -> bool:
        """Test connection to DexScreener API using the trending endpoint."""
        try:
            test_url = self.trending_endpoint 
            logger.debug(f"Testing connection to DexScreener API: {test_url}")
            # Use _make_request to include retry/error handling
            await self._make_request(test_url, method="GET")
            logger.info("Successfully connected to DexScreener API")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to DexScreener API: {e}")
            return False
            
    async def get_trending_tokens(self) -> List[Dict]:
        """Get list of trending tokens from the DexScreener TRENDING endpoint."""
        try:
            logger.debug(f"Fetching trending tokens from: {self.trending_endpoint}")
            response_data = await self._make_request(self.trending_endpoint)

            # The trending endpoint returns a list of pair objects directly
            if isinstance(response_data, list):
                if not self._logged_first_trending_token and response_data:
                    # Safely log the first pair
                    try: logger.debug(f"Raw DexScreener TRENDING pair example: {json.dumps(response_data[0], indent=2)}")
                    except Exception: logger.debug(f"Raw DexScreener TRENDING pair example (unserializable): {response_data[0]}")
                    self._logged_first_trending_token = True
                logger.info(f"Successfully fetched {len(response_data)} pairs from DexScreener trending endpoint.")
                return response_data # Return the list directly
            else:
                logger.error(f"Unexpected response type for trending tokens (expected list): {type(response_data)}")
                return [] # Explicitly return empty list on error
        except Exception as e:
            logger.error(f"Error fetching trending tokens: {e}", exc_info=True)
            return [] # Explicitly return empty list on error
            
    async def get_token_details(self, tokens: Union[str, List[str]]) -> Dict[str, Any]:
        """Get detailed pair information for token(s). Always returns a Dict {'pairs': [...] }"""
        try:
            is_single_token_request = False
            if isinstance(tokens, list):
                if not tokens: return {"pairs": []}
                addresses_str = ",".join(tokens[:30]) # API limit
                if len(tokens) == 1:
                    is_single_token_request = True
            else: 
                addresses_str = tokens
                is_single_token_request = True
                
            url = f"{self.details_endpoint}/{addresses_str}"
            logger.debug(f"Fetching token pair details: {url} (Single token request: {is_single_token_request})")
            data = await self._make_request(url)
            
            # Log the raw response for debugging, especially for problematic tokens
            logger.debug(f"Raw response from DexScreener for {addresses_str}: {data}")

            if isinstance(data, dict):
                if "pairs" in data and isinstance(data["pairs"], list):
                    # Standard response, return as is
                    if not data["pairs"]:
                        logger.debug(f"DexScreener returned an empty 'pairs' list for {addresses_str}. Full response: {data}")
                    return data
                elif "pair" in data and isinstance(data["pair"], dict):
                    # Single pair object returned, wrap it
                    logger.debug("Received single 'pair' object, wrapping in list.")
                    return {"pairs": [data["pair"]]}
                else:
                    # Unexpected dict format
                    logger.warning(f"Unexpected dict format from {url} (no 'pairs' or 'pair' key found, or 'pairs' not a list). Full response: {data}")
                    return {"pairs": []}
            elif isinstance(data, list):
                # API returned a list directly. This might happen for single token queries sometimes.
                logger.warning(f"Received a list directly from {url} for {addresses_str}, expected a dict. Wrapping list in {{'pairs': ...}} structure.")
                # If it was a single token request and we got a list, it should ideally contain one item.
                # TokenScanner._fetch_detailed_token_data_map expects the value for a single mint to be the dict itself, not a list.
                # However, this method's contract is to return {'pairs': [...]}.
                # The scanner needs to handle if the value for a mint in its resulting map is a list or a dict.
                # For now, just ensure this method returns {'pairs': data}
                return {"pairs": data}
            else:
                # Unexpected response type
                logger.error(f"Unexpected response type from {url}: {type(data)}")
                return {"pairs": []}

        except Exception as e:
            logger.error(f"Error fetching token details for {tokens}: {e}", exc_info=True)
            return {"pairs": []}
            
    async def get_pairs(self, chain_id: str = "solana") -> List[Dict]:
        """(Placeholder/Example) Might fetch pairs differently if needed."""
        # This method might be redundant if get_token_details covers pair fetching
        logger.warning("get_pairs method might be redundant, consider using get_token_details.")
        # Example implementation if a different endpoint exists:
        # url = f"{self.base_url}/dex/pairs/{chain_id}" 
        # try:
        #     data = await self._make_request(url)
        #     return data.get('pairs', []) if isinstance(data, dict) else []
        # except Exception as e:
        #     logger.error(f"Error in get_pairs: {e}")
        #     return []
        return [] # Default empty list 