import os
import time
import random
import logging
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from config.settings import Settings
from utils.logger import get_logger

# Get logger for this module
logger = get_logger(__name__)

class SolanaTrackerAPI:
    """Client for interacting with the SolanaTracker API."""
    
    def __init__(self, settings: Settings, proxy_manager=None, http_client=None):
        """
        Initialize SolanaTracker API client.
        
        Args:
            settings: The application settings object.
            proxy_manager: Proxy manager instance (optional)
            http_client: HTTP client session (optional)
        """
        self.settings = settings
        self.api_key = self.settings.SOLANATRACKER_API_KEY
        self.api_url = self.settings.SOLANATRACKER_API_URL
        self.proxy_manager = proxy_manager
        self.http_client = http_client
        self.max_retries = self.settings.API_MAX_RETRIES
        self.base_delay = self.settings.BASE_DELAY
        self.max_delay = 30
        self.timeout = aiohttp.ClientTimeout(total=self.settings.HTTP_TIMEOUT)
        
        logger.info(f"SolanaTrackerAPI initialized with URL: {self.api_url}")
    
    async def initialize(self) -> bool:
        """
        Initialize the SolanaTrackerAPI.
        
        Returns:
            bool: True if initialization is successful, False otherwise.
        """
        try:
            logger.info("Initializing SolanaTrackerAPI")
            
            # Check if we have a valid API key
            if not self.api_key or self.api_key == "DEMO_KEY" or self.api_key == "your_solanatracker_api_key":
                logger.warning("No valid API key for SolanaTrackerAPI")
                # Still return True to allow application to continue
                return True
                
            # Initialization successful
            logger.info("SolanaTrackerAPI initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing SolanaTrackerAPI: {e}")
            # Still return True to allow application to continue
            return True
            
    async def close(self):
        """Release the reference to the shared HTTP client."""
        # Do not close the client here, it's managed externally (e.g., in DataPackage)
        if self.http_client:
             logger.debug("Releasing shared HTTP client reference in SolanaTrackerAPI")
             self.http_client = None
                
    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create a client session."""
        if not self.http_client:
            self.http_client = aiohttp.ClientSession(timeout=self.timeout)
        return self.http_client
        
    async def get_trending_tokens(self) -> List[Dict[str, Any]]:
        """
        Get trending tokens from SolanaTracker API with improved rate limiting and retries.
        
        Returns:
            List of trending token data dictionaries
        """
        try:
            # Add initial delay between requests
            await asyncio.sleep(2)
            
            headers = {
                'x-api-key': self.api_key,
                'Accept': 'application/json'
            }
            
            for attempt in range(self.max_retries):
                try:
                    # Get proxy for this request
                    proxy = self.proxy_manager.get_proxy_dict()
                    
                    # Add exponential backoff delay between requests
                    if attempt > 0:
                        wait_time = min(
                            self.base_delay * (2 ** attempt) + random.uniform(0, 2),
                            self.max_delay
                        )
                        self.logger.info(f"Waiting {wait_time:.1f} seconds before retry {attempt + 1}")
                        await asyncio.sleep(wait_time)
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{self.api_url}/tokens/trending",
                            headers=headers,
                            proxy=proxy['https'] if proxy else None,
                            timeout=self.timeout
                        ) as response:
                            if response.status == 429:  # Rate limit hit
                                if proxy:
                                    self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                                if attempt < self.max_retries - 1:
                                    self.logger.warning(
                                        f"Rate limit hit, "
                                        f"attempt {attempt + 1}/{self.max_retries}"
                                    )
                                    continue
                                else:
                                    self.logger.error("Max retries reached for SolanaTracker API")
                                    return []
                            
                            response.raise_for_status()
                            data = await response.json()
                            
                            # Check for API errors
                            if 'error' in data:
                                self.logger.warning(f"SolanaTracker API returned error: {data['error']}")
                                if attempt < self.max_retries - 1:
                                    continue
                                else:
                                    return []
                            
                            # Ensure data is a list of dictionaries
                            if isinstance(data, list) and all(isinstance(token, dict) for token in data):
                                return data
                            else:
                                self.logger.warning("SolanaTracker unexpected data format received")
                                return []
                        
                except asyncio.TimeoutError:
                    if proxy:
                        self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                    self.logger.warning(f"Timeout on attempt {attempt + 1}")
                    if attempt < self.max_retries - 1:
                        continue
                    else:
                        self.logger.error("Max retries reached due to timeouts")
                        return []
                    
                except aiohttp.ClientError as e:
                    if proxy:
                        self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                    if attempt < self.max_retries - 1:
                        self.logger.warning(
                            f"Request failed, "
                            f"attempt {attempt + 1}/{self.max_retries}: {e}"
                        )
                        continue
                    else:
                        self.logger.error(f"Failed to get SolanaTracker data after {self.max_retries} attempts: {e}")
                        return []
                    
        except Exception as e:
            self.logger.error(f"Unexpected error in SolanaTracker data fetch: {e}", exc_info=True)
            return []
            
        # If we get here, return an empty list as a fallback
        return []
            
    async def get_token_data(self, token_mint: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed token data from SolanaTracker API.
        
        Args:
            token_mint: Token mint address
            
        Returns:
            Token data dictionary or None if failed
        """
        try:
            # Check if we have a valid API key
            if not self.api_key or self.api_key == "DEMO_KEY" or self.api_key == "your_solanatracker_api_key":
                self.logger.warning(f"No valid API key for SolanaTrackerAPI. Dropping token {token_mint}.")
                return None
                
            # Add initial delay between requests
            await asyncio.sleep(2)
            
            headers = {
                'x-api-key': self.api_key,
                'Accept': 'application/json'
            }
            
            for attempt in range(self.max_retries):
                try:
                    # Get proxy for this request
                    proxy = self.proxy_manager.get_proxy_dict()
                    
                    # Add exponential backoff delay between requests
                    if attempt > 0:
                        wait_time = min(
                            self.base_delay * (2 ** attempt) + random.uniform(0, 2),
                            self.max_delay
                        )
                        self.logger.info(f"Waiting {wait_time:.1f} seconds before retry {attempt + 1} for {token_mint}")
                        await asyncio.sleep(wait_time)
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{self.api_url}/tokens/{token_mint}",
                            headers=headers,
                            proxy=proxy['https'] if proxy else None,
                            timeout=self.timeout
                        ) as response:
                            if response.status == 401:  # Unauthorized
                                self.logger.error(f"API key unauthorized for SolanaTracker API. Dropping token {token_mint}.")
                                return None
                                
                            elif response.status == 429:  # Rate limit hit
                                if proxy:
                                    self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                                if attempt < self.max_retries - 1:
                                    self.logger.warning(
                                        f"Rate limit hit for {token_mint}, "
                                        f"attempt {attempt + 1}/{self.max_retries}"
                                    )
                                    continue
                                else:
                                    self.logger.error(f"Max retries reached for SolanaTracker API for {token_mint}. Dropping token.")
                                    return None
                            
                            try:
                                response.raise_for_status()
                                data = await response.json()
                                
                                # Check for API errors
                                if 'error' in data:
                                    self.logger.warning(f"SolanaTracker API returned error for {token_mint}: {data['error']}")
                                    if attempt < self.max_retries - 1:
                                        continue
                                    else:
                                        self.logger.error(f"SolanaTracker API returned error after retries. Dropping token {token_mint}.")
                                        return None
                                
                                # Add missing fields that may cause issues in data processing
                                if 'buysCount' not in data:
                                    data['buysCount'] = 0
                                if 'sellsCount' not in data:
                                    data['sellsCount'] = 0
                                
                                return data
                            except aiohttp.ClientResponseError:
                                if attempt < self.max_retries - 1:
                                    self.logger.warning(
                                        f"Request failed with status {response.status} for {token_mint}, "
                                        f"attempt {attempt + 1}/{self.max_retries}"
                                    )
                                    continue
                                else:
                                    self.logger.error(f"Failed to get SolanaTracker data after {self.max_retries} attempts for {token_mint}. Dropping token.")
                                    return None
                        
                except asyncio.TimeoutError:
                    if proxy:
                        self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                    self.logger.warning(f"Timeout on attempt {attempt + 1} for {token_mint}")
                    if attempt < self.max_retries - 1:
                        continue
                    else:
                        self.logger.error(f"Max retries reached due to timeouts for {token_mint}. Dropping token.")
                        return None
                    
                except aiohttp.ClientError as e:
                    if proxy:
                        self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                    if attempt < self.max_retries - 1:
                        self.logger.warning(
                            f"Request failed for {token_mint}, "
                            f"attempt {attempt + 1}/{self.max_retries}: {e}"
                        )
                        continue
                    else:
                        self.logger.error(f"Failed to get SolanaTracker data after {self.max_retries} attempts for {token_mint}: {e}. Dropping token.")
                        return None
                    
        except Exception as e:
            self.logger.error(f"Unexpected error in SolanaTracker data fetch for {token_mint}: {e}. Dropping token.", exc_info=True)
            return None
    
    def process_token_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process raw token data from SolanaTracker API.
        
        Args:
            data: Raw token data from API
            
        Returns:
            Processed token data dictionary
        """
        try:
            token_data = data['token']
            pools_data = data['pools'][0]
            txns_data = pools_data['txns']
            events_data = data['events']
            risk_data = data['risk']
            buysCount_data = data['buysCount']
            sellsCount_data = data['sellsCount']
            
            # Extract token information
            mint = token_data['mint']
            symbol = token_data['symbol']
            twitter = token_data.get('twitter', '')
            creator_site = token_data.get('website', '')
            has_file_metadata = token_data['hasFileMetaData']
            
            # Extract price and market data
            price = pools_data['price']['usd']
            market_cap_usd = pools_data['marketCap']['usd']
            liquidity_usd = pools_data['liquidity']['usd']
            txns_volume = txns_data['volume']
            buysCount = buysCount_data
            txns_buys = txns_data['buys']
            sellsCount = sellsCount_data
            txns_sells = txns_data['sells']
            lpburn = pools_data['lpBurn']
            
            # Extract price changes
            price_change_1m = round(events_data.get('1m', {}).get('priceChangePercentage', 0) or 0, 2)
            price_change_5m = round(events_data.get('5m', {}).get('priceChangePercentage', 0) or 0, 2)
            price_change_1h = round(events_data.get('1h', {}).get('priceChangePercentage', 0) or 0, 2)
            price_change_24h = round(events_data.get('24h', {}).get('priceChangePercentage', 0) or 0, 2)
            
            # Extract risk data
            rugged = risk_data['rugged']
            risk_score = risk_data['score']
            total_risk_score = sum(risk['score'] for risk in risk_data['risks'])
            jupiter_verified = risk_data.get('jupiterVerified', False)
            
            return {
                'mint': mint,
                'symbol': symbol,
                'twitter': twitter,
                'creator_site': creator_site,
                'has_file_metadata': has_file_metadata,
                'price': price,
                'market_cap_usd': market_cap_usd,
                'liquidity_usd': liquidity_usd,
                'txns_volume': txns_volume,
                'buysCount': buysCount,
                'txns_buys': txns_buys,
                'sellsCount': sellsCount,
                'txns_sells': txns_sells,
                'lpburn': lpburn,
                'price_change_1m': price_change_1m,
                'price_change_5m': price_change_5m,
                'price_change_1h': price_change_1h,
                'price_change_24h': price_change_24h,
                'rugged': rugged,
                'risk_score': risk_score,
                'total_risk_score': total_risk_score,
                'jupiter_verified': jupiter_verified
            }
            
        except Exception as e:
            self.logger.error(f"Error processing SolanaTracker data: {e}", exc_info=True)
            return {}
            
    def is_token_valid(self, data: Dict[str, Any]) -> bool:
        """
        Check if token passes SolanaTracker validation criteria.
        
        Args:
            data: Processed token data
            
        Returns:
            True if token passes validation, False otherwise
        """
        return (
            data.get('lpburn', 0) >= 90 and
            not data.get('rugged', False) and
            data.get('risk_score', 0) <= 5
        ) 

    async def get_token_holders(self, token_mint: str) -> Dict[str, Any]:
        """
        Get token holder data from SolanaTracker API.
        
        Args:
            token_mint: Token mint address
            
        Returns:
            Dictionary containing holder data
        """
        try:
            # Check if we have a valid API key
            if not self.api_key or self.api_key == "DEMO_KEY" or self.api_key == "your_solanatracker_api_key":
                self.logger.warning(f"No valid API key for SolanaTrackerAPI. Dropping token {token_mint}.")
                return {'holders': 0}
                
            # Add initial delay between requests
            await asyncio.sleep(2)
            
            headers = {
                'x-api-key': self.api_key,
                'Accept': 'application/json'
            }
            
            for attempt in range(self.max_retries):
                try:
                    # Get proxy for this request
                    proxy = self.proxy_manager.get_proxy_dict() if self.proxy_manager else None
                    
                    # Add exponential backoff delay between requests
                    if attempt > 0:
                        wait_time = min(
                            self.base_delay * (2 ** attempt) + random.uniform(0, 2),
                            self.max_delay
                        )
                        logger.info(f"Waiting {wait_time:.1f} seconds before retry {attempt + 1} for {token_mint}")
                        await asyncio.sleep(wait_time)
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{self.api_url}/tokens/{token_mint}/holders",
                            headers=headers,
                            proxy=proxy['https'] if proxy else None,
                            timeout=self.timeout
                        ) as response:
                            if response.status == 401:  # Unauthorized
                                logger.error(f"API key unauthorized for SolanaTracker API. Dropping token {token_mint}.")
                                return {'holders': 0}
                                
                            elif response.status == 429:  # Rate limit hit
                                if proxy and self.proxy_manager:
                                    self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                                if attempt < self.max_retries - 1:
                                    logger.warning(
                                        f"Rate limit hit for {token_mint}, "
                                        f"attempt {attempt + 1}/{self.max_retries}"
                                    )
                                    continue
                                else:
                                    logger.error(f"Max retries reached for SolanaTracker API for {token_mint}. Dropping token.")
                                    return {'holders': 0}
                            
                            try:
                                response.raise_for_status()
                                data = await response.json()
                                
                                # Check for API errors
                                if 'error' in data:
                                    logger.warning(f"SolanaTracker API returned error for {token_mint}: {data['error']}")
                                    if attempt < self.max_retries - 1:
                                        continue
                                    else:
                                        logger.error(f"SolanaTracker API returned error after retries. Dropping token {token_mint}.")
                                        return {'holders': 0}
                                
                                # Extract holder count from response
                                holder_count = data.get('totalHolders', 0)
                                return {'holders': holder_count}
                                
                            except aiohttp.ClientResponseError as e:
                                if proxy and self.proxy_manager:
                                    self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                                if attempt < self.max_retries - 1:
                                    logger.warning(f"Response error for {token_mint}, attempt {attempt + 1}: {e}")
                                    continue
                                else:
                                    logger.error(f"Failed to get holder data for {token_mint} after {self.max_retries} attempts: {e}")
                                    return {'holders': 0}
                                    
                except asyncio.TimeoutError:
                    if proxy and self.proxy_manager:
                        self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                    logger.warning(f"Timeout on attempt {attempt + 1} for {token_mint}")
                    if attempt < self.max_retries - 1:
                        continue
                    else:
                        logger.error(f"Max retries reached due to timeouts for {token_mint}")
                        return {'holders': 0}
                        
                except aiohttp.ClientError as e:
                    if proxy and self.proxy_manager:
                        self.proxy_manager.mark_proxy_failure(self.proxy_manager.current_proxy)
                    if attempt < self.max_retries - 1:
                        logger.warning(f"Request failed for {token_mint}, attempt {attempt + 1}: {e}")
                        continue
                    else:
                        logger.error(f"Failed to get holder data for {token_mint} after {self.max_retries} attempts: {e}")
                        return {'holders': 0}
                        
        except Exception as e:
            logger.error(f"Unexpected error getting holder data for {token_mint}: {e}", exc_info=True)
            return {'holders': 0}
            
        # If we get here, return zero holders as a fallback
        return {'holders': 0} 

    async def close(self):
        """Closes the aiohttp client session."""
        if self.http_client and not self.http_client.is_closed:
            await self.http_client.aclose()
            self.logger.info("SolanaTrackerAPI HTTP client closed.")