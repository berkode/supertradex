import os
import logging
import asyncio
import json
import time
import random
import copy
from typing import List, Dict, Optional, Set, Any, Union, TYPE_CHECKING
from datetime import datetime, timezone, timedelta
import pandas as pd
from config.thresholds import Thresholds
from config.dexscreener_api import DexScreenerAPI
from config.filters_config import FiltersConfig
from config.rugcheck_api import RugcheckAPI
from filters.solsniffer_api import SolsnifferAPI
from filters.twitter_check import TwitterCheck
from filters.dump_filter import DumpFilter
from data.solanatracker_api import SolanaTrackerAPI
from data.token_database import TokenDatabase
from data.platform_tracker import PlatformTracker
from utils.logger import get_logger
from utils.exception_handler import ExceptionHandler
from utils.proxy_manager import ProxyManager
import aiohttp
from data.token_metrics import TokenMetrics
from config.dexscreener_api import DexScreenerAPI
from config.thresholds import Thresholds
from filters.filter_manager import FilterManager
from data.indicators import TechnicalIndicators
import httpx
from data.market_data import MarketData
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType
from pathlib import Path

# Import Settings, MarketDataService, Thresholds for type hinting only
if TYPE_CHECKING:
    from config.settings import Settings
    from data.market_data import MarketDataService # Note: Might need adjustment if MarketDataService is not the class
    from config.thresholds import Thresholds
    from data.token_metrics import TokenMetrics # Make sure TokenMetrics is hinted
    from filters.filter_manager import FilterManager # Make sure FilterManager is hinted
    from config.dexscreener_api import DexScreenerAPI # Make sure APIClient is hinted if that's the type
    from config.rugcheck_api import RugcheckAPI # Make sure RugcheckAPI is hinted

logger = logging.getLogger(__name__)

class TokenScanner:
    """
    Scans for tokens on DEXes and filters them using multiple APIs.
    """
    
    def __init__(self,
                 db: 'TokenDatabase',
                 settings: 'Settings',
                 thresholds: 'Thresholds', # Add thresholds parameter
                 filter_manager: 'FilterManager',
                 market_data: 'MarketData',
                 dexscreener_api: 'DexScreenerAPI', # Changed hint to DexScreenerAPI assuming that's the class
                 token_metrics: 'TokenMetrics',
                 rugcheck_api: Optional['RugcheckAPI'] = None):
        """
        Initializes the TokenScanner.
        Sets up dependencies, configurations, and initial state.
        """
        self.db = db
        self.filter_manager = filter_manager
        self.market_data = market_data
        self.settings = settings
        self.thresholds = thresholds # Assign the passed-in thresholds instance
        self.logger = get_logger(__name__)
        self.dexscreener_api = dexscreener_api
        self.token_metrics = token_metrics
        self.rugcheck_api = rugcheck_api
        self.debug = getattr(settings, 'DEBUG', False)  # Safely get DEBUG with default value
        self.scan_start_time = None

        # Load settings for scanner
        self.scan_interval = self.settings.TOKEN_SCAN_INTERVAL
        self.poll_interval = self.settings.POLL_INTERVAL
        self.http_timeout = self.settings.HTTP_TIMEOUT
        self.error_retry_interval = self.settings.ERROR_RETRY_INTERVAL

        # Initialize state variables
        self.tokens_data: Dict[str, Dict] = {}
        self.processed_tokens: Set[str] = set()
        self._is_running = False
        self.lock = asyncio.Lock()
        self.last_scan_time: Optional[datetime] = None
        self.circuit_breaker = CircuitBreaker(
            breaker_type=CircuitBreakerType.COMPONENT,
            identifier="token_scanner",
            max_consecutive_failures=self.settings.COMPONENT_CB_MAX_FAILURES, 
            reset_after_minutes=self.settings.CIRCUIT_BREAKER_RESET_MINUTES
        )
        self._db_lock = asyncio.Lock() # Initialize the database lock
        self.tasks = [] # Keep track of background tasks
        self.blacklist_update_task = None
        self.blacklist_last_check_time = None

        # Whitelist for forced pre-qualification
        self.force_prequalify_mints: Set[str] = set()
        self._load_forced_prequalify_whitelist()

        self.logger.info(f"TokenScanner initialized. Scan interval: {self.scan_interval} seconds.")

    def _load_forced_prequalify_whitelist(self):
        """Loads mint addresses from outputs/whitelist.csv into a set."""
        # Corrected path to outputs directory
        whitelist_path = Path(__file__).parent.parent / "outputs" / "whitelist.csv"
        if not whitelist_path.exists():
            self.logger.info(f"Prequalification whitelist file not found at {whitelist_path}. No tokens will be force-prequalified.")
            return

        try:
            df = pd.read_csv(whitelist_path)
            # Standardize column name check (case-insensitive)
            header = [col.lower().strip() for col in df.columns]
            if 'mint' not in header:
                self.logger.error(f"Whitelist file {whitelist_path} is missing the required 'mint' header (case-insensitive).")
                return

            # Find the actual column name (preserving original case for access)
            mint_col_name = df.columns[header.index('mint')]

            # Ensure mints are strings and handle potential NaN/empty values
            mints = df[mint_col_name].dropna().astype(str).tolist()
            self.force_prequalify_mints = set(m.strip() for m in mints if m.strip()) # Add strip()

            if self.force_prequalify_mints:
                self.logger.info(f"Loaded {len(self.force_prequalify_mints)} mints from prequalification whitelist ({whitelist_path}): {self.force_prequalify_mints}")
            else:
                 self.logger.info(f"Whitelist file {whitelist_path} loaded but contained no valid mint addresses under 'mint' header.")

        except pd.errors.EmptyDataError:
            self.logger.warning(f"Whitelist file {whitelist_path} is empty.")
        except Exception as e:
            self.logger.error(f"Error loading prequalification whitelist from {whitelist_path}: {e}", exc_info=True)

    async def initialize(self) -> bool:
        """Asynchronously initialize components that require it."""
        self.logger.info("Initializing TokenScanner components...")
        try:
            # Ensure components are initialized if not provided
            if not self.filter_manager:
                # Simplified init, assumes required components are available via settings/db
                self.logger.warning("FilterManager not provided, attempting basic initialization.")
                # If FilterManager has async init:
                # if hasattr(self.filter_manager, 'initialize') and asyncio.iscoroutinefunction(self.filter_manager.initialize):
                #     await self.filter_manager.initialize()
                # For now, assume it's passed correctly initialized or doesn't need async init here.
                pass # Placeholder - Ensure FilterManager is correctly initialized before use

            if not self.market_data:
                # Initialize MarketData if needed (assuming it has an async initialize)
                self.logger.warning("MarketData not provided, attempting basic initialization.")
                self.market_data = MarketData(db=self.db) # Pass DB
                if hasattr(self.market_data, 'initialize') and asyncio.iscoroutinefunction(self.market_data.initialize):
                    await self.market_data.initialize()
                    self.logger.info("MarketData initialized within TokenScanner.")
                else:
                    self.logger.warning("MarketData doesn't have an async initialize method or init failed.")

            # Initialize TokenMetrics (Removed - Now passed in __init__)
            # from data.token_metrics import TokenMetrics # Removed
            # self.token_metrics = TokenMetrics(settings=self.settings) # Removed

            self.logger.info("TokenScanner components initialized successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Error during TokenScanner initialization: {e}", exc_info=True)
            return False

    @property
    def scan_results(self) -> Dict:
        """Thread-safe access to scan results."""
        return self._scan_results.copy()
        
    async def close(self):
        """
        Clean up resources and close connections.
        """
        try:
            await self.dexscreener_api.close()
            await self.filter_manager.close()
            # Check if attributes exist before trying to close them
            if hasattr(self, 'solana_tracker_api') and self.solana_tracker_api:
                 await self.solana_tracker_api.close()
                 self.logger.info("SolanaTrackerAPI closed within TokenScanner.")
            if hasattr(self, 'solsniffer_api') and self.solsniffer_api:
                 await self.solsniffer_api.close()
                 self.logger.info("SolsnifferAPI closed within TokenScanner.")
            # Close MarketDataService if it has a close method
            if hasattr(self.market_data, 'close') and asyncio.iscoroutinefunction(self.market_data.close):
                await self.market_data.close()
                self.logger.info("MarketDataService closed within TokenScanner.")
            self.logger.info("TokenScanner resources cleaned up")
        except Exception as e:
            self.logger.error(f"Error during TokenScanner cleanup: {e}")
        
    async def scan_tokens(self) -> None:
        """
        Main method refactored for progressive data fetching, unified filtering, and single save.
        """
        self.logger.debug("--- Entering scan_tokens method ---")
        if not self.filter_manager:
            self.logger.error("FilterManager not initialized in TokenScanner!")
            return

        try:
            self.logger.info("Starting token scan cycle...")
            start_time = time.time()
            scan_timestamp = datetime.now(timezone.utc) # Use a consistent timestamp for this scan cycle

            # 1. Fetch trending tokens (DexScreener)
            # The method get_trending_tokens returns profiles that include 'icon' and 'links'
            trending_tokens_raw = await self.dexscreener_api.get_trending_tokens()
            if not trending_tokens_raw:
                self.logger.warning("No trending tokens found from DexScreener.")
                # Consider adding a return or continue based on desired flow if no tokens found

            # --- NEW: Initial Icon & Twitter URL Filter ---
            icon_twitter_filtered_tokens = []
            if trending_tokens_raw: # Ensure there are tokens to filter
                for token_profile in trending_tokens_raw:
                    has_icon = bool(token_profile.get('icon'))
                    has_twitter = False
                    if isinstance(token_profile.get('links'), list):
                        for link_info in token_profile['links']:
                            if isinstance(link_info, dict) and link_info.get('type') == 'twitter' and link_info.get('url'):
                                has_twitter = True
                                break
                    if has_icon and has_twitter:
                        icon_twitter_filtered_tokens.append(token_profile)
                    else:
                        mint_for_log = token_profile.get('tokenAddress', 'Unknown Mint') # 'tokenAddress' is the mint in this structure
                        self.logger.debug(f"Token {mint_for_log} failed initial icon/twitter filter. Icon: {has_icon}, Twitter: {has_twitter}")
            
            self.logger.info(f"Initial trending fetch: {len(trending_tokens_raw)}, After icon/twitter filter: {len(icon_twitter_filtered_tokens)}")

            # --- Limit fetched tokens based on settings (applied to icon/twitter filtered list) ---
            limit = self.settings.DEXSCREENER_TOKEN_QTY
            if limit and len(icon_twitter_filtered_tokens) > limit:
                self.logger.info(f"Have {len(icon_twitter_filtered_tokens)} tokens after icon/twitter filter, limiting to {limit} based on DEXSCREENER_TOKEN_QTY setting.")
                final_trending_list_for_details = icon_twitter_filtered_tokens[:limit]
            else:
                final_trending_list_for_details = icon_twitter_filtered_tokens
            # --- End Limit --- 

            # --- Log Raw API Output Sample (from the list that passed icon/twitter filter) ---
            try:
                sample_token = final_trending_list_for_details[0] if final_trending_list_for_details else {}
                self.logger.debug(f"DexScreener Trending Token Profile (Sample, post icon/twitter filter): {json.dumps(sample_token, indent=2, default=str)}")
            except Exception as log_e:
                self.logger.warning(f"Could not log raw API output sample (post icon/twitter): {log_e}")
            # --- End Log Raw API Output Sample ---

            self.logger.info(f"Proceeding to fetch details for {len(final_trending_list_for_details)} tokens that passed icon/twitter filter and quantity limit.")

            # 2. Initial Pre-Filter (Extracting mint from the icon/twitter filtered list)
            pre_filtered_solana_tokens_for_details = [] # Stores {'mint': str, 'original_profile': dict} for SOLANA tokens
            for token_profile_data in final_trending_list_for_details: # token_profile_data is a PAIR object
                self.logger.debug(f"Pre-filtering trending token profile (keys): {list(token_profile_data.keys())}")
                try:
                    chain_id = token_profile_data.get('chainId')
                    if chain_id != 'solana':
                        self.logger.debug(f"Skipping non-Solana chain token from trending: {chain_id}, Pair: {token_profile_data.get('pairAddress')}")
                        continue

                    # Attempt to extract mint:
                    # 1. Try standard baseToken.address (common for detailed pair objects)
                    mint = token_profile_data.get('baseToken', {}).get('address')
                    
                    # 2. If not found, try tokenAddress (seems to be used in some trending/summary objects)
                    if not mint:
                        mint = token_profile_data.get('tokenAddress')
                        if mint:
                            self.logger.debug(f"Using 'tokenAddress' as mint for trending Solana pair: {mint}")
                    
                    if not mint:
                        pair_addr_log = token_profile_data.get('pairAddress', 'UnknownPair')
                        try:
                             token_str = json.dumps(token_profile_data, indent=2, default=str)
                        except Exception:
                             token_str = str(token_profile_data)
                        self.logger.warning(f"Skipping Solana trending token profile (Pair: {pair_addr_log}) due to missing 'baseToken.address' (mint). Data: {token_str}")
                        continue
                    
                    # Store mint and the original profile data (which is a PAIR object)
                    pre_filtered_solana_tokens_for_details.append({'mint': mint, 'original_profile': token_profile_data})
                except Exception as e:
                    self.logger.warning(f"Error during pre-filter for trending token profile {token_profile_data.get('baseToken', {}).get('address', 'UNKNOWN')}: {e}", exc_info=True)
            
            self.logger.info(f"{len(pre_filtered_solana_tokens_for_details)} Solana tokens (mint extracted from trending) to fetch details for.")
            if not pre_filtered_solana_tokens_for_details:
                 self.logger.info("No Solana tokens from trending to fetch details for. Ending scan cycle early.")
                 return # Return early if no Solana tokens to process

            # 3. Fetch Detailed Data (DexScreener bulk for SOLANA tokens)
            token_mints_for_details = [t['mint'] for t in pre_filtered_solana_tokens_for_details]
            detailed_data_map = await self._fetch_detailed_token_data_map(token_mints_for_details) # detailed_data_map uses mint as key

            # Combine initial, detailed data, and categorize
            combined_data_tokens = []
            # Iterate through the pre_filtered_solana_tokens_for_details which contains the correct mints
            for pre_filtered_item in pre_filtered_solana_tokens_for_details: 
                mint_from_trending = pre_filtered_item['mint'] # This is the confirmed Solana mint
                original_profile_data = pre_filtered_item['original_profile'] # This is the PAIR data from trending

                # details from detailed_data_map is also a PAIR object, keyed by mint_from_trending
                details_pair_object = detailed_data_map.get(mint_from_trending) 
                
                if not details_pair_object:
                    self.logger.warning(f"Skipping Solana mint {mint_from_trending}: Could not fetch further DexScreener details (was in trending, but no pair data from details endpoint).")
                    continue
                
                # The 'details_pair_object' is a "pair" object from DexScreener API.
                # Its baseToken.address should be the mint.
                # This check ensures the details fetched correspond to the mint we asked for.
                actual_mint_in_details = details_pair_object.get('baseToken', {}).get('address')
                if not actual_mint_in_details or actual_mint_in_details != mint_from_trending:
                    self.logger.warning(f"Mint mismatch or missing in details for Solana trending mint {mint_from_trending}. Details baseToken: {actual_mint_in_details}. Skipping.")
                    continue

                # Use the 'details_pair_object' as the primary source for further processing.
                # Add our confirmed 'mint' (which is actual_mint_in_details) to it for convenience.
                details_pair_object['mint'] = actual_mint_in_details # Same as mint_from_trending at this point

                # Consolidate icon: Prefer details_pair_object.info.imageUrl, fallback to original_profile_data.icon
                # original_profile_data is the PAIR object from the trending list
                # details_pair_object is the PAIR object from the details endpoint
                
                icon_url = None
                details_info = details_pair_object.get('info')
                if details_info and details_info.get('imageUrl'):
                    icon_url = details_info['imageUrl']
                elif original_profile_data.get('icon'): # Fallback to icon from trending pair data
                    icon_url = original_profile_data['icon']
                details_pair_object['icon_url'] = icon_url
                
                # Consolidate links (especially Twitter): Prefer details_pair_object.info.socials, 
                # fallback to original_profile_data.links
                social_links = []
                if details_info and isinstance(details_info.get('socials'), list):
                    social_links = details_info['socials']
                elif isinstance(original_profile_data.get('links'), list): # Fallback to links from trending pair data
                    social_links = original_profile_data['links']
                details_pair_object['social_links'] = social_links

                # Map DexScreener API camelCase fields to snake_case for internal consistency
                details_pair_object['dex_id'] = details_pair_object.get('dexId', 'unknown')
                details_pair_object['pair_address'] = details_pair_object.get('pairAddress')

                # Map token symbol and name from baseToken
                base_token = details_pair_object.get('baseToken', {})
                details_pair_object['symbol'] = base_token.get('symbol', 'UNKNOWN')
                details_pair_object['name'] = base_token.get('name', 'Unknown Token')

                # Map other common DexScreener fields for consistency
                if 'priceUsd' in details_pair_object:
                    details_pair_object['price_usd'] = details_pair_object['priceUsd']
                if 'priceNative' in details_pair_object:
                    details_pair_object['price_native'] = details_pair_object['priceNative']

                # Map liquidity and volume data for easier access
                liquidity_data = details_pair_object.get('liquidity', {})
                if isinstance(liquidity_data, dict) and 'usd' in liquidity_data:
                    details_pair_object['liquidity_usd'] = liquidity_data['usd']

                volume_data = details_pair_object.get('volume', {})
                if isinstance(volume_data, dict):
                    if 'h24' in volume_data:
                        details_pair_object['volume_24h'] = volume_data['h24']
                    if 'm5' in volume_data:
                        details_pair_object['volume_5m'] = volume_data['m5']

                # Map market cap data
                if 'marketCap' in details_pair_object:
                    details_pair_object['market_cap'] = details_pair_object['marketCap']
                elif 'fdv' in details_pair_object:
                    details_pair_object['market_cap'] = details_pair_object['fdv']

                # --- NEW: PRE-QUALIFICATION & STREAMING ---
                # Prequalification uses fields from 'details_pair_object' like liquidity.usd, volume.h24, pairCreatedAt
                is_qualified = await self._prequalify_token(details_pair_object) 
                if is_qualified:
                    self.logger.info(f"Token {actual_mint_in_details} pre-qualified based on internal TokenScanner checks.") # MODIFIED Log Message
                # --- END NEW ---\
                
                # Calculate age_minutes using pairCreatedAt from 'details_pair_object'
                details_pair_object['age_minutes'] = await self._get_token_age_minutes(details_pair_object.get('pairCreatedAt'))

                # Categorize using TokenMetrics
                try:
                    if self.token_metrics:
                        metrics_input = {
                            'age_minutes': float(details_pair_object.get('age_minutes', 0) or 0),
                            'market_cap': float(details_pair_object.get('market_cap', details_pair_object.get('fdv', 0)) or 0), # Use marketCap, fallback to fdv
                            'liquidity_usd': float(details_pair_object.get('liquidity_usd', 0) or 0),
                            'volume_5m': float(details_pair_object.get('volume_5m', 0) or 0)
                        }
                        category = self.token_metrics.determine_token_category(metrics_input)
                    else:
                        category = 'UNKNOWN'  # Default category when token_metrics is not available
                        self.logger.warning(f"TokenMetrics not available, using default category for {actual_mint_in_details}")
                    
                    details_pair_object['initial_category'] = category # Add category to the 'details_pair_object' dict
                    combined_data_tokens.append(details_pair_object) # Add the modified 'details_pair_object' dict
                except Exception as cat_e:
                     self.logger.error(f"Error categorizing token {actual_mint_in_details}: {cat_e}", exc_info=True)
                     # Add a default category and continue
                     details_pair_object['initial_category'] = 'ERROR'
                     combined_data_tokens.append(details_pair_object)

            current_tokens = combined_data_tokens # List now holds dicts based on 'details_pair_object'
            self.logger.info(f"{len(current_tokens)} tokens have combined data and category.")
            if not current_tokens: return

            # Log example token after DexScreener details merge
            if current_tokens:
                try:
                    example_output = json.dumps(current_tokens[0], indent=2, default=str)
                    self.logger.debug(f"Example token after DexScreener merge & categorization: {example_output}")
                except Exception as json_e:
                     self.logger.warning(f"Could not serialize example token after DexScreener merge: {json_e}")


            # --- Filter for Solana Tokens (REDUNDANT BLOCK - REMOVED) ---
            # The list comprehension below was faulty and is now redundant
            # as current_tokens should already contain only Solana tokens due to earlier filtering.
            # solana_tokens = [ \
            # token for token in current_tokens \
            # if token.get('chainId') == 'solana' \
            # ]
            # THIS BLOCK IS NOW REDUNDANT as filtering happens before detail fetching
            # if not solana_tokens:
            # self.logger.info("No Solana tokens found after filtering by chainId. Ending scan cycle.")
            # return # Exit if no Solana tokens
            # self.logger.info(f"Filtered down to {len(solana_tokens)} Solana tokens.")
            # From now on, use solana_tokens for Solana-specific checks
            
            # current_tokens list already contains only processed Solana tokens.
            # If current_tokens is empty here, it means no Solana tokens made it through the full processing.
            if not current_tokens:
                 self.logger.info("No Solana tokens remaining after full processing. Ending scan cycle.")
                 return

            # Use current_tokens directly, as it should only contain Solana tokens by this point.
            # For clarity in the rest of the function, we can assign it to solana_tokens if preferred,
            # or refactor the rest of the function to use current_tokens.
            solana_tokens = current_tokens 

            # --- Fetch Additional API Data (Sequential and Batch) ---
            # Note: Data is added directly to the dictionaries within solana_tokens

            # 4. Fetch RugCheck Scores (Concurrent)
            rugcheck_scores_map = {}
            if self.rugcheck_api and solana_tokens:
                mints_to_check = [token.get('mint') for token in solana_tokens if token.get('mint')]
                if mints_to_check:
                    self.logger.info(f"Fetching RugCheck scores concurrently for {len(mints_to_check)} Solana tokens using get_scores_for_mints...")
                    try:
                        # Call the CONCURRENT method in RugcheckAPI
                        rugcheck_scores_map = await self.rugcheck_api.get_scores_for_mints(mints_to_check)
                        
                        # --- Debug Log for the entire result map ---
                        try:
                             scores_output = json.dumps(rugcheck_scores_map, indent=2, default=str)
                             # Limit log size if very large
                             log_limit = 3000
                             if len(scores_output) > log_limit:
                                 self.logger.debug(f"API Output Map - RugCheck (Partial): {scores_output[:log_limit]}...")
                             else:
                                 self.logger.debug(f"API Output Map - RugCheck (Full): {scores_output}")
                        except Exception as json_e:
                             self.logger.warning(f"Could not serialize RugCheck scores map: {json_e}")
                        # --- End Debug Log ---

                    except Exception as rug_e:
                        self.logger.error(f"Error calling RugcheckAPI.get_scores_for_mints: {rug_e}", exc_info=True)
                        # If the batch call fails, rugcheck_scores_map remains empty
                else:
                    self.logger.info("No valid mints found in solana_tokens to fetch RugCheck scores for.")
            elif not solana_tokens:
                 self.logger.info("No Solana tokens to fetch RugCheck scores for.")
            else:
                self.logger.warning("RugcheckAPI client not available. Skipping RugCheck scores.")

            # Now, iterate through solana_tokens and update based on the fetched map
            for token in solana_tokens:
                mint = token.get('mint')
                if mint in rugcheck_scores_map:
                    token['rugcheck_data'] = rugcheck_scores_map[mint]
                elif self.rugcheck_api and mint: # API exists but no score was returned for this mint
                     token['rugcheck_data'] = {'error': 'No data returned from API'}
                else: # API client missing or no mint
                    token['rugcheck_data'] = {'error': 'API client missing or invalid mint'}
                    # Default score to avoid downstream issues? Depends on filter logic.
                    # token['rugcheck_data']['score_normalised'] = 100 

            # Log example token after RugCheck update
            if solana_tokens:
                 try:
                    example_output = json.dumps(solana_tokens[0], indent=2, default=str)
                    self.logger.debug(f"Example token after RugCheck update: {example_output}")
                 except Exception as json_e:
                     self.logger.warning(f"Could not serialize example token after RugCheck update: {json_e}")


            # 5. Fetch Solsniffer Data (Batch)
            # [REMOVED - Solsniffer filtering will be handled individually by FilterManager]
            # Original block attempted to call a non-existent batch_filter_tokens method.
            # if hasattr(self, 'solsniffer_api') and self.solsniffer_api and solana_tokens:
            #    self.logger.info(f"Fetching Solsniffer data for {len(solana_tokens)} Solana tokens using batch_filter_tokens...")
            #    try:
            #        solsniffer_results_map = await self.solsniffer_api.batch_filter_tokens(solana_tokens)
            #        ...
            #    except AttributeError as ae:
            #         self.logger.error(f"SolsnifferAPI is missing the 'batch_filter_tokens' method. Skipping Solsniffer fetch. Error: {ae}", exc_info=True)
            #         for token_data in solana_tokens: token_data['solsniffer_data'] = {'error': 'batch_filter_tokens missing'}
            #    except Exception as e:
            #        self.logger.error(f"Error fetching/processing Solsniffer batch data: {e}", exc_info=True)
            #        for token_data in solana_tokens: token_data['solsniffer_data'] = {'error': str(e)}
            # elif not solana_tokens:
            #    self.logger.info("No Solana tokens remaining to fetch Solsniffer data for.")
            # else:
            #     self.logger.warning("SolsnifferAPI client not available or no tokens. Skipping Solsniffer fetch.")
            #     for token_data in solana_tokens: token_data['solsniffer_data'] = {'error': 'API client missing'}
            #
            # if solana_tokens:
            #     try:
            #         example_output = json.dumps(solana_tokens[0], indent=2, default=str)
            #         self.logger.debug(f"Example token after Solsniffer update: {example_output}")
            #     except Exception as json_e:
            #         self.logger.warning(f"Could not serialize example token after Solsniffer update: {json_e}")


            # 6. Fetch Twitter Data (Sequential)
            # [REMOVED - Twitter checks will be handled individually by SocialFilter within FilterManager]
            # Original block fetched data directly in the scanner.
            # if hasattr(self, 'twitter_check') and self.twitter_check and solana_tokens:
            #     self.logger.info(f"Fetching Twitter data sequentially for {len(solana_tokens)} Solana tokens using verify_twitter_account...")
            # ... (rest of the original Twitter block commented out) ...
            # elif not solana_tokens:
            #      self.logger.info("No Solana tokens remaining to fetch Twitter data for.")
            # else:
            #      self.logger.warning("TwitterCheck client not available or no tokens. Skipping Twitter fetch.")
            #      for token_data in solana_tokens: token_data['twitter_data'] = {'error': 'Twitter client not available'}


            # --- Apply All Filters via FilterManager ---
            # FilterManager applies filters per token and modifies the token_data dict
            processed_tokens_for_db = [] # List to hold fully processed tokens ready for DB preparation
            filter_application_errors = 0
            aborted_early_count = 0

            if solana_tokens:
                self.logger.info(f"Applying configured filters via FilterManager individually to {len(solana_tokens)} Solana tokens...")

                for token_data in solana_tokens: # token_data already contains Dex, Rug, Sniff, Tweet data
                    mint = token_data.get('mint')
                    if not mint:
                        self.logger.warning("Skipping token in FilterManager stage due to missing mint.")
                        continue

                    try:
                        # Apply filters using FilterManager
                        # FilterManager now expects token_data and optional initial_scan flag
                        processed_token_data = await self.filter_manager.apply_filters(token_data, initial_scan=True)
                        
                        # Check overall_filter_passed from the processed_token_data
                        if processed_token_data.get('overall_filter_passed', False):
                            processed_tokens_for_db.append(processed_token_data)
                        else:
                            # This path is taken if overall_filter_passed is False
                            aborted_early_count +=1 # Count if aborted or failed critical
                            self.logger.info(f"Token {mint} did not pass initial critical filters or was aborted. Status: {processed_token_data.get('analysis_status')}")
                            # Do not add to tokens_to_save_batch if it failed critical filters
                            continue # Skip to the next token

                    except AttributeError as filter_e:
                         self.logger.error(f"FilterManager missing expected 'apply_filters' method? {filter_e}", exc_info=True)
                         filter_application_errors += 1
                         break # Stop filtering if manager is broken
                    except Exception as e:
                        self.logger.error(f"Error applying filters via FilterManager for token {mint}: {e}", exc_info=True)
                        filter_application_errors += 1
                        # Optionally add error info to token_data, but skip saving it for now
                        # token_data['filter_error'] = str(e)
                        # Still continue to next token

                self.logger.info(f"FilterManager processing complete. Ready for DB: {len(processed_tokens_for_db)}, Aborted Early: {aborted_early_count}, Errors: {filter_application_errors}")

            else:
                 self.logger.info("No Solana tokens remaining to apply FilterManager filters.")


            # --- Prepare and Save Final Results to DB ---
            tokens_to_save_prepared = []
            for token_data in processed_tokens_for_db: # Iterate over fully processed tokens
                 prepared_data = self._prepare_token_for_db(token_data, scan_timestamp) # Pass scan timestamp
                 if prepared_data:
                     tokens_to_save_prepared.append(prepared_data)

            if tokens_to_save_prepared:
                async with self._db_lock:
                    try:
                        await self.db.update_insert_token(tokens_to_save_prepared)
                        self.logger.info(f"Saved/Updated {len(tokens_to_save_prepared)} tokens to the database via update_insert_token.")
                    except AttributeError as db_e:
                         self.logger.error(f"TokenDatabase missing expected 'update_insert_token' method? {db_e}", exc_info=True)
                    except Exception as e:
                         self.logger.error(f"Error saving tokens to database using update_insert_token: {e}", exc_info=True)
            elif processed_tokens_for_db: # Log if tokens were processed but failed preparation
                 self.logger.warning(f"{len(processed_tokens_for_db)} tokens were processed, but 0 were prepared successfully for DB saving.")
            else:
                 self.logger.info("No tokens were processed successfully to save in this cycle.")

            # After saving tokens to DB, update best token selection
            if tokens_to_save_prepared:
                await self._update_best_token_selection()

            elapsed_time = time.time() - start_time
            self.logger.info(f"Token scan cycle completed in {elapsed_time:.2f} seconds.")
            self.last_scan_time = datetime.now(timezone.utc)

        except asyncio.CancelledError:
            self.logger.info("scan_tokens task cancelled.")
            raise # Re-raise CancelledError to be handled by the main loop

        except Exception as e:
            self.logger.error(f"Unhandled error in scan_tokens: {e}", exc_info=True)
            # Optionally, trigger circuit breaker or other error handling here
            self.circuit_breaker.increment_failures()
        finally:
            # Ensure logging happens even if an error occurs within the try block
            # Note: start_time might not be defined if error happens before its assignment
            if 'start_time' in locals():
                 duration = time.time() - start_time
                 self.logger.debug(f"--- Exiting scan_tokens method (Duration: {duration:.2f}s) ---")
            else:
                 self.logger.debug(f"--- Exiting scan_tokens method (Error before start_time assignment) ---")


    async def _fetch_detailed_token_data_map(self, mints: List[str]) -> Dict[str, Dict]:
        """Fetches detailed token data from DexScreener for multiple mints."""
        self.logger.info(f"Fetching DexScreener details for {len(mints)} mints via get_token_details...")
        details_map = {}
        if not mints:
            self.logger.warning("No mints provided to _fetch_detailed_token_data_map.")
            return {}
            
        try:
            # Call the existing get_token_details method which handles list input
            raw_details = await self.dexscreener_api.get_token_details(mints)

            # --- ADD DEBUG LOG: Log raw API response BEFORE processing --- #
            try:
                # Attempt to log the full raw response (or a sample if too large)
                raw_details_log = json.dumps(raw_details, indent=2, default=str)
                # Limit log size if necessary (e.g., first 1000 chars)
                log_limit = 2000
                if len(raw_details_log) > log_limit:
                    # --- FIX: Use triple quotes for multi-line f-string --- #
                    self.logger.debug(f"""Raw DexScreener Details Multi Response (Sample, {len(mints)} mints):
                    {raw_details_log[:log_limit]}... (truncated)""")
                else:
                    # --- FIX: Use triple quotes for multi-line f-string --- #
                    self.logger.debug(f"""Raw DexScreener Details Multi Response ({len(mints)} mints):
                    {raw_details_log}""")
            except Exception as log_e:
                self.logger.warning(f"Could not serialize/log raw DexScreener details response: {log_e}. Type: {type(raw_details)}")
            # --- END DEBUG LOG --- #

            # Process the response into a mint -> data map
            if isinstance(raw_details, dict) and 'pairs' in raw_details:
                for pair_data in raw_details['pairs']:
                    mint = pair_data.get('baseToken', {}).get('address')
                    if mint:
                        details_map[mint] = pair_data
            elif isinstance(raw_details, list): # Handle if API returns list directly
                 for pair_data in raw_details:
                    mint = pair_data.get('baseToken', {}).get('address')
                    if mint:
                        details_map[mint] = pair_data
            else:
                self.logger.warning(f"Unexpected format received from DexScreener details multi: {type(raw_details)}")


            self.logger.info(f"Processed DexScreener details for {len(details_map)} mints.")
            return details_map
        except Exception as e:
            self.logger.error(f"Error fetching/processing DexScreener details multi: {e}", exc_info=True)
            return {}

    async def run_scan_loop(self, shutdown_event: asyncio.Event):
        """Run the token scanning loop periodically until shutdown_event is set."""
        self.logger.info("Starting TokenScanner run_scan_loop...")
        while not shutdown_event.is_set():
            try:
                await self.scan_tokens()
            except asyncio.CancelledError:
                self.logger.info("Scan loop cancelled during scan_tokens.")
                break # Exit loop if scan_tokens itself is cancelled
            except Exception as e:
                self.logger.error(f"Error in scan_tokens loop iteration: {e}", exc_info=True)
                # Optional: Add specific error handling or shorter sleep for certain errors
                self.logger.info(f"Waiting {self.scan_interval} seconds before retry due to error.")
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=self.scan_interval)
                    if shutdown_event.is_set():
                        self.logger.info("Shutdown event received during error wait. Exiting scan loop.")
                        break
                except asyncio.TimeoutError:
                    pass # Timeout means shutdown_event wasn't set, continue loop
                continue # Continue the loop after error and sleep
        
            # Successful scan, sleep for the normal interval, but check for shutdown during sleep
            if shutdown_event.is_set():
                self.logger.info("Shutdown event received after successful scan. Exiting scan loop before sleep.")
                break

            self.logger.info(f"Scan cycle finished, sleeping for {self.scan_interval} seconds.")
            try:
                # Wait for the scan_interval or until shutdown_event is set
                await asyncio.wait_for(shutdown_event.wait(), timeout=self.scan_interval)
                if shutdown_event.is_set():
                    self.logger.info("Shutdown event received during sleep. Exiting scan loop.")
                    break # Exit if shutdown event is set during sleep
            except asyncio.TimeoutError:
                pass # Timeout means shutdown_event wasn't set, loop will continue
            except asyncio.CancelledError: # Catch cancellation of the wait_for itself
                self.logger.info("Scan loop's sleep wait_for was cancelled. Exiting.")
                break
        self.logger.info("TokenScanner run_scan_loop finished.")

    
    def _prepare_token_for_db(self, token_data: Dict, scan_timestamp: datetime) -> Optional[Dict]:
        """
        Prepares the final token data dictionary for database insertion/update.
        Includes normalization logic for key fields and stores full raw data in api_data.
        """
        mint = token_data.get('mint')
        if not mint:
             self.logger.error(f"_prepare_token_for_db called with token_data missing 'mint'.") 
             return None

        self.logger.debug(f"Preparing token {mint} for DB...") # Log entry

        try:
            # Ensure filter_results exists, default if not
            filter_results = token_data.get('filter_results', {})
            if not isinstance(filter_results, dict):
                filter_results = {}

            # Extract key values from token_data 
            pair_address = token_data.get('pair_address')
            symbol = token_data.get('symbol', 'UNKNOWN')
            name = token_data.get('name', 'Unknown Token')
            
            # Price calculations and normalization
            price_native = token_data.get('price_native')  # Original price in native currency
            price_usd = token_data.get('price_usd')        # Price in USD
            
            # Ensure we have a valid price - use price_usd or calculate from price_native if needed
            if price_usd is None and price_native is not None:
                # Calculate USD price using SOL price if available
                sol_price = token_data.get('sol_price')
                if sol_price:
                    price_usd = float(price_native) * float(sol_price)
            
            # Liquidity, volume, market cap
            liquidity_usd = token_data.get('liquidity_usd')
            # If liquidity_usd is not directly available, extract from nested structure
            if liquidity_usd is None:
                liquidity_data = token_data.get('liquidity', {})
                if isinstance(liquidity_data, dict):
                    liquidity_usd = liquidity_data.get('usd')
            
            volume_h24 = token_data.get('volume_24h')  # Get directly from token_data or from volume dict
            if volume_h24 is None and isinstance(token_data.get('volume'), dict):
                volume_h24 = token_data.get('volume', {}).get('h24', 0)
                
            market_cap = token_data.get('market_cap')
            
            # Age calculations
            age_minutes = token_data.get('age_minutes')
            first_scan_timestamp = token_data.get('first_scan_timestamp', scan_timestamp)

            # --- Extracting Filter Results ---
            overall_filter_passed = token_data.get('overall_filter_passed', False)

            # Rugcheck specific - Extract from rugcheck_data instead of filter_results
            rugcheck_data = token_data.get('rugcheck_data', {})
            rugcheck_passed = None
            rugcheck_score = None
            
            if isinstance(rugcheck_data, dict) and 'error' not in rugcheck_data:
                # Extract score from RugCheck API response
                rugcheck_score = rugcheck_data.get('score_normalised')
                if rugcheck_score is not None:
                    rugcheck_passed = True  # If we have a score, consider it passed
            elif isinstance(rugcheck_data, dict) and 'error' in rugcheck_data:
                self.logger.debug(f"RugCheck error for {mint}: {rugcheck_data.get('error')}")

            # Social specific (adjust based on actual SocialFilter output)
            social_exists = filter_results.get('social', {}).get('exists', None)
            social_handle = filter_results.get('social', {}).get('handle', None)
            social_followers = filter_results.get('social', {}).get('followers', None)
            
            # Store category/dex info
            category = token_data.get('category', 'NONE')  # Default to NONE
            dex_id = token_data.get('dex_id', 'unknown')  # Default to unknown
            
            # Determine monitoring_status
            monitoring_status = token_data.get('monitoring_status', 'detected')  # Default to detected

            # --- Timestamps and Status ---
            first_scan_timestamp = token_data.get('first_scan_timestamp', scan_timestamp) # Use current if missing

            # --- Consolidate into DB Schema format ---
            db_entry = {
                'mint': mint,
                'symbol': symbol,
                'name': name,
                'pair_address': pair_address,
                'price': price_usd,  # Use price_usd for the 'price' field
                'liquidity': liquidity_usd,  # Use liquidity_usd for the 'liquidity' field
                'volume_24h': volume_h24,  # Use volume_h24 for the 'volume_24h' field
                'market_cap': market_cap,
                'age_minutes': token_data.get('age_minutes'),
                'is_valid': True,  # Assume valid unless known invalid
                'overall_filter_passed': overall_filter_passed,
                'monitoring_status': monitoring_status,
                'last_scanned_at': scan_timestamp,
                'category': category,
                'dex_id': dex_id,
                'rugcheck_score': rugcheck_score,  # Add rugcheck_score to database entry
            }
            
            # Add social media info if available
            if social_handle:
                db_entry['twitter'] = social_handle
                
            # Store full token data in api_data JSON field with any necessary cleanup
            api_data = token_data.copy()
            # Remove redundant fields that are stored separately to avoid duplication
            for field in ['mint', 'symbol', 'name', 'pair_address', 'overall_filter_passed', 'monitoring_status']:
                api_data.pop(field, None)
                
            # Add rugcheck results to api_data
            if rugcheck_score is not None:
                if 'rugcheck' not in api_data:
                    api_data['rugcheck'] = {}
                api_data['rugcheck']['score'] = rugcheck_score
                api_data['rugcheck']['passed'] = rugcheck_passed
                api_data['rug_check_score'] = rugcheck_score  # Duplicate for easier queries
            
            # Add social data to api_data
            if social_exists is not None or social_handle or social_followers is not None:
                if 'social' not in api_data:
                    api_data['social'] = {}
                api_data['social']['exists'] = social_exists
                api_data['social']['handle'] = social_handle
                api_data['social']['followers'] = social_followers
                
            db_entry['api_data'] = api_data
            db_entry['scan_results'] = filter_results
            
            # Return prepared entry
            self.logger.debug(f"Prepared token {mint} for DB with price: ${price_usd if price_usd else 'N/A'}")
            return db_entry
        except Exception as e:
            self.logger.error(f"Error preparing token {mint} for DB: {str(e)}", exc_info=True)
            return None
        
    # --- NEW: Pre-qualification Method ---
    async def _prequalify_token(self, token_data: Dict) -> bool:
        """Check if a token meets basic pre-qualification criteria before full filtering."""
        self.logger.debug(f"Entering _prequalify_token. Raw token_data received: {token_data}")
        raw_pair_created_at = token_data.get('pairCreatedAt')
        self.logger.debug(f"Value of token_data.get('pairCreatedAt'): {raw_pair_created_at}")

        mint = token_data.get('baseToken', {}).get('address')
        symbol = token_data.get('baseToken', {}).get('symbol', 'N/A')

        if not mint:
            self.logger.warning("Prequalification check called with token_data missing 'baseToken.address' (mint).")
            return False

        # --- Calculate metrics for pre-qualification ---
        age_minutes: Optional[float] = None
        if raw_pair_created_at:
            try:
                pair_created_at_ms = int(raw_pair_created_at)
                age_dt = datetime.fromtimestamp(pair_created_at_ms / 1000, tz=timezone.utc)
                current_time_utc = datetime.now(timezone.utc)
                age_delta = current_time_utc - age_dt
                age_minutes = age_delta.total_seconds() / 60
            except (ValueError, TypeError) as e:
                self.logger.warning(f"Could not parse pairCreatedAt '{raw_pair_created_at}' for {mint}. Error: {e}")
                # age_minutes remains None

        liquidity_usd: Optional[float] = token_data.get('liquidity', {}).get('usd')
        volume_h24: Optional[float] = token_data.get('volume', {}).get('h24')
        
        # Log the values that will be used for checks
        self.logger.debug(f"Prequalifying {mint} ({symbol}): Calculated AgeMins={age_minutes}, LiqUSD={liquidity_usd}, Vol24H={volume_h24}")

        # Check blacklist first (using the DB method)
        try:
            if await self.db.is_blacklisted(mint):
                self.logger.debug(f"Token {mint} ({symbol}) is blacklisted. Skipping pre-qualification.")
                return False
        except Exception as e:
            self.logger.error(f"Error checking blacklist for {mint}: {e}", exc_info=True)
            return False # Treat DB error as potential blacklist

        # Check whitelist for forced pre-qualification
        if mint in self.force_prequalify_mints:
            self.logger.info(f"Token {mint} ({symbol}) found in forced prequalification whitelist. Prequalified.")
            return True
            
        # Check basic criteria (liquidity, volume) using Thresholds
        # Age is NOT checked here for pre-qualification, only calculated for later use.
        min_liquidity_threshold = self.thresholds.MIN_LIQUIDITY
        min_volume_threshold = self.thresholds.MIN_VOLUME_24H

        passes_liquidity = liquidity_usd is not None and liquidity_usd >= min_liquidity_threshold
        passes_volume = volume_h24 is not None and volume_h24 >= min_volume_threshold
        
        is_prequalified = passes_liquidity and passes_volume # Age check removed

        if is_prequalified:
            self.logger.info(f"Token {mint} ({symbol}) pre-qualified (Liquidity & Volume).") # Updated log
            return True
        else:
            reasons = []
            # Age failure reason removed
            min_liquidity_str = f"${min_liquidity_threshold:.2f}"
            liquidity_str = f"${liquidity_usd:.2f}" if liquidity_usd is not None else "N/A"
            if not passes_liquidity:
                 reasons.append(f"Liquidity USD ({liquidity_str}) < Min ({min_liquidity_str})")
            
            min_volume_str = f"${min_volume_threshold:.2f}"
            volume_str = f"${volume_h24:.2f}" if volume_h24 is not None else "N/A"
            if not passes_volume:
                 reasons.append(f"Volume 24H ({volume_str}) < Min ({min_volume_str})")
            
            failure_reason_str = ", ".join(reasons)
            self.logger.info(f"Token {mint} ({symbol}) failed pre-qualification. Reasons: {failure_reason_str}")
            return False
    # --- END NEW ---

    async def _get_token_age_minutes(self, pair_created_at: Optional[int]) -> Optional[float]:
        """Calculates token age in minutes from pair_created_at timestamp."""
        if pair_created_at is None:
            return None
        created_at_dt = datetime.fromtimestamp(pair_created_at / 1000, tz=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        age_delta = now_utc - created_at_dt
        return age_delta.total_seconds() / 60

    async def _update_best_token_selection(self) -> None:
        """
        Identifies and updates the system's 'best token' for focused monitoring and potential trading.
        This involves querying the database for the highest-scoring token that meets all criteria.
        If a new best token is found, or if no token is currently monitored, it updates
        MarketData to start/switch monitoring to this new token.
        """
        self.logger.info("Attempting to update best token selection...")
        try:
            # MODIFIED: Call get_best_token_for_trading with include_inactive_tokens=True
            self.logger.debug("Calling self.db.get_best_token_for_trading(include_inactive_tokens=True)") # ADDED
            best_token_candidate = await self.db.get_best_token_for_trading(include_inactive_tokens=True)
            self.logger.debug(f"get_best_token_for_trading returned: {best_token_candidate}") # ADDED
            
            if best_token_candidate:
                # ADDED detailed logging for candidate properties
                self.logger.info(
                    f"Best token candidate from DB: {best_token_candidate.mint} "
                    f"with score {getattr(best_token_candidate, 'overall_score', 'N/A')}, "
                    f"status {best_token_candidate.monitoring_status}, "
                    f"filter_passed: {best_token_candidate.overall_filter_passed}, "
                    f"pair_address: {best_token_candidate.pair_address}, "
                    f"dex_id: {best_token_candidate.dex_id}"
                )
                
                current_mint_details = None
                if hasattr(self, 'current_monitored_mint') and self.current_monitored_mint and self.current_monitored_mint == best_token_candidate.mint: # ADDED hasattr check
                    current_mint_details = self.market_data.get_realtime_pair_state(self.current_monitored_mint)
                    self.logger.debug(f"Current monitored token {self.current_monitored_mint} is the same as candidate. Details: {current_mint_details}") # ADDED
                elif hasattr(self, 'current_monitored_mint'): # ADDED hasattr check
                    self.logger.debug(f"Current monitored token is: {self.current_monitored_mint}")
                else:
                    self.logger.debug("No current_monitored_mint attribute found or it's None.")


                # Condition to switch:
                # 1. No token is currently monitored OR
                # 2. The new candidate is different from the current one AND
                #    (The new candidate has a better score OR the current one has become invalid/untradeable)
                #    (For now, simpler: switch if different and new one is valid. Score comparison can be added)
                
                switch_to_new_token = False
                # ADDED hasattr check for self.current_monitored_mint
                if not hasattr(self, 'current_monitored_mint') or self.current_monitored_mint is None:
                    self.logger.info(f"No token currently monitored. Selecting {best_token_candidate.mint} as the best token.")
                    switch_to_new_token = True
                elif self.current_monitored_mint != best_token_candidate.mint:
                    self.logger.info(f"New best token candidate {best_token_candidate.mint} is different from current {self.current_monitored_mint}.")
                    # Add more sophisticated comparison logic here if needed (e.g., score, status of current)
                    # For now, if a new valid candidate is found and it's different, we consider switching.
                    if best_token_candidate.overall_filter_passed and best_token_candidate.pair_address and best_token_candidate.dex_id:
                         self.logger.info(f"Switching from {self.current_monitored_mint} to {best_token_candidate.mint} because it passed filters and has pair/dex info.") # MODIFIED
                         switch_to_new_token = True
                    else:
                        self.logger.warning(
                            f"New best token candidate {best_token_candidate.mint} is not suitable for monitoring "
                            f"(filter_passed: {best_token_candidate.overall_filter_passed}, "
                            f"pair_address: {best_token_candidate.pair_address}, "
                            f"dex_id: {best_token_candidate.dex_id}). Retaining {self.current_monitored_mint}."
                        )
                else:
                    self.logger.info(f"Current best token {self.current_monitored_mint} is the same as candidate. No change needed.") # MODIFIED


                if switch_to_new_token:
                    self.logger.info(f"Proceeding to switch. MarketData available: {True if self.market_data else False}") # ADDED
                    if self.market_data:
                        # Stop monitoring the old token if one exists and is different
                        # ADDED hasattr check for self.current_monitored_mint
                        if hasattr(self, 'current_monitored_mint') and self.current_monitored_mint and self.current_monitored_mint != best_token_candidate.mint:
                            self.logger.info(f"Stopping monitoring for previous best token: {self.current_monitored_mint}")
                            await self.market_data.stop_monitoring_token(self.current_monitored_mint)
                            await self.db.update_token_monitoring_status(self.current_monitored_mint, "stopped")
                            self.logger.info(f"Previous token {self.current_monitored_mint} monitoring stopped and status updated to 'stopped'.") # ADDED

                        self.logger.info(f"Adding new best token {best_token_candidate.mint} (Pair: {best_token_candidate.pair_address}, DEX: {best_token_candidate.dex_id}) for monitoring.")
                        
                        # Ensure pair_address and dex_id are present before adding
                        if not best_token_candidate.pair_address or not best_token_candidate.dex_id:
                            self.logger.error(f"Cannot monitor token {best_token_candidate.mint}: missing pair_address ('{best_token_candidate.pair_address}') or dex_id ('{best_token_candidate.dex_id}'). Monitoring will not start for this token.") # MODIFIED
                            # Potentially mark the token as invalid or requiring attention in DB
                            return 

                        # Add token for monitoring via MarketData
                        # This call might involve fetching initial state, subscribing to WebSocket updates, etc.
                        self.logger.debug(f"Calling market_data.add_token_for_monitoring for {best_token_candidate.mint}") # ADDED
                        success_monitoring = await self.market_data.add_token_for_monitoring(
                            mint=best_token_candidate.mint,
                            pair_address=best_token_candidate.pair_address,
                            dex_id=best_token_candidate.dex_id # Pass dex_id
                        )
                        self.logger.debug(f"market_data.add_token_for_monitoring returned: {success_monitoring} for {best_token_candidate.mint}") # ADDED
                        
                        if success_monitoring:
                            self.current_monitored_mint = best_token_candidate.mint
                            self.current_monitored_pair_address = best_token_candidate.pair_address
                            self.current_monitored_dex_id = best_token_candidate.dex_id
                            # Update monitoring status in DB
                            await self.db.update_token_monitoring_status(best_token_candidate.mint, "active")
                            self.logger.info(f"Successfully started monitoring new best token: {best_token_candidate.mint} on DEX {best_token_candidate.dex_id} with pair {best_token_candidate.pair_address}. Status set to 'active'.")
                        else:
                            self.logger.error(f"Failed to start monitoring for new best token candidate: {best_token_candidate.mint}. It will not be set as current_monitored_mint.")
                            # Consider setting status to 'error' or 'pending_retry' in DB
                            await self.db.update_token_monitoring_status(best_token_candidate.mint, "monitoring_failed")
                            self.logger.info(f"Token {best_token_candidate.mint} status updated to 'monitoring_failed'.") # ADDED

                    else:
                        self.logger.warning("MarketData component not available. Cannot update token monitoring.")
                # If not switching, but a candidate exists, ensure its status is updated if it was 'pending' and meets criteria
                elif best_token_candidate and best_token_candidate.monitoring_status == 'pending' and best_token_candidate.overall_filter_passed:
                     self.logger.info(f"Best token candidate {best_token_candidate.mint} is 'pending' and passed filters, but no switch decision made. Current status: {best_token_candidate.monitoring_status}") # ADDED
                     # This case might be redundant if the above logic correctly makes it active,
                     # but can serve as a fallback if a token is best but not chosen for active switch.
                     # For now, we primarily rely on the switch_to_new_token logic to activate.
                     pass
                else: # ADDED for clarity on why no switch happened
                    self.logger.info(f"No switch to new token decision made. switch_to_new_token: {switch_to_new_token}, Candidate: {best_token_candidate.mint if best_token_candidate else 'None'}")


            else: # No best_token_candidate found
                self.logger.info("No suitable token candidate found by get_best_token_for_trading(include_inactive_tokens=True).")
                # If a token was previously monitored, consider stopping it or letting it continue
                # ADDED hasattr check for self.current_monitored_mint
                if hasattr(self, 'current_monitored_mint') and self.current_monitored_mint:
                    self.logger.info(f"Continuing to monitor existing token: {self.current_monitored_mint} as no better alternative was found.")
                    # Or, optionally, stop monitoring if no good candidates exist anymore:
                    # self.logger.info(f\"No suitable tokens found. Stopping monitoring for {self.current_monitored_mint}\")
                    # await self.market_data.stop_monitoring_token(self.current_monitored_mint)
                    # await self.token_db.update_token_monitoring_status(self.current_monitored_mint, "stopped_no_candidate")
                    # self.current_monitored_mint = None
                    # self.current_monitored_pair_address = None
                    # self.current_monitored_dex_id = None
                else: # ADDED
                    self.logger.info("No current token is being monitored, and no new candidate found.")


        except Exception as e:
            self.logger.error(f"Error in _update_best_token_selection: {e}", exc_info=True)
