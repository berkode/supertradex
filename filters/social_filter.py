"""
Social media filter module for analyzing token social presence.
"""

import logging
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from config.settings import Settings
from .twitter_check import TwitterCheck

logger = logging.getLogger(__name__)

class SocialFilter:
    """Filter for analyzing social media presence of tokens, primarily Twitter."""
    
    def __init__(self, settings: Settings, twitter_check: Optional[TwitterCheck] = None):
        """
        Initialize the social filter.
        
        Args:
            settings: Application settings
            twitter_check: Instance of TwitterCheck for API calls.
        """
        self.settings = settings
        self.twitter_check = twitter_check
        if not self.twitter_check:
            logger.warning("SocialFilter initialized WITHOUT TwitterCheck instance. Twitter checks will be skipped.")
        else:
            logger.info("SocialFilter initialized with TwitterCheck instance.")
        
    async def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a token's Twitter presence based on links in token_data.
        Validates link type before calling the Twitter API.
        
        Args:
            token_data: Token data dictionary, expected to have 'mint' and 'links' keys.
            
        Returns:
            A dictionary containing the Twitter analysis result.
            Keys include: handle, exists, error, followers, blue_verified, created_at,
                          account_age_days, description, mint_announced.
        """
        mint = token_data.get('mint', 'UNKNOWN_MINT')
        default_error_result = {
            "handle": None, "exists": False, "error": "An unknown error occurred",
            "followers": None, "blue_verified": None, "created_at": None,
            "account_age_days": None, "description": None, "mint_announced": None
        }

        if not self.twitter_check:
            logger.debug(f"Skipping Twitter check for {mint}: TwitterCheck not available.")
            default_error_result["error"] = "Twitter check not configured"
            return default_error_result

        try:
            # Extract Twitter link from DexScreener data
            twitter_link = next((link.get('url') for link in token_data.get('links', [])
                                 if link.get('type') == 'twitter' and isinstance(link.get('url'), str)), None)

            if not twitter_link:
                logger.debug(f"No Twitter link found for mint {mint}. Skipping Twitter check.")
                default_error_result["error"] = "No Twitter link found"
                return default_error_result

            # Validate URL type - skip search and status links
            parsed_url = urlparse(twitter_link)
            path = parsed_url.path.lower()

            if path.startswith('/search') or '/status/' in path:
                logger.debug(f"Skipping invalid Twitter URL type (search/status) for {mint}: {twitter_link}")
                default_error_result["error"] = f"Invalid Twitter URL type (search/status): {twitter_link}"
                return default_error_result

            # If link looks valid, proceed with verification
            logger.debug(f"Attempting Twitter verification for {mint} using link: {twitter_link}")
            twitter_analysis_result = await self.twitter_check.verify_twitter_account(twitter_link, mint)

            # Log the result from TwitterCheck
            logger.info(f"SocialFilter Twitter result for {mint}: Exists={twitter_analysis_result.get('exists')}, Handle={twitter_analysis_result.get('handle')}, Error='{twitter_analysis_result.get('error')}'")
            return twitter_analysis_result
            
        except Exception as e:
            logger.error(f"Error analyzing token {mint} social presence: {e}", exc_info=True)
            default_error_result["error"] = f"Internal filter error: {str(e)}"
            return default_error_result

    async def aclose(self):
        """Perform any cleanup if necessary."""
        logger.info("SocialFilter closed.")
        # If twitter_check needs closing, FilterManager should handle it as it was passed in.

    # Alias for compatibility with FilterManager check loop if needed
    async def check(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.analyze_token(token_data) 