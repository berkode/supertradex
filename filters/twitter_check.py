import logging
import re
import time
import random
import asyncio
import twikit
import os
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, timezone
from config.settings import Settings
from config.thresholds import Thresholds
from utils.logger import get_logger
from random import randint
import pandas as pd
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

# Get logger for this module
logger = get_logger(__name__)

class TwitterCheck:
    """
    Twitter client for verifying Twitter accounts of tokens using Twikit.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(TwitterCheck, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, settings: Settings, thresholds: Thresholds):
        """Initialize TwitterCheck."""
        if not TwitterCheck._initialized:
            self.settings = settings
            self.logger = get_logger(__name__)
            self.thresholds = thresholds
            
            self.max_retries = self.settings.API_MAX_RETRIES 
            self.retry_delay = self.settings.API_RETRY_DELAY

            self.twikit_client = None
            # Define cookie path relative to the workspace root or use absolute path if needed
            # Assuming filters directory is at the root
            self.cookies_path = os.path.join('filters', 'twitter_cookies.json') 
            self.logged_in = False
            self.last_login_attempt = None
            self.login_lock = asyncio.Lock()
            
            self.follower_thresholds = {
                'FRESH': self.thresholds.get('FRESH_TWITTER_MIN_FOLLOWERS'),
                'NEW': self.thresholds.get('NEW_TWITTER_MIN_FOLLOWERS'),
                'FINAL': self.thresholds.get('FINAL_TWITTER_MIN_FOLLOWERS'),
                'MIGRATED': self.thresholds.get('MIGRATED_TWITTER_MIN_FOLLOWERS'),
                'OLD': self.thresholds.get('OLD_TWITTER_MIN_FOLLOWERS')
            }
            
            TwitterCheck._initialized = True
            self.logger.info(f"TwitterCheck initialized. Cookie path: {self.cookies_path}")
        
    async def initialize(self):
        """Initialize the Twikit client, handling cookie loading and login."""
        async with self.login_lock:
            if self.logged_in and self.twikit_client:
                self.logger.info("Twikit client already initialized and logged in.")
                return True

            self.logger.info("Initializing Twikit client...")
            self.twikit_client = twikit.Client(language='en-US')
            logged_in_via_cookie = False
            
            # 1. Try loading cookies
            if os.path.exists(self.cookies_path):
                try:
                    self.logger.info(f"Loading cookies from {self.cookies_path}...")
                    self.twikit_client.load_cookies(self.cookies_path)
                
                    # 2. Validate cookies by fetching configured user's profile
                    self.logger.info(f"Validating loaded cookies by fetching profile for user: {self.settings.TWITTER_USER}...")
                    await asyncio.sleep(random.uniform(0.1, 0.5)) # Small delay before validation call
                    validation_user = await self.twikit_client.get_user_by_screen_name(self.settings.TWITTER_USER)
                    
                    if validation_user and validation_user.id:
                        self.logger.info(f"Cookie validation successful (able to fetch profile for {self.settings.TWITTER_USER}).")
                        logged_in_via_cookie = True
                        self.logged_in = True
                    else:
                        # This case might not be strictly necessary if Unauthorized is caught, but good for robustness
                        self.logger.warning("Loaded cookies seem invalid (could not fetch configured user profile). Will attempt credential login.") 
                        # Clear invalid cookies (optional)
                        try: os.remove(self.cookies_path) 
                        except OSError as e: self.logger.error(f"Error removing invalid cookie file: {e}")
                            
                except twikit.errors.Unauthorized as e:
                    self.logger.warning(f"Cookie validation failed (Unauthorized fetching profile: {e}). Will attempt credential login.")
                    # Clear invalid cookies 
                    try: os.remove(self.cookies_path) 
                    except OSError as e: self.logger.error(f"Error removing invalid cookie file: {e}")

                except Exception as e:
                    # Catch other potential errors during cookie load/validation
                    self.logger.warning(f"Cookie validation failed (Error: {e}). Will attempt credential login.")
                    # Optionally remove cookies here too if the error suggests they are corrupt
                    # try: os.remove(self.cookies_path)
                    # except OSError as e: self.logger.error(f"Error removing cookie file: {e}")
            else:
                self.logger.info(f"Cookie file not found at {self.cookies_path}. Will attempt credential login.")

            # 3. Attempt credential login if cookies failed or didn't exist
            if not logged_in_via_cookie:
                username = self.settings.TWITTER_USER
                email = self.settings.TWITTER_EMAIL
                password_secret = self.settings.TWITTER_PASSWORD

                if not username or not email or not password_secret:
                    self.logger.error("Twitter username, email, or password not configured in settings for credential login.")
                    self.twikit_client = None
                    return False
                
                password = password_secret.get_secret_value()

                self.logger.info(f"Attempting credential login for user: {username}...")
                try:
                    await self.twikit_client.login(
                        auth_info_1=username,
                        auth_info_2=email,
                        password=password
                    )
                    self.logger.info("Credential login successful.")
                    self.logged_in = True
                    
                    # 4. Save cookies after successful credential login
                    self.logger.info(f"Saving cookies to {self.cookies_path}...")
                    try:
                        # Ensure directory exists
                        os.makedirs(os.path.dirname(self.cookies_path), exist_ok=True)
                        self.twikit_client.save_cookies(self.cookies_path)
                        self.logger.info("Cookies saved successfully.")
                    except Exception as e:
                        self.logger.error(f"Failed to save cookies: {e}")
                        
                except twikit.errors.BadRequest as e: # Catch potential login errors
                    self.logger.error(f"Twikit credential login failed (BadRequest): {e}")
                    self.twikit_client = None
                    self.logged_in = False
                    return False
                except Exception as e:
                    self.logger.error(f"Twikit credential login failed (Error): {e}", exc_info=True)
                    self.twikit_client = None
                    self.logged_in = False
                    return False
        
        # Final check
        if self.logged_in and self.twikit_client:
            self.logger.info("✅ Twikit client initialized and logged in successfully.")
            return True
        else:
            self.logger.error("❌ Failed to initialize Twikit client or log in.")
            return False
    
    def extract_twitter_handle(self, url):
        """Extract Twitter handle from various URL formats."""
        if not url:
            return None
            
        # Remove any whitespace
        url = url.strip()
        
        # Handle direct @username format
        if url.startswith('@'):
            return url[1:]
            
        # Handle twitter.com and x.com URLs
        patterns = [
            r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([^/]+)(?:\?.*)?$',
            r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/@?([^/]+)(?:\?.*)?$',
            r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/i/communities/([^/]+)(?:\?.*)?$'
        ]
        
        for pattern in patterns:
            self.logger.debug(f"Attempting pattern: {pattern} on URL: {url}") # Log pattern
            match = re.search(pattern, url)
            self.logger.debug(f"Match result: {match}") # Log match result
            # If a match is found with the current pattern, extract and check
        if match:
            handle = match.group(1)
            self.logger.debug(f"Potential handle extracted: '{handle}'") # Log extracted handle
            # Remove any query parameters just in case
            handle = handle.split('?')[0]
            # Basic check to avoid matching common path words
            is_valid_handle = handle.lower() not in ['home', 'explore', 'search', 'notifications', 'messages', 'settings', 'i', 'status', 'communities']
            self.logger.debug(f"Handle validity check ('{handle.lower()}' not in excluded list): {is_valid_handle}") # Log validity check
            if is_valid_handle:
                self.logger.debug(f"Valid handle '{handle}' found, returning.")
                return handle # Return the valid handle immediately
            else:
                self.logger.debug(f"Handle '{handle}' matched pattern but is excluded. Continuing to next pattern.")
            # If match was found but it was a common path word, continue to next pattern
        else:
            self.logger.debug("Pattern did not match.")
                
        # If no pattern matched and returned a valid handle after checking all patterns, return None
        self.logger.warning(f"Could not extract a valid handle from URL: {url} using patterns.") # Add log for failed extraction
        return None

    async def verify_twitter_account(self, twitter_url: str, mint_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetches Twitter account data and checks for mint announcement.
        Does NOT perform filtering based on thresholds anymore.
        Includes improved error handling for authentication.
        
        Args:
            twitter_url: The URL of the Twitter profile.
            mint_address: Optional mint address to check for announcement.
            
        Returns:
            A dictionary containing verification findings:
            { 
                'handle': str | None,
                'exists': bool,
                'error': str | None,
                'followers': int | None,
                'blue_verified': bool | None,
                'created_at': datetime | None,
                'account_age_days': int | None,
                'description': str | None,
                'mint_announced': bool | None # True if mint found, False if not found, None if mint_address not provided
            }
        """
        handle = None
        default_result = {
            'handle': None, 'exists': False, 'error': 'Unknown error', 
            'followers': None, 'blue_verified': None, 'created_at': None,
            'account_age_days': None, 'description': None, 'mint_announced': None
        }

        try:
            # Re-check client status and attempt re-initialization if needed
            # Basic check, might need more robust session validation
            if not self.twikit_client or not self.logged_in:
                self.logger.warning("Twikit client not available or not logged in. Attempting re-initialization.")
                if not await self.initialize():
                     default_result['error'] = "Client re-initialization failed"
                return default_result

            handle = self.extract_twitter_handle(twitter_url)
            if not handle:
                self.logger.warning(f"Could not extract handle from URL: {twitter_url}")
                default_result['error'] = "Invalid Twitter URL/Handle"
                return default_result
            
            default_result['handle'] = handle
            self.logger.debug(f"Verifying Twitter handle: @{handle} (Mint: {mint_address or 'N/A'})")

            try:
                # Fetch user data
                await asyncio.sleep(random.uniform(0.5, 1.5)) # Small random delay
                user = await self.twikit_client.get_user_by_screen_name(handle)
                
                if not user:
                    self.logger.warning(f"Twitter account @{handle} not found.")
                    default_result['error'] = "Account not found"
                    return default_result
                
                # Extract data (ensure user object is valid)
                followers_count = getattr(user, 'followers_count', None)
                is_blue_verified = getattr(user, 'is_blue_verified', None)
                created_at_dt = getattr(user, 'created_at_datetime', None)
                account_age_days = (datetime.now(timezone.utc) - created_at_dt).days if created_at_dt else None
                description = getattr(user, 'description', None)

                self.logger.debug(f"Metrics for @{handle}: Followers={followers_count}, Blue={is_blue_verified}, Age={account_age_days} days")

                mint_announced_status = None 
                if mint_address:
                    mint_announced_status = False
                    self.logger.debug(f"Checking for mint {mint_address} announcement by @{handle}")
                    # Check description
                    if mint_address in (description or ""):
                        self.logger.info(f"Mint {mint_address} found in description for @{handle}")
                        mint_announced_status = True
                    
                    # Check pinned tweet if not found yet
                    if not mint_announced_status and hasattr(user, 'pinned_tweet_ids') and user.pinned_tweet_ids:
                        try:
                            await asyncio.sleep(random.uniform(0.2, 0.8))
                            pinned_tweets = await self.twikit_client.get_tweets_by_ids(user.pinned_tweet_ids)
                            for tweet in pinned_tweets:
                                if mint_address in (getattr(tweet, 'text', None) or ""):
                                    self.logger.info(f"Mint {mint_address} found in pinned tweet for @{handle}")
                                    mint_announced_status = True
                                    break 
                        except Exception as pinned_err:
                             self.logger.warning(f"Could not fetch/check pinned tweets for @{handle}: {pinned_err}")
                                
                    # Check highlights if not found yet
                    if not mint_announced_status and hasattr(user, 'get_highlights_tweets'):
                         try:
                             await asyncio.sleep(random.uniform(0.2, 0.8))
                             highlights = await user.get_highlights_tweets(count=3) # Check a few highlights
                             for tweet in highlights:
                                 if mint_address in (getattr(tweet, 'text', None) or ""):
                                     self.logger.info(f"Mint {mint_address} found in highlights for @{handle}")
                                     mint_announced_status = True
                                     break
                         except Exception as highlight_err:
                             self.logger.warning(f"Could not fetch highlights for @{handle}: {highlight_err}")

                    if mint_announced_status:
                        self.logger.debug(f"Mint announcement check PASSED for @{handle}")
                    else:
                        self.logger.debug(f"Mint announcement check FAILED for @{handle} - Mint not found.")

                return {
                    'handle': handle,
                    'exists': True,
                    'error': None,
                    'followers': followers_count,
                    'blue_verified': is_blue_verified,
                    'created_at': created_at_dt,
                    'account_age_days': account_age_days,
                    'description': description,
                    'mint_announced': mint_announced_status 
                }

            # --- Specific Error Handling --- 
            except twikit.errors.TooManyRequests as e:
                try:
                    reset_time = int(e.response.headers.get('x-rate-limit-reset', 0))
                    current_time = int(datetime.now().timestamp())
                    wait_time = max(reset_time - current_time, 5) # Wait at least 5s
                    self.logger.warning(f"Twitter rate limit hit for @{handle}. Waiting {wait_time} seconds. (Reset timestamp: {reset_time})")
                    await asyncio.sleep(wait_time)
                    # Retry the call (could implement max retries here)
                    return await self.verify_twitter_account(twitter_url, mint_address) 
                except Exception as rate_limit_e:
                     self.logger.error(f"Error handling rate limit: {rate_limit_e}")
                     default_result['error'] = f"Rate limit hit, error handling failed: {rate_limit_e}"
                     return default_result
            
            except twikit.errors.UserNotFound:
                 self.logger.warning(f"Twitter account @{handle} not found via API.")
                 default_result['error'] = "Account not found (API)"
                 return default_result

            except twikit.errors.Forbidden as e:
                 self.logger.error(f"Twitter API Forbidden (403) error for @{handle}. Session likely invalid: {e}")
                 self.logged_in = False # Mark session as invalid
                 # Optionally try to remove cookies if they caused the issue
                 if os.path.exists(self.cookies_path):
                     try: 
                         os.remove(self.cookies_path)
                         self.logger.info(f"Removed potentially invalid cookie file ({self.cookies_path}) due to 403 error.")
                     except OSError as rm_err:
                         self.logger.error(f"Error removing cookie file {self.cookies_path} after 403: {rm_err}")
                 default_result['error'] = f"Verification error: status: 403, message: {e}"
                 return default_result
                 
            except twikit.errors.Unauthorized as e:
                 self.logger.error(f"Twitter API Unauthorized (401) error for @{handle}. Session invalid: {e}")
                 self.logged_in = False # Mark session as invalid
                 # Remove cookies
                 if os.path.exists(self.cookies_path):
                     try: os.remove(self.cookies_path)
                     except OSError as rm_err: self.logger.error(f"Error removing cookie file {self.cookies_path} after 401: {rm_err}")
                 default_result['error'] = f"Verification error: status: 401, message: {e}"
                 return default_result

            except Exception as e:
                self.logger.error(f"Unexpected error verifying Twitter @{handle}: {e}", exc_info=True)
                default_result['error'] = f"Unexpected verification error: {str(e)[:100]}"
                return default_result
                
        # Catch potential errors during the initial client check or handle extraction
        except Exception as outer_e:
            self.logger.error(f"Outer error during Twitter verification for URL {twitter_url}: {outer_e}", exc_info=True)
            default_result['error'] = f"Outer verification error: {str(outer_e)[:100]}"
            return default_result

    async def apply(self, token_data: dict) -> bool:
        # This method might need review based on how FilterManager calls filters
        # Assuming it's called by FilterManager which then adds the result 
        # to filter_results. This method might just return the analysis dict.
        
        # Example: If FilterManager expects analyze_token method
        # return await self.analyze_token(token_data) 
        
        # Placeholder based on original structure - NEEDS REVIEW
        twitter_url = token_data.get('twitter')
        mint = token_data.get('mint')
        if not twitter_url:
            return False # Or handle differently?
            
        analysis_result = await self.verify_twitter_account(twitter_url, mint)
        
        # Add result to token_data (assuming FilterManager doesn't do this)
        token_data['twitter_analysis'] = analysis_result 
        
        # Determine pass/fail based on the analysis
        # This filtering logic should ideally live in SocialFilter
        passed = False
        if analysis_result['exists'] and not analysis_result['error']:
            # Add threshold checks here if this filter is responsible for them
            # status = token_data.get('status', 'NEW') # Need token status
            # followers = analysis_result['followers']
            # age = analysis_result['account_age_days']
            # if self.meets_follower_threshold(status, followers) and age >= self.min_account_age_days:
            #    passed = True
            passed = True # Simplified pass if account exists
        
        return passed

    async def filter_tokens_by_twitter(self, tokens: List[Dict]) -> List[Dict]:
        """
        DEPRECATED in favor of using FilterManager and apply method?

        Fetches Twitter data, checks mint announcement, updates tokens,
        and filters based on announcement and status-specific follower counts.
        
        Args:
            tokens: List of token dictionaries (must include 'twitter' url and 'status').
            
        Returns:
            List[Dict]: Filtered list of tokens that passed Twitter checks.
        """
        if not tokens:
            self.logger.warning("No tokens provided for Twitter verification")
            return []
            
        self.logger.info(f"🔍 Starting Twitter enrichment & filtering for {len(tokens)} tokens")
        
        try:
            self.logger.debug(f"Using status-based follower thresholds: {self.follower_thresholds}")
        except Exception as e:
            self.logger.error(f"Failed to load thresholds: {e}. Cannot perform follower filtering.")
            return []
            
        if not self.twikit_client:
            self.logger.info("Initializing Twikit client...")
            if not await self.initialize():
                self.logger.error("Failed to initialize Twitter client")
                return []
        
        # Use a temporary list to hold tokens during processing
        temp_processed_tokens = [token.copy() for token in tokens] 
        tasks = []
        token_task_map = {} 

        self.logger.info(f"Creating verification tasks for {len(temp_processed_tokens)} tokens...")
        for index, token in enumerate(temp_processed_tokens):
            twitter_url = token.get('twitter')
            mint_address = token.get('mint') or token.get('address')
            
            if twitter_url and isinstance(twitter_url, str) and twitter_url.strip():
                task = asyncio.create_task(self.verify_twitter_account(twitter_url, mint_address))
                tasks.append(task)
                token_task_map[task] = index 
            else:
                self.logger.warning(f"Token {token.get('symbol', 'Unknown')} has no valid Twitter URL")
                token['twitter_handle'] = None
                token['twitter_exists'] = False
                token['twitter_error'] = 'Missing or invalid Twitter URL'
                token['twitter_mint_announced'] = False
                token['twitter_followers'] = 0
                token['twitter_blue_verified'] = False

        self.logger.info(f"Awaiting results for {len(tasks)} verification tasks...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        self.logger.info("Updating token dictionaries with verification results...")
        for task, result in zip(tasks, results):
            if isinstance(result, Exception):
                self.logger.error(f"Error in Twitter verification task: {result}")
                continue
                
            index = token_task_map[task]
            token = temp_processed_tokens[index]
            
            if isinstance(result, dict):
                token['twitter_handle'] = result.get('handle')
                token['twitter_exists'] = result.get('exists', False)
                token['twitter_error'] = result.get('error')
                token['twitter_followers'] = result.get('followers')
                token['twitter_blue_verified'] = result.get('blue_verified')
                token['twitter_created_at'] = result.get('created_at')
                token['twitter_account_age_days'] = result.get('account_age_days')
                token['twitter_description'] = result.get('description')
                token['twitter_mint_announced'] = result.get('mint_announced') if result.get('mint_announced') is not None else False 
                token['twitter_check_status'] = 'PASSED'
                token['twitter_followers'] = result.get('followers')
                token['twitter_account_age_days'] = result.get('account_age_days')

                # --- Log first passed token --- 
                if not self.logged_in:
                    self.logger.debug("=== START: Raw TwitterCheck PASSED token example ===")
                    try:
                        # Log the token data *after* status/details have been added
                        self.logger.debug(json.dumps(token, indent=2))
                    except TypeError as e:
                         self.logger.error(f"Could not serialize TwitterCheck passed token for logging: {e}")
                         self.logger.debug(f"Raw TwitterCheck data (potentially unserializable): {token}")
                    self.logger.debug("=== END: Raw TwitterCheck PASSED token example ===")
                    self.logged_in = True
                # --- End log --- 
            else:
                self.logger.error(f"Unexpected result type for {token.get('symbol', 'Unknown')}: {type(result)}")
                token['twitter_error'] = f"Unexpected result type: {type(result)}"

        self.logger.info(f"Performing final filtering on {len(temp_processed_tokens)} processed tokens...")
        final_verified_tokens = []
        failed_filter_count = 0

        for token in temp_processed_tokens:
            status = token.get('status', 'NEW').upper()
            required_followers = self.follower_thresholds.get(status)
            
            announced = token.get('twitter_mint_announced', False)
            followers = token.get('twitter_followers')

            passes_filter = False
            if announced:
                if required_followers is not None:
                    if followers is not None and followers >= required_followers:
                        passes_filter = True
                        self.logger.debug(f"✅ Token {token.get('symbol', 'Unknown')} PASSED: Announced=True, Followers={followers} >= {required_followers} ({status}) ")
                    else:
                        self.logger.debug(f"❌ Token {token.get('symbol', 'Unknown')} FAILED filter: Announced=True, Followers={followers} < {required_followers} ({status})")
                else:
                    self.logger.warning(f"❓ Token {token.get('symbol', 'Unknown')} SKIPPED follower check: No threshold for status '{status}'")
                    passes_filter = True # Pass if announced but status threshold unknown
            else:
                 self.logger.debug(f"❌ Token {token.get('symbol', 'Unknown')} FAILED filter: Mint not announced.")

            if passes_filter:
                final_verified_tokens.append(token)
            else:
                failed_filter_count += 1
        
        total_initial = len(tokens)
        total_final = len(final_verified_tokens)
        
        self.logger.info("\n📊 Twitter Verification & Filtering Summary:")
        self.logger.info(f"   • Initial Tokens: {total_initial}")
        self.logger.info(f"   • Tokens Passing Final Filter: {total_final}")
        self.logger.info(f"   • Tokens Failing Final Filter: {failed_filter_count}")
        success_rate = (total_final / total_initial * 100) if total_initial > 0 else 0
        self.logger.info(f"   • Overall Pass Rate: {success_rate:.1f}%")
        
        return final_verified_tokens

    async def close(self):
        """Closes any resources held by TwitterCheck, like the Twikit client session."""
        self.logger.info("Closing TwitterCheck resources...")
        closed_session = False
        if self.twikit_client:
            # Try the typical path for Twikit's internal httpx session first
            try:
                if hasattr(self.twikit_client, 'client') and self.twikit_client.client and \
                   hasattr(self.twikit_client.client, '_session') and self.twikit_client.client._session and \
                   hasattr(self.twikit_client.client._session, 'aclose') and \
                   asyncio.iscoroutinefunction(self.twikit_client.client._session.aclose):
                    
                    self.logger.info("Attempting to aclose() twikit_client.client._session (httpx)...")
                    await self.twikit_client.client._session.aclose()
                    self.logger.info("Successfully called aclose() on twikit_client.client._session.")
                    closed_session = True
            except Exception as e:
                self.logger.warning(f"Error attempting to close twikit_client.client._session: {e}")

            # Fallback to iterating common session attributes if direct path failed
            if not closed_session:
                session_attrs = ['_session', 'session', '_client', 'client', '_http', 'http', '_http_client']
                for attr_name in session_attrs:
                    if hasattr(self.twikit_client, attr_name):
                        session_obj = getattr(self.twikit_client, attr_name)
                        if session_obj is None: # Skip if the attribute is None
                            continue
                            
                        # Check for httpx-style aclose
                        if hasattr(session_obj, 'aclose') and asyncio.iscoroutinefunction(session_obj.aclose):
                            try:
                                self.logger.info(f"Fallback: Attempting to aclose() session attribute '{attr_name}' on Twikit client...")
                                await session_obj.aclose()
                                self.logger.info(f"Fallback: Successfully called aclose() on Twikit client's '{attr_name}'.")
                                closed_session = True
                                break # Found and closed a session
                            except Exception as e:
                                self.logger.warning(f"Fallback: Error calling aclose() on Twikit client's '{attr_name}': {e}")
                        # Check for aiohttp-style close (less likely for modern twikit but good for robustness)
                        elif hasattr(session_obj, 'close') and asyncio.iscoroutinefunction(session_obj.close):
                            try:
                                self.logger.info(f"Fallback: Attempting to close() session attribute '{attr_name}' on Twikit client (aiohttp style)...")
                                await session_obj.close()
                                self.logger.info(f"Fallback: Successfully called close() on Twikit client's '{attr_name}'.")
                                closed_session = True
                                break # Found and closed a session
                            except Exception as e:
                                self.logger.warning(f"Fallback: Error calling close() on Twikit client's '{attr_name}': {e}")
            
            if not closed_session:
                self.logger.warning("Could not find and close a standard session attribute (e.g., httpx session's aclose) on Twikit client.")
        
        self.twikit_client = None # Clear the client instance