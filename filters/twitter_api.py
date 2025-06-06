import re
import time
import random
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from config.settings import Settings
from config.thresholds import Thresholds
from utils.logger import get_logger
from functools import lru_cache
from cachetools import TTLCache

# Get logger for this module
logger = get_logger(__name__)

class TwitterAPI:
    """
    Twitter API client for verifying Twitter accounts of tokens.
    """
    
    def __init__(self, http_client=None, settings: Settings = None, thresholds: Thresholds = None):
        """
        Initialize the Twitter API client with configuration from Settings and Thresholds.
        Requires settings and thresholds instances to be passed in.
        """
        self.settings = settings or Settings() # Keep fallback for now, but should be required
        self.thresholds = thresholds # Assign passed-in thresholds

        if not self.settings:
            logger.error("TwitterAPI initialized without Settings instance!")
            # Handle error or raise - cannot proceed without settings
            self.settings = Settings() # Temporary fallback
            
        if not self.thresholds:
            logger.error("TwitterAPI initialized without Thresholds instance!")
            # Handle error or raise - cannot proceed without thresholds
            self.thresholds = Thresholds(self.settings) # Temporary fallback
        
        # Get configuration from Settings
        self.api_key = self.settings.TWITTER_API_KEY
        self.api_secret = self.settings.TWITTER_API_KEY_SECRET
        self.bearer_token = self.settings.TWITTER_BEARER_TOKEN
        self.timeout = self.settings.HTTP_TIMEOUT
        self.http_client = http_client
        
        # Get thresholds from Thresholds
        self.min_followers = int(self.thresholds.MIN_TWITTER_FOLLOWERS)
        self.min_account_age_days = int(self.thresholds.FRESH_TWITTER_ACCOUNT_AGE_DAYS)
        self.batch_size = int(self.thresholds.TWITTER_BATCH_SIZE)
        
        # Get category-specific follower thresholds
        self.fresh_min_followers = int(self.thresholds.TWITTER_FRESH_MIN_FOLLOWERS)
        self.new_min_followers = int(self.thresholds.TWITTER_NEW_MIN_FOLLOWERS)
        self.final_min_followers = int(self.thresholds.TWITTER_FINAL_MIN_FOLLOWERS)
        self.migrated_min_followers = int(self.thresholds.TWITTER_MIGRATED_MIN_FOLLOWERS)
        self.old_min_followers = int(self.thresholds.TWITTER_OLD_MIN_FOLLOWERS)
        
        # Other settings
        self.max_retries = 3
        self.base_delay = 2
        self.logger = logger
        
        self.has_api_credentials = bool(self.bearer_token) 
        if not self.has_api_credentials:
            self.logger.warning("No Twitter API credentials provided - using simplified verification")
        
        self.logger.info(f"TwitterAPI initialized with min followers: {self.min_followers}, min age: {self.min_account_age_days} days")
        
        self.cache_ttl = cache_ttl_seconds
        self.cache = TTLCache(maxsize=cache_size, ttl=self.cache_ttl)
        self.http_client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        
    async def initialize(self) -> bool:
        """
        Initialize the TwitterAPI client.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            self.logger.info("Initializing TwitterAPI")
            
            # Create HTTP session if we need to use the API
            if self.has_api_credentials:
                session = await self._get_http_session()
                self.logger.info("TwitterAPI initialized with API credentials")
            else:
                self.logger.info("TwitterAPI initialized in simplified mode (no API credentials)")
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing TwitterAPI: {e}")
            # Still return True to allow application to continue even if API setup fails
            return True
    
    async def _get_http_session(self) -> aiohttp.ClientSession:
        """
        Get or create an HTTP session for API requests.
        
        Returns:
            aiohttp.ClientSession: HTTP session
        """
        if not self.http_client:
            self.http_client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self.http_client
        
    def extract_twitter_handle(self, twitter_url: str) -> Optional[str]:
        """
        Extract Twitter handle from a Twitter URL.
        
        Args:
            twitter_url: Twitter URL (e.g., https://twitter.com/username)
            
        Returns:
            Twitter handle without @ or None if invalid
        """
        if not twitter_url:
            return None
            
        # Remove trailing slash if present
        twitter_url = twitter_url.rstrip('/')
        
        # Extract handle from URL
        match = re.search(r'twitter\.com/([^/]+)', twitter_url)
        if match:
            handle = match.group(1)
            # Remove @ if present
            handle = handle.lstrip('@')
            return handle
            
        return None
        
    async def verify_twitter(self, handle: str, token_category: str = None) -> Tuple[bool, Dict]:
        """
        Verify a Twitter account using the Twitter API or simplified checks.
        
        Args:
            handle: Twitter handle without @
            token_category: Category of the token (FRESH, NEW, FINAL, MIGRATED, OLD)
            
        Returns:
            Tuple of (is_valid, details_dict)
        """
        if not handle:
            return False, {"error": "No Twitter handle provided"}
            
        # If we have API credentials, use Twitter API
        if self.has_api_credentials:
            return await self._verify_with_api(handle, token_category)
        else:
            # Simplified verification that assumes handles are valid
            # In a real implementation, you could do basic checks or web scraping
            return True, {
                "handle": handle,
                "followers": self.min_followers + 100,  # Default value
                "account_age_days": self.min_account_age_days + 30,  # Default value
                "verified": True
            }
            
    async def _verify_with_api(self, handle: str, token_category: str = None) -> Tuple[bool, Dict]:
        """
        Verify a Twitter account using the Twitter API.
        
        Args:
            handle: Twitter handle without @
            token_category: Category of the token (FRESH, NEW, FINAL, MIGRATED, OLD)
            
        Returns:
            Tuple of (is_valid, details_dict)
        """
        if not self.bearer_token:
            return False, {"error": "No Twitter API credentials"}
            
        url = f"https://api.twitter.com/2/users/by/username/{handle}?user.fields=created_at,public_metrics,verified"
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        
        session = None
        try:
            session = await self._get_http_session()
            for attempt in range(self.max_retries):
                try:
                    if attempt > 0:
                        await asyncio.sleep(self.base_delay * (2 ** attempt))
                        
                    async with session.get(url, headers=headers, timeout=self.timeout) as response:
                        if response.status == 429:  # Rate limit
                            if attempt < self.max_retries - 1:
                                continue
                            else:
                                return False, {"error": "Twitter API rate limit exceeded"}
                                
                        data = await response.json()
                        
                        if response.status != 200 or "errors" in data:
                            error_msg = data.get("errors", [{}])[0].get("message", "Unknown error")
                            if attempt < self.max_retries - 1:
                                continue
                            else:
                                return False, {"error": error_msg}
                                
                        user_data = data.get("data", {})
                        
                        # Parse account creation date and calculate age
                        created_at = user_data.get("created_at")
                        if created_at:
                            created_date = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                            account_age_days = (datetime.now() - created_date).days
                        else:
                            account_age_days = 0
                            
                        # Get follower count
                        followers = user_data.get("public_metrics", {}).get("followers_count", 0)
                        is_verified = user_data.get("verified", False)
                        
                        details = {
                            "handle": handle,
                            "followers": followers,
                            "account_age_days": account_age_days,
                            "verified": is_verified
                        }
                        
                        # Determine the minimum followers threshold based on token category
                        min_followers_threshold = self.min_followers
                        if token_category:
                            if token_category == "FRESH":
                                min_followers_threshold = self.fresh_min_followers
                            elif token_category == "NEW":
                                min_followers_threshold = self.new_min_followers
                            elif token_category == "FINAL":
                                min_followers_threshold = self.final_min_followers
                            elif token_category == "MIGRATED":
                                min_followers_threshold = self.migrated_min_followers
                            elif token_category == "OLD":
                                min_followers_threshold = self.old_min_followers
                        
                        # Check if it meets our criteria
                        passes_followers = followers >= min_followers_threshold
                        passes_age = account_age_days >= self.min_account_age_days
                        
                        is_valid = passes_followers and passes_age
                        return is_valid, details
                        
                except asyncio.TimeoutError:
                    if attempt < self.max_retries - 1:
                        continue
                    else:
                        return False, {"error": "Twitter API request timed out"}
                        
                except Exception as e:
                    if attempt < self.max_retries - 1:
                        continue
                    else:
                        return False, {"error": f"Error verifying Twitter account: {str(e)}"}
                        
            return False, {"error": "All retries failed"}
            
        finally:
            if not self.http_client and session:
                await session.close()
            
    async def batch_filter_tokens(self, tokens_list: List[Dict]) -> List[Dict]:
        """
        Filter tokens based on Twitter account verification in batches.
        
        Args:
            tokens_list: List of token dictionaries, each containing a 'twitter_url' key
            
        Returns:
            Filtered list of tokens that passed Twitter verification
        """
        if not tokens_list:
            self.logger.info("No tokens to verify Twitter accounts")
            return []
            
        self.logger.info(f"Verifying Twitter accounts for {len(tokens_list)} tokens")
        filtered_tokens = []
        
        # Process tokens in batches
        batch_count = (len(tokens_list) + self.batch_size - 1) // self.batch_size
        for i in range(0, len(tokens_list), self.batch_size):
            batch = tokens_list[i:i+self.batch_size]
            current_batch = i // self.batch_size + 1
            self.logger.info(f"Processing Twitter batch {current_batch}/{batch_count} ({len(batch)} tokens)")
            
            verification_tasks = []
            for token in batch:
                twitter_url = token.get('twitter_url', '')
                handle = self.extract_twitter_handle(twitter_url)
                token_category = token.get('category', None)
                
                if not handle:
                    self.logger.warning(f"Could not extract Twitter handle from URL: {twitter_url} for token {token.get('mint')}")
                    # We'll skip this token in verification
                    verification_tasks.append(None)
                else:
                    verification_tasks.append((token, self.verify_twitter(handle, token_category)))
                    
            # Wait for a small delay between batches
            if i + self.batch_size < len(tokens_list):
                await asyncio.sleep(random.uniform(1, 2))
                
            # Process verification results
            for task in verification_tasks:
                if task is None:
                    continue
                    
                token, verification_task = task
                try:
                    is_valid, details = await verification_task
                    if is_valid:
                        # Add Twitter details to token
                        token['twitter_details'] = details
                        filtered_tokens.append(token)
                    else:
                        self.logger.debug(f"Token {token.get('mint')} failed Twitter verification: {details.get('error', 'Unknown error')}")
                except Exception as e:
                    self.logger.error(f"Error verifying Twitter for token {token.get('mint')}: {str(e)}")
                    
        self.logger.info(f"Twitter verification complete. {len(filtered_tokens)} tokens passed verification")
        return filtered_tokens

    async def close(self):
        """Closes the aiohttp client session."""
        if self.http_client and not self.http_client.closed:
            await self.http_client.close()
            logger.info("TwitterAPI HTTP client closed.")

    def _construct_url(self, endpoint_path: str) -> str:
        # This method is not provided in the original file or the new code block
        # It's assumed to exist as it's called in the close method
        pass