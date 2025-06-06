import logging
from typing import Dict, Any, Optional, Tuple
import httpx
from solana.rpc.async_api import AsyncClient # Import AsyncClient
from datetime import datetime, timezone # Ensure datetime is imported
import asyncio
from math import isclose

from config import Settings, Thresholds, FiltersConfig
from data.token_database import TokenDatabase # Assuming DB access class
from data.price_monitor import PriceMonitor # Import PriceMonitor

# Import API Clients passed from main.py
from config.rugcheck_api import RugcheckAPI
from .solsniffer_api import SolsnifferAPI
from .twitter_check import TwitterCheck

# Import Filter Classes
from .blacklist import Blacklist
from .bonding_curve import BondingCurveCalculator
from .dump_filter import DumpFilter
from .liquidity_filter import LiquidityFilter
from .moonshot_filter import MoonshotFilter
from .rugcheck_filter import RugcheckFilter
from .scam_filter import ScamFilter
from .social_filter import SocialFilter # Needs TwitterCheck/API
# NOTE: This import will fail until filters/solsniffer_filter.py is created
from .solsniffer_filter import SolsnifferFilter # Needs SolsnifferAPI
from .volume_filter import VolumeFilter
from .whale_filter import WhaleFilter
from .whitelist import WhitelistFilter
from .blacklist import BlacklistFilter
# TODO: Add imports for any other filters like DevWalletActivityFilter if needed

logger = logging.getLogger(__name__)

class FilterManager:
    """
    Orchestrates the application of various filters to tokens based on configuration.
    Annotates tokens with filter results and persists them to the database.
    Provides a single interface for applying filters during initial scan and monitoring.
    """
    def __init__(self, 
                 settings: Settings, 
                 thresholds: Thresholds, 
                 filters_config: FiltersConfig,
                 db: TokenDatabase,
                 http_client: httpx.AsyncClient,
                 solana_client: AsyncClient, 
                 price_monitor: PriceMonitor, 
                 rugcheck_api: RugcheckAPI,
                 solsniffer_api: SolsnifferAPI,
                 twitter_check: TwitterCheck):
        """
        Initializes the FilterManager with necessary configurations, database, clients, and price monitor.
        """
        self.settings = settings
        self.thresholds = thresholds
        self.filters_config = filters_config
        self.db = db
        self.http_client = http_client
        self.solana_client = solana_client
        self.price_monitor = price_monitor
        self.rugcheck_api = rugcheck_api
        self.solsniffer_api = solsniffer_api
        self.twitter_check = twitter_check
        
        self.filters: Dict[str, Optional[Any]] = {}
        self._initialize_filters()
        logger.info(f"FilterManager initialized with filters: {list(f for f in self.filters if self.filters[f] is not None)}")

    def _initialize_filters(self):
        """Initializes and stores filter instances based on configuration."""
        logger.info("Initializing filters...")
        # Example: Iterate through a config that specifies which filters to enable
        # and what their settings are. For now, let's assume all imported filters
        # are potentially active if their config says so.

        # Note: self.filters_config.enabled_filters might be a dict or list from FiltersConfig
        # For simplicity, we'll check if a filter is enabled via self.filters_config.is_enabled(filter_name)
        # or by looking up specific config sections. This is a placeholder for actual config structure.

        filter_classes = {
            "whitelist": WhitelistFilter,
            "blacklist": BlacklistFilter,
            "rugcheck": RugcheckFilter,
            "solsniffer": SolsnifferFilter,
            "scam": ScamFilter,
            "liquidity": LiquidityFilter,
            "volume": VolumeFilter,
            "dump": DumpFilter,
            "whale": WhaleFilter,
            "bonding_curve": BondingCurveCalculator, # Note: This is a calculator, might be used differently
            "social": SocialFilter,
            "moonshot": MoonshotFilter,
            # Add other filter_name -> FilterClass mappings here
        }

        for filter_name, FilterClass in filter_classes.items():
            # Check if filter is enabled in settings (using proper env variables)
            is_enabled = False
            if filter_name == "liquidity":
                is_enabled = getattr(self.settings, 'FILTER_LIQUIDITY_ENABLED', False)
            elif filter_name == "volume":
                is_enabled = getattr(self.settings, 'FILTER_VOLUME_ENABLED', False)
            elif filter_name == "rugcheck":
                is_enabled = getattr(self.settings, 'FILTER_RUGCHECK_ENABLED', False)
            elif filter_name == "solsniffer":
                is_enabled = getattr(self.settings, 'FILTER_SOLSNIFFER_ENABLED', False)
            elif filter_name == "social":
                is_enabled = getattr(self.settings, 'FILTER_SOCIAL_ENABLED', False)
            elif filter_name == "scam":
                is_enabled = getattr(self.settings, 'FILTER_SCAM_ENABLED', False)
            elif filter_name == "dump":
                is_enabled = getattr(self.settings, 'FILTER_DUMP_ENABLED', False)
            elif filter_name == "whale":
                is_enabled = getattr(self.settings, 'FILTER_WHALE_ENABLED', False)
            elif filter_name == "moonshot":
                is_enabled = getattr(self.settings, 'FILTER_MOONSHOT_ENABLED', False)
            elif filter_name == "whitelist":
                is_enabled = getattr(self.settings, 'FILTER_WHITELIST_ENABLED', False)
            elif filter_name == "blacklist":
                is_enabled = getattr(self.settings, 'FILTER_BLACKLIST_ENABLED', False)
            elif filter_name == "bonding_curve":
                is_enabled = getattr(self.settings, 'FILTER_BONDING_CURVE_ENABLED', False)
            else:
                # Unknown filter, default to disabled unless in debug mode
                is_enabled = False

            if is_enabled or getattr(self.settings, 'LOG_LEVEL', 'INFO') == 'DEBUG': # Enable all in debug mode for testing
                try:
                    logger.debug(f"Attempting to initialize filter: {filter_name} (enabled: {is_enabled}, debug_mode: {getattr(self.settings, 'LOG_LEVEL', 'INFO') == 'DEBUG'})")
                    if filter_name == "whitelist":
                        self.filters[filter_name] = FilterClass(settings=self.settings)
                    elif filter_name == "blacklist":
                        # BlacklistFilter takes (db, settings)
                        self.filters[filter_name] = FilterClass(db=self.db, settings=self.settings) 
                    elif filter_name == "rugcheck":
                        # RugcheckFilter takes (rugcheck_api, settings) - NO thresholds
                        self.filters[filter_name] = FilterClass(rugcheck_api=self.rugcheck_api, settings=self.settings)
                    elif filter_name == "solsniffer":
                        # SolsnifferFilter takes (settings, solsniffer_api) - NO thresholds
                        self.filters[filter_name] = FilterClass(settings=self.settings, solsniffer_api=self.solsniffer_api)
                    elif filter_name == "scam":
                        self.filters[filter_name] = FilterClass(logging_level=self.settings.LOG_LEVEL)
                    elif filter_name == "liquidity":
                        # LiquidityFilter takes (settings, logging_level) - NO thresholds/price_monitor/db
                        self.filters[filter_name] = FilterClass(settings=self.settings, logging_level=self.settings.LOG_LEVEL)
                    elif filter_name == "volume":
                        # VolumeFilter takes (settings) - NO thresholds/price_monitor
                        self.filters[filter_name] = FilterClass(settings=self.settings)
                    elif filter_name == "dump":
                        # DumpFilter takes (settings, logging_level) - NO thresholds/price_monitor
                        self.filters[filter_name] = FilterClass(settings=self.settings, logging_level=self.settings.LOG_LEVEL)
                    elif filter_name == "whale":
                        # WhaleFilter takes (settings) - NO db/solana_client/price_monitor/thresholds
                        self.filters[filter_name] = FilterClass(settings=self.settings)
                    elif filter_name == "bonding_curve":
                        # BondingCurveCalculator needs solana_client, settings
                        self.filters[filter_name] = FilterClass(solana_client=self.solana_client, settings=self.settings)
                    elif filter_name == "social":
                        # SocialFilter needs settings and twitter_check
                        self.filters[filter_name] = FilterClass(settings=self.settings, twitter_check=self.twitter_check)
                    elif filter_name == "moonshot":
                        # MoonshotFilter needs only settings
                        self.filters[filter_name] = FilterClass(settings=self.settings)
                    else:
                        # Generic instantiation if no special parameters are known
                        # This might fail if the filter requires specific args not provided here.
                        logger.warning(f"Filter '{filter_name}' does not have specific initialization logic, attempting generic init.")
                        self.filters[filter_name] = FilterClass() 

                    if self.filters.get(filter_name):
                         logger.info(f"Successfully initialized filter: {filter_name}")
                    else:
                        logger.warning(f"Filter {filter_name} was attempted but not stored. Check its init logic or enabled status.")

                except Exception as e:
                    logger.error(f"Failed to initialize filter '{filter_name}': {e}", exc_info=True)
                    self.filters[filter_name] = None # Mark as failed to initialize
            else:
                logger.info(f"Filter '{filter_name}' is DISABLED (FILTER_{filter_name.upper()}_ENABLED=False). Skipping initialization.")
                self.filters[filter_name] = None

    async def close(self):
        logger.info("Closing FilterManager and its managed filters...")
        for filter_instance in self.filters.values():
            if hasattr(filter_instance, 'close') and callable(filter_instance.close):
                try:
                    await filter_instance.close()
                    logger.info(f"Closed filter: {filter_instance.__class__.__name__}")
                except Exception as e:
                    logger.error(f"Error closing filter {filter_instance.__class__.__name__}: {e}", exc_info=True)
        logger.info("FilterManager closed.")

    async def apply_filters(self, token_data: Dict[str, Any], current_time: Optional[datetime] = None, initial_scan: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Applies enabled filters to the token data, annotates it, and saves results.
        Includes optimization for initial scan phase.

        Args:
            token_data: Dict containing token info (will be mutated with results).
            current_time: Optional current time for filters that might need it.
            initial_scan: If True, enables early exit after critical filter failures.

        Returns:
            The input token_data dictionary annotated with a 'filter_results' key. 
            Also includes 'analysis_status' ('complete' or 'aborted_early').
        """
        # Fetch current SOL price before the loop
        sol_price_usd = 0.0
        try:
            sol_price_usd = await self.price_monitor.get_sol_price()
            if sol_price_usd is None:
                 sol_price_usd = 0.0
                 logger.warning("Could not retrieve current SOL price for bonding curve calculation.")
        except Exception as e:
            logger.error(f"Error fetching SOL price from PriceMonitor: {e}", exc_info=True)
            # Handle error appropriately, maybe skip bonding curve filter or use default

        mint = token_data.get("mint") # Get mint from token_data
        if not mint:
            logger.error("Mint address not found in token_data for apply_filters.")
            # Decide how to handle this - perhaps return an error or the token_data as is with an error note.
            token_data['filter_results'] = {"error": "Missing mint address"}
            token_data['analysis_status'] = 'error'
            token_data['overall_filter_passed'] = False
            return token_data # Return modified token_data

        logger.debug(f"Applying filters to token {mint} (SOL Price: ${sol_price_usd:.2f}, Initial Scan: {initial_scan})")
        filter_results = token_data.get('filter_results', {}) # Preserve previous results if any
        analysis_status = 'complete'
        overall_filter_passed = True # Assume passing unless a filter fails

        # --- Verification Needed --- 
        # 3. Which filters are 'critical' for early exit during initial scan?
        #    Using rugcheck, solsniffer, blacklist as examples.
        critical_filters_for_early_exit = ['rugcheck', 'blacklist', 'solsniffer']

        # Ensure essential data from DexScreener (or earlier stages) is present for filters
        # These might already be populated by TokenScanner._prepare_token_for_db
        if 'symbol' not in token_data:
             token_data['symbol'] = token_data.get('baseToken', {}).get('symbol') or token_data.get('name', 'Unknown')
        if 'liquidity' not in token_data: # Ensure top-level liquidity (expecting USD value)
            liquidity_data = token_data.get('liquidity', {})
            token_data['liquidity'] = liquidity_data.get('usd', 0.0) if isinstance(liquidity_data, dict) else 0.0
        if 'marketCap' not in token_data: # Ensure top-level marketCap (expecting USD value)
             token_data['marketCap'] = token_data.get('marketCap', 0.0) # Check top level first
             if isinstance(token_data['marketCap'], dict): # If it's a dict, try getting 'usd'
                 token_data['marketCap'] = token_data['marketCap'].get('usd', 0.0)
             elif not isinstance(token_data['marketCap'], (float, int)):
                 token_data['marketCap'] = 0.0 # Default to 0 if not a number
        
        logger.debug(f"Pre-filter token_data prep for {mint}: Symbol='{token_data.get('symbol')}', Liq='{token_data.get('liquidity')}', MCAP='{token_data.get('marketCap')}'")

        # Iterate through instantiated filters
        # --- Define the order filters should run (example) ---
        # Critical checks first, then informational/scoring
        filter_order = [
            'blacklist',
            'whitelist',
            'rugcheck',
            'solsniffer',
            'scam', # Assuming scam filter is critical
            'liquidity',
            'volume',
            'dump',
            'whale',
            'bonding_curve', 
            'social', 
            'moonshot',
            # Add others in desired order
        ]
        
        # Create a map for quick lookup
        enabled_filters_map = {name: inst for name, inst in self.filters.items() if inst}
        
        for name in filter_order:
            filter_instance = enabled_filters_map.get(name)
            if filter_instance:
                # Skip if already processed in a previous partial run
                # Check if analysis result key exists, not just filter name
                analysis_key = f"{name}_analysis" if name not in ['bonding_curve'] else 'bonding_curve' # Special case for bonding curve key?
                # TODO: Standardize result key naming across all filters
                if analysis_key in token_data:
                    logger.debug(f"Skipping filter '{name}' for {mint} as results key '{analysis_key}' already exists.")
                    continue
                    
                logger.debug(f"Applying filter '{name}' to {mint}...")
                try:
                    # Determine the method to call (Prioritize analyze_token)
                    method_to_call = None
                    method_type = None # To track how to call it
                    
                    # --- Determine Filter Method and Type ---
                    if hasattr(filter_instance, 'get_bonding_curve_metrics'):
                        method_to_call = filter_instance.get_bonding_curve_metrics
                        method_type = 'bonding_curve' # Specific handling: Needs mint, sol_price
                    elif hasattr(filter_instance, 'analyze_and_annotate'):
                        method_to_call = filter_instance.analyze_and_annotate
                        method_type = 'annotate_list' # Expects list, modifies in place
                    elif hasattr(filter_instance, 'apply'):
                         # WhitelistFilter uses 'apply' but expects a list
                         method_to_call = filter_instance.apply
                         method_type = 'apply_list' # Expects list, modifies in place
                    elif hasattr(filter_instance, 'analyze_token'): 
                        method_to_call = filter_instance.analyze_token
                        method_type = 'single_token' # Expects dict, returns result
                    elif hasattr(filter_instance, 'check'): 
                        method_to_call = filter_instance.check
                        method_type = 'single_token' # Assume expects dict, returns result
                    elif hasattr(filter_instance, 'analyze'): 
                        method_to_call = filter_instance.analyze
                        method_type = 'single_token' # Assume expects dict, returns result
                    elif hasattr(filter_instance, 'evaluate'): 
                        method_to_call = filter_instance.evaluate
                        method_type = 'single_token' # Assume expects dict, returns result
                    elif hasattr(filter_instance, 'calculate_risk_score'): 
                        method_to_call = filter_instance.calculate_risk_score
                        method_type = 'single_token_addr' # Needs address string

                    result = None # Initialize result
                    if method_to_call:
                        # Determine arguments and call method based on type
                        if method_type == 'bonding_curve':
                            # Only run bonding curve analysis on PumpFun/PumpSwap tokens
                            token_dex_id = token_data.get('dex_id', '').lower()
                            if token_dex_id in ['pumpfun', 'pumpswap']:
                                if sol_price_usd > 0: 
                                    result = await method_to_call(mint, sol_price_usd) # Pass mint string, price
                                else:
                                    result = {"status": "error", "message": "Skipped due to missing SOL price"}
                            else:
                                result = {"status": "skipped", "message": f"Bonding curve analysis only applies to PumpFun/PumpSwap tokens, not {token_dex_id}"}
                                logger.debug(f"Skipping bonding curve analysis for {mint} - not a PumpFun/PumpSwap token (dex_id: {token_dex_id})")
                        elif method_type == 'single_token_addr':
                            result = await method_to_call(mint) # Pass mint string
                        elif method_type in ('annotate_list', 'apply_list'):
                            # Ensure it's called with the current token_data
                            await method_to_call([token_data])
                            # Result is now IN token_data, extract the specific analysis part
                            # Standardize the key name later!
                            result_key = f"{name}_analysis" if name not in ['bonding_curve', 'blacklist', 'whitelist'] else name
                            result = token_data.get(result_key, {"status":"annotated_in_place"}) 
                        elif method_type == 'single_token':
                            # Pass the potentially updated token_data
                            result = await method_to_call(token_data)
                            
                        # Store the result in filter_results (standardized key)
                        filter_results[name] = result
                        logger.debug(f"Filter '{name}' applied to {mint}. Result: {result}")
                        
                        # --- Market Cap Comparison Logic (After bonding_curve filter) ---
                        if name == 'bonding_curve' and result and result.get('status') == 'success':
                            dex_mcap = token_data.get('marketCap', 0.0) # Get DexScreener MCAP 
                            # Ensure dex_mcap is float/int
                            if not isinstance(dex_mcap, (float, int)):
                                 dex_mcap = 0.0
                                 
                            bonding_mcap = result.get('market_cap', 0.0)
                            # Ensure bonding_mcap is float/int
                            if not isinstance(bonding_mcap, (float, int)):
                                 bonding_mcap = 0.0

                            # Add mismatch flag if difference > 25% and both > 0
                            mismatch = False
                            if dex_mcap > 0 and bonding_mcap > 0:
                                 diff_percent = abs(dex_mcap - bonding_mcap) / dex_mcap
                                 if diff_percent > 0.25:
                                     mismatch = True
                                     logger.warning(f"MCAP Mismatch for {mint}: DexScreener (${dex_mcap:,.2f}) vs BondingCurve (${bonding_mcap:,.2f}) > 25%")
                            # Store the flag within the bonding_curve results
                            result['mcap_dex_bonding_mismatch'] = mismatch
                        # --- End Market Cap Comparison Logic ---

                        # Check for early exit if a critical filter failed
                        if initial_scan and name in critical_filters_for_early_exit:
                            # How to check failure? Assume a 'flagged' or 'failed' key in result dict
                            is_failed = False
                            if isinstance(result, dict):
                                is_failed = result.get('flagged', False) or result.get('status') == 'error' or result.get('failed', False)
                                # Specific check for blacklist filter if its result is just a boolean True
                                if name == 'blacklist' and result is True:
                                     is_failed = True
                                     
                            if is_failed:
                                logger.warning(f"Critical filter '{name}' failed for {mint} during initial scan. Aborting further analysis.")
                                analysis_status = 'aborted_early'
                                overall_filter_passed = False # Mark as failed overall
                                break # Exit the filter loop for this token
                        
                        # Check if *any* filter flagged the token
                        if isinstance(result, dict) and result.get('flagged', False):
                            overall_filter_passed = False
                        elif name == 'blacklist' and result is True: # Specific blacklist check
                            overall_filter_passed = False

                    else:
                        logger.warning(f"No suitable analysis method found for filter '{name}'. Skipping.")

                except Exception as e:
                    logger.error(f"Error applying filter '{name}' to {mint}: {e}", exc_info=True)
                    # Store error information in results
                    filter_results[name] = {"status": "error", "message": str(e)}
                    # Decide if this error constitutes overall failure
                    if name in critical_filters_for_early_exit: 
                        overall_filter_passed = False
                        if initial_scan: 
                            analysis_status = 'aborted_early'
                            logger.warning(f"Critical filter '{name}' errored for {mint} during initial scan. Aborting further analysis.")
                            break # Exit loop on critical error during initial scan

        # Add final results and status back to the main token_data dictionary
        token_data['filter_results'] = filter_results
        token_data['analysis_status'] = analysis_status
        token_data['overall_filter_passed'] = overall_filter_passed # Store the final pass/fail status
        token_data['last_filter_update'] = datetime.now(timezone.utc) # Record when filters were last run
        
        # Don't save to DB here, let TokenScanner handle batch saving
        # await self._save_filter_results(mint, filter_results)
        
        logger.debug(f"Finished applying filters for {mint}. Overall passed: {overall_filter_passed}, Status: {analysis_status}")
        return token_data

    async def _save_filter_results(self, mint: str, results: Dict[str, Any]):
        """Saves the filter results for a token to the database."""
        # This should likely be handled by TokenScanner after all processing is done
        # to allow for batch updates/inserts.
        logger.warning("_save_filter_results is deprecated in FilterManager. Saving should be handled by TokenScanner.")
        pass 
        # try:
        #     # Example: Update a specific JSON field or dedicated columns
        #     # This requires knowing the database schema and how results are stored
        #     update_data = {
        #         'filter_results_json': json.dumps(results, default=str), 
        #         'last_filtered_at': datetime.now(timezone.utc)
        #         # Potentially add overall_passed flag here?
        #     }
        #     await self.db.update_token_filter_data(mint, update_data) 
        #     logger.debug(f"Saved filter results for token {mint}")
        # except Exception as e:
        #     logger.error(f"Failed to save filter results for {mint}: {e}")

# We need to create filters/solsniffer_filter.py with the SolSnifferFilter class.
# We also need to verify the apply method signature and logic of filters/twitter_check.py.

# Example usage (for testing, remove later)
# if __name__ == '__main__':
#     # Need mock objects for settings, thresholds, etc. to test
#     pass 