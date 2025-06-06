import os
import logging
import time
import random
import aiohttp
import asyncio
import json
from typing import Dict, Any, Optional, List
from config.settings import Settings
from utils.logger import get_logger
from utils.proxy_manager import ProxyManager
import httpx

# Get logger for this module
logger = logging.getLogger(__name__)

class RugcheckAPI:
    """API client for Rugcheck.xyz"""

    BASE_URL = "https://api.rugcheck.xyz/v1"

    def __init__(self, settings: Settings, proxy_manager: Optional[ProxyManager] = None):
        """Initialize the RugcheckAPI client."""
        self.settings = settings
        self.api_url = settings.RUGCHECK_API_URL
        self.logger = logging.getLogger("filters.rugcheck_api")
        self.semaphore = asyncio.Semaphore(settings.API_CONCURRENCY_LIMIT)
        self.api_available = False
        self.max_retries = settings.API_MAX_RETRIES
        self.retry_delay = settings.API_RETRY_DELAY
        self.proxy_manager = proxy_manager
        
        self.logger.info(f"RugcheckAPI concurrency limit set to: {self.semaphore._value}")
        
        self.session = None
        self._setup_logging()
        
        self.headers = {
            "User-Agent": "Supertradex/1.0"
        }
        self.client = httpx.AsyncClient(headers=self.headers, timeout=30.0)
        
    def _setup_logging(self):
        """Set up logging for the Rugcheck API client."""
        self.logger.info(f"Initializing RugcheckAPI with URL: {self.api_url}")
        
    async def initialize(self):
        """Initialize the aiohttp client session."""
        try:
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()
                self.logger.info("aiohttp ClientSession created for RugcheckAPI.")
            return True
        except Exception as e:
            self.logger.error(f"Error initializing RugcheckAPI session: {e}")
            return False
        
    async def close(self):
        """Closes the aiohttp client session and httpx client."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("RugcheckAPI aiohttp session closed.")
        if hasattr(self, 'client') and self.client and not self.client.is_closed:
            await self.client.aclose()
            logger.info("RugcheckAPI httpx client closed.")
            
    async def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None, data: Optional[Dict] = None, initial_backoff: float = 1.0) -> Optional[Dict]:
        """Makes an API request with proxy rotation and retry logic for 429 errors."""
        url = f"{self.BASE_URL}/{endpoint}"
        current_retry = 0
        backoff_delay = initial_backoff
        retries = self.max_retries # Use retries from settings

        while current_retry <= retries: # Use the configured max_retries
            proxy_url = None
            client_kwargs = {"params": params, "json": data}
            
            if self.proxy_manager:
                proxy_url = self.proxy_manager.get_proxy()
                if proxy_url:
                    proxies = {"http://": proxy_url, "https://": proxy_url}
                    client_kwargs["proxies"] = proxies
                    self.logger.debug(f"Using proxy: {proxy_url} for request to {url}")
                else:
                    self.logger.warning("Proxy manager enabled but no proxy available.")

            try:
                response = await self.client.request(method, url, **client_kwargs)
                
                # Handle Rate Limiting (429)
                if response.status_code == 429:
                    current_retry += 1
                    if current_retry > retries:
                         self.logger.error(f"Rugcheck API rate limit exceeded after {retries} retries on {endpoint}. Giving up.")
                         return None
                         
                    retry_after = response.headers.get("Retry-After")
                    wait_time = backoff_delay
                    if retry_after:
                        try:
                            wait_time = max(float(retry_after), backoff_delay) # Use header if available and longer
                        except ValueError:
                            self.logger.warning(f"Invalid Retry-After header value: {retry_after}. Using default backoff.")
                    
                    self.logger.warning(
                        f"Rate limited by Rugcheck API (Status 429) on {endpoint}. "
                        f"Retry {current_retry}/{retries} in {wait_time:.2f} seconds..."
                    )
                    await asyncio.sleep(wait_time)
                    backoff_delay *= 2 # Exponential backoff
                    if proxy_url:
                        self.proxy_manager.report_failure(proxy_url) # Report failure on rate limit to rotate proxy
                    continue # Go to next retry iteration

                # Handle other client/server errors
                response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx responses != 429
                            
                        # Success
                return response.json()
                        
            except httpx.HTTPStatusError as e:
                self.logger.error(f"HTTP error calling Rugcheck API {endpoint}: {e.response.status_code} - {e.response.text}")
                if proxy_url:
                    self.proxy_manager.report_failure(proxy_url) # Report failure on other HTTP errors too
                # Consider specific status code handling (e.g., 404 not found might not need retry)
                # For now, break loop on non-429 errors
                break 
            except httpx.RequestError as e:
                self.logger.error(f"Request error calling Rugcheck API {endpoint}: {e}")
                if proxy_url:
                    self.proxy_manager.report_failure(proxy_url)
                # Network errors might be retried, similar to rate limits
                current_retry += 1
                if current_retry > retries:
                    self.logger.error(f"Rugcheck API request failed after {retries} retries on {endpoint}. Giving up.")
                    break
                wait_time = backoff_delay
                self.logger.warning(
                    f"Request error on {endpoint}. "
                    f"Retry {current_retry}/{retries} in {wait_time:.2f} seconds..."
                )
                await asyncio.sleep(wait_time)
                backoff_delay *= 2
                continue # Continue to the next retry attempt
            except Exception as e: # Correctly aligned except block
                self.logger.error(f"Unexpected error calling Rugcheck API {endpoint}: {e}", exc_info=True)
                break # Break on unexpected errors
            
        return None # Return None if all retries fail or a non-retryable error occurs
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.logger.debug(f"Request headers: {headers}")
        return headers

    async def get_token_score(self, token_address: str) -> Optional[Dict]:
        """Get rugcheck score for a token.
        
        Args:
            token_address: Token mint address
            
        Returns:
            Dict containing score fields prefixed with 'rugcheck_' and other fields as-is
        """
        if not token_address:
            self.logger.warning("No token address provided")
            return None

        # Add base delay before making the request
        if self.settings.BASE_DELAY > 0:
            await asyncio.sleep(self.settings.BASE_DELAY)
            
        try:
            endpoint = f"tokens/{token_address}/report"
            # Use general API retry delay as initial backoff in _make_request
            result = await self._make_request("GET", endpoint, initial_backoff=self.retry_delay) 
            if result is None:
                # Signal that the request failed after retries
                self.logger.warning(f"API call failed for {token_address} after all retries.")
                return {"api_error": True}
            return result
                
        except Exception as e:
            self.logger.error(f"Error getting Rugcheck score for {token_address}: {str(e)}")
            return None

    # Implementation of get_scores_for_mints method
    async def get_scores_for_mints(self, mints: List[str]) -> Dict[str, Dict]:
        """Fetch rugcheck scores for a list of mint addresses concurrently, respecting semaphore limit."""

        if not mints:
            self.logger.warning("No mint addresses provided to get_scores_for_mints")
            return {}

        # Filter out potential non-Solana addresses (basic check)
        valid_solana_mints = [m for m in mints if m and not m.startswith('0x') and len(m) > 30] # Basic Solana address check
        skipped_count = len(mints) - len(valid_solana_mints)
        if skipped_count > 0:
             self.logger.warning(f"Skipped {skipped_count} potentially invalid/non-Solana addresses for RugCheck.")
             
        if not valid_solana_mints:
             self.logger.warning("No valid Solana mint addresses remaining after filtering for RugCheck.")
             return {}

        scores_map: Dict[str, Dict] = {}
        tasks = []

        # Helper coroutine to wrap the call with semaphore acquisition
        async def fetch_score_with_semaphore(mint):
            async with self.semaphore:
                # Add a small random delay *before* the call, if desired (helps spread load slightly)
                # await asyncio.sleep(random.uniform(0.1, 0.5)) 
                self.logger.debug(f"Acquired semaphore, fetching RugCheck score for mint: {mint}")
                result = await self.get_token_score(mint)
                self.logger.debug(f"Finished fetch for mint: {mint}")
                return mint, result # Return mint to associate result

        # Create tasks for all valid mints
        for mint in valid_solana_mints:
            tasks.append(fetch_score_with_semaphore(mint))

        self.logger.info(f"Fetching RugCheck scores concurrently for {len(tasks)} valid mints (limit: {self.semaphore._value})...")
        
        # Run tasks concurrently using gather
        # return_exceptions=True ensures that one failed task doesn't stop others
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_count = 0
        error_count = 0
        # Process results
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"Exception occurred during concurrent RugCheck fetch: {result}", exc_info=False) # Log exception info if needed: exc_info=result
                error_count += 1
            elif isinstance(result, tuple) and len(result) == 2:
                mint, score_data = result
                if isinstance(score_data, dict) and score_data: # Check if result is a non-empty dict
                    scores_map[mint] = score_data
                    processed_count += 1
                elif score_data is None:
                     self.logger.warning(f"No score data retrieved concurrently for mint {mint} (get_token_score returned None).")
                     # Optionally add error marker: scores_map[mint] = {'error': 'No data'}
                else: # API error flag etc.
                    self.logger.warning(f"Score data retrieved for mint {mint} indicates an API error or no data: {score_data}. Storing as is.")
                    scores_map[mint] = score_data # Store the error dict if present
                    # Consider incrementing error_count if score_data contains {'api_error': True}
                    if score_data.get("api_error"):
                         error_count += 1
                    else: # Count successfully processed even if API reported 'no data' without error
                         processed_count += 1
            else:
                 self.logger.error(f"Unexpected result format from asyncio.gather in get_scores_for_mints: {result}")
                 error_count += 1


        self.logger.info(f"RugCheck concurrent fetch complete. Successfully processed: {processed_count}, Errors/Exceptions: {error_count}, Total Mints Attempted: {len(valid_solana_mints)}.")
        return scores_map

    async def get_token_report(self, mint_address: str) -> Optional[Dict]:
        """Get the Rugcheck report for a specific token mint."""
        endpoint = f"tokens/{mint_address}/report"
        return await self._make_request("GET", endpoint)

    async def get_tokens_latest(self, limit: int = 100, offset: int = 0) -> Optional[Dict]:
        """Get the latest tokens listed on Rugcheck."""
        endpoint = "tokens/latest"
        params = {"limit": limit, "offset": offset}
        return await self._make_request("GET", endpoint, params=params) 