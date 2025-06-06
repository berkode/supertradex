import os
import asyncio
import logging
import json
from datetime import datetime, timezone, time, timedelta
import time as _time
from typing import Dict, List, Optional, Any, Set, TYPE_CHECKING
import pandas as pd
import httpx

from config.settings import Settings
from config.logging_config import LoggingConfig
from config.dexscreener_api import DexScreenerAPI
from utils.logger import get_logger
from config.blockchain_logging import setup_price_monitoring_logger
from data.jupiter_price_parser import JupiterPriceParser
from data.raydium_price_parser import RaydiumPriceParser

# Configure logging using centralized config
# LoggingConfig.setup_logging()
logger = get_logger(__name__)

# Get dedicated price monitoring logger
price_logger = setup_price_monitoring_logger("PriceMonitor")

# Assuming TokenDatabase might be needed later, adjust path if necessary
# from .token_database import TokenDatabase

# Load environment variables from .env
# Adjust path relative to this file's location if needed
# load_dotenv(dotenv_path='../config/.env')

# Configure logging (ensure logger name consistency if desired)
# log_file = os.getenv("LOG_FILE", "price_monitor.log")
# log_level = os.getenv("LOG_LEVEL", "INFO").upper()
# enable_console = os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true"

# Basic logging setup (consider moving to a central logging config)
# log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Avoid adding handlers multiple times if logger is already configured
# if not logger.handlers:
#     file_handler = logging.FileHandler(log_file)
#     file_handler.setFormatter(log_formatter)
#     logger.addHandler(file_handler)
#     if enable_console:
#         stream_handler = logging.StreamHandler()
#         stream_handler.setFormatter(log_formatter)
#         logger.addHandler(stream_handler)
#     logger.setLevel(getattr(logging, log_level, logging.INFO))

if TYPE_CHECKING:
    from config.settings import Settings # Use for type hints only
    from data.token_database import TokenDatabase

# --- Constants ---
SOLANA_DECIMALS = 9
USDC_DECIMALS = 6

# --- Rate limiting exception handling ---
def is_rate_limit_error(e: Exception) -> bool:
    """Helper to detect rate limiting errors."""
    return (isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429) or \
           "rate limit" in str(e).lower()

class PriceMonitor:
    """
    Enhanced PriceMonitor with smart API routing and SOL-based pricing.
    
    Features:
    - Smart DEX routing: Raydium tokens -> RaydiumPriceParser, Others -> JupiterPriceParser
    - SOL-first pricing with USD conversion for display
    - Clean price monitoring logs (price_monitor.log)
    - Fallback mechanisms for reliability
    """
    def __init__(self, settings: 'Settings', dex_api_client: DexScreenerAPI, http_client: httpx.AsyncClient, db: 'TokenDatabase' = None):
        """
        Initializes the Enhanced PriceMonitor.

        Args:
            settings: The global application settings object. MUST be provided.
            dex_api_client: An initialized DexScreenerAPI client instance. MUST be provided.
            http_client: An initialized httpx.AsyncClient instance. MUST be provided.
            db: Optional instance of TokenDatabase for storing/retrieving token data.
        """
        if settings is None:
             logger.error("PriceMonitor initialized without a Settings object. This is required.")
             raise ValueError("PriceMonitor requires a valid Settings object.")
        if dex_api_client is None:
            logger.error("PriceMonitor initialized without a DexScreenerAPI client. This is required.")
            raise ValueError("PriceMonitor requires a valid DexScreenerAPI client.")
        if http_client is None:
            logger.error("PriceMonitor initialized without an httpx.AsyncClient. This is required.")
            raise ValueError("PriceMonitor requires a valid httpx.AsyncClient.")

        self.settings = settings
        self.db = db
        self.dex_api_client = dex_api_client
        self.http_client = http_client

        # Enhanced API parsers for smart routing
        self.jupiter_parser = JupiterPriceParser(settings, logger, http_client)
        self.raydium_parser = RaydiumPriceParser(settings, logger)
        
        # Existing attributes
        self._token_prices: Dict[str, float] = {}  # Will store SOL prices
        self._token_prices_usd: Dict[str, float] = {}  # USD prices for display
        self._token_data_cache: Dict[str, Dict[str, Any]] = {}
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}
        self._stop_event = asyncio.Event()
        self._active_monitors: Set[str] = set()
        self.price_history: Dict[str, List[Dict[str, Any]]] = {}
        self.max_history_length = self.settings.MAX_PRICE_HISTORY
        self.poll_interval = self.settings.PRICEMONITOR_INTERVAL
        self._sol_price_cache: Optional[float] = None
        self._sol_price_last_updated: Optional[datetime] = None
        self._sol_price_cache_ttl = timedelta(seconds=self.settings.SOL_PRICE_CACHE_DURATION)
        self.tokens_being_monitored: Set[str] = set()
        self.active_tokens_details: Dict[str, Dict[str, Any]] = {}
        
        # Token routing cache (mint -> dex_id)
        self._token_dex_routing: Dict[str, str] = {}
        
        # Pricing statistics
        self._pricing_stats = {
            'jupiter_requests': 0,
            'raydium_requests': 0,
            'fallback_requests': 0,
            'successful_updates': 0,
            'failed_updates': 0,
            'last_update_time': None
        }

    async def initialize(self) -> bool:
        """
        Initialize the Enhanced PriceMonitor instance.
        Sets up Jupiter and Raydium parsers.
        
        Returns:
            bool: True if initialization was successful, False otherwise.
        """
        try:
            logger.info("Initializing Enhanced PriceMonitor with smart API routing...")
            
            # Initialize API parsers
            jupiter_init = await self.jupiter_parser.initialize()
            raydium_init = await self.raydium_parser.initialize()
            
            if not jupiter_init:
                logger.warning("Failed to initialize Jupiter parser - will fallback to DexScreener")
            if not raydium_init:
                logger.warning("Failed to initialize Raydium parser - will fallback to Jupiter")
            
            # Validate injected DexScreenerAPI client
            if not self.dex_api_client:
                logger.error("DexScreenerAPI client not provided during initialization.")
                return False

            # Update SOL price cache
            await self._update_sol_price_cache()
                
            logger.info(f"Enhanced PriceMonitor initialized. Poll Interval: {self.poll_interval}s, Max History: {self.max_history_length}.")
            price_logger.info("🚀 Enhanced PriceMonitor started with smart API routing (Raydium → Raydium API, Others → Jupiter API)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Enhanced PriceMonitor: {e}", exc_info=True)
            return False

    async def close(self):
        """Stops monitoring and cleans up resources."""
        logger.info("Closing Enhanced PriceMonitor...")
        self._stop_event.set()
        
        # Close API parsers
        try:
            await self.jupiter_parser.close()
            await self.raydium_parser.close()
        except Exception as e:
            logger.warning(f"Error closing API parsers: {e}")
        
        # Cancel all monitoring tasks
        cancelled_tasks = []
        tasks_to_cancel = list(self._monitoring_tasks.values())
        self._monitoring_tasks.clear()

        for task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                cancelled_tasks.append(task)

        if cancelled_tasks:
            await asyncio.gather(*cancelled_tasks, return_exceptions=True)
            logger.info(f"Gathered results for {len(cancelled_tasks)} cancelled monitoring tasks.")

        # Clear caches and active monitors
        self._token_prices.clear()
        self._token_prices_usd.clear()
        self._token_data_cache.clear()
        self._active_monitors.clear()
        self._token_dex_routing.clear()
        
        price_logger.info("📊 Enhanced PriceMonitor closed - Final stats: " + 
                         f"Jupiter: {self._pricing_stats['jupiter_requests']}, " +
                         f"Raydium: {self._pricing_stats['raydium_requests']}, " +
                         f"Success: {self._pricing_stats['successful_updates']}, " +
                         f"Failed: {self._pricing_stats['failed_updates']}")
        logger.info("Enhanced PriceMonitor closed successfully.")

    def _determine_api_route(self, mint: str, dex_id: Optional[str] = None) -> str:
        """
        Determine which API to use for pricing based on smart DEX routing.
        
        Args:
            mint: Token mint address
            dex_id: Optional DEX identifier
            
        Returns:
            str: 'raydium' for Raydium tokens, 'jupiter' for others
        """
        # Check cache first
        if mint in self._token_dex_routing:
            cached_dex = self._token_dex_routing[mint]
            if cached_dex in ['raydium_v4', 'raydium_clmm', 'raydium']:
                return 'raydium'
            else:
                return 'jupiter'
        
        # Use provided dex_id
        if dex_id:
            self._token_dex_routing[mint] = dex_id
            if dex_id in ['raydium_v4', 'raydium_clmm', 'raydium']:
                return 'raydium'
            else:
                return 'jupiter'
        
        # Check database for dex_id (synchronous check)
        if self.db:
            try:
                # Get token info from database to determine DEX
                # Note: This is a synchronous call - in real async implementation
                # we'd need to make this method async or cache the results
                token_info = None
                if hasattr(self.db, 'get_token_by_mint_sync'):
                    token_info = self.db.get_token_by_mint_sync(mint)
                
                if token_info and hasattr(token_info, 'dex_id'):
                    found_dex = token_info.dex_id
                    self._token_dex_routing[mint] = found_dex
                    if found_dex in ['raydium_v4', 'raydium_clmm', 'raydium']:
                        logger.debug(f"Routing {mint[:8]}... to Raydium API (found in DB: {found_dex})")
                        return 'raydium'
                    else:
                        logger.debug(f"Routing {mint[:8]}... to Jupiter API (found in DB: {found_dex})")
                        return 'jupiter'
            except Exception as e:
                logger.debug(f"Error checking database for dex_id of {mint}: {e}")
        
        # Default to Jupiter (broader coverage)
        self._token_dex_routing[mint] = 'jupiter'
        logger.debug(f"Routing {mint[:8]}... to Jupiter API (default)")
        return 'jupiter'

    async def fetch_prices(self, mints: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Enhanced fetch_prices using smart API routing.
        
        Args:
            mints: List of token mint addresses
            
        Returns:
            Dict[str, Dict[str, Any]]: SOL-based price data with USD conversion
        """
        if not mints:
            logger.warning("fetch_prices called with empty token list.")
            return {}

        unique_mints = list(set(mints))
        fetched_data: Dict[str, Dict[str, Any]] = {}
        
        # Route tokens to appropriate APIs
        raydium_tokens = []
        jupiter_tokens = []
        
        for mint in unique_mints:
            api_route = self._determine_api_route(mint)
            if api_route == 'raydium':
                raydium_tokens.append(mint)
            else:
                jupiter_tokens.append(mint)
        
        price_logger.info(f"🔄 Fetching prices: {len(raydium_tokens)} via Raydium API, {len(jupiter_tokens)} via Jupiter API")
        
        # Fetch from Raydium API
        if raydium_tokens:
            try:
                self._pricing_stats['raydium_requests'] += 1
                raydium_data = await self._fetch_prices_from_raydium(raydium_tokens)
                fetched_data.update(raydium_data)
            except Exception as e:
                logger.error(f"Error fetching Raydium prices: {e}")
                # Fallback to Jupiter for Raydium tokens
                jupiter_tokens.extend(raydium_tokens)
        
        # Fetch from Jupiter API  
        if jupiter_tokens:
            try:
                self._pricing_stats['jupiter_requests'] += 1
                jupiter_data = await self._fetch_prices_from_jupiter(jupiter_tokens)
                fetched_data.update(jupiter_data)
            except Exception as e:
                logger.error(f"Error fetching Jupiter prices: {e}")
                # Fallback to DexScreener for remaining tokens
                self._pricing_stats['fallback_requests'] += 1
                fallback_data = await self._fetch_prices_fallback(jupiter_tokens)
                fetched_data.update(fallback_data)
        
        # Update statistics and log results
        self._pricing_stats['successful_updates'] += len(fetched_data)
        self._pricing_stats['failed_updates'] += len(unique_mints) - len(fetched_data)
        self._pricing_stats['last_update_time'] = datetime.now()
        
        # Clean price logging
        await self._log_price_updates(fetched_data)
        
        return fetched_data

    async def _fetch_prices_from_raydium(self, mints: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch prices from Raydium API"""
        results = {}
        
        try:
            # Fetch individual prices for each mint
            for mint in mints:
                price_data = await self.raydium_parser.fetch_single_price(mint)
                
                if price_data:
                    # Raydium returns USD prices, convert to SOL
                    price_usd = price_data.get('price_usd', 0)
                    price_sol = price_data.get('price_sol')
                    
                    # If SOL price not calculated, do it here
                    if not price_sol and price_usd:
                        sol_price_usd = await self.get_sol_price()
                        if sol_price_usd and sol_price_usd > 0:
                            price_sol = price_usd / sol_price_usd
                    
                    if price_sol and price_sol > 0:
                        standardized_data = {
                            'mint': mint,
                            'price_sol': price_sol,
                            'price_usd': price_usd,
                            'priceUsd': str(price_usd),  # Legacy format for compatibility
                            'source': 'raydium_api',
                            'timestamp': price_data.get('timestamp', _time.time()),
                            'fetchTimestamp': datetime.now(timezone.utc).isoformat()
                        }
                        
                        results[mint] = standardized_data
                        # Update main cache
                        self._token_data_cache[mint] = standardized_data
                        self._token_prices[mint] = price_sol
                        self._token_prices_usd[mint] = price_usd
                    else:
                        logger.warning(f"Raydium API returned invalid price for {mint}: SOL={price_sol}, USD={price_usd}")
                else:
                    logger.warning(f"No price data returned from Raydium API for {mint}")
                    
        except Exception as e:
            logger.error(f"Error fetching prices from Raydium API: {e}")
        
        return results

    async def _fetch_prices_from_jupiter(self, mints: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch prices from Jupiter API"""
        results = {}
        
        try:
            # Fetch individual prices for each mint
            for mint in mints:
                price_data = await self.jupiter_parser.fetch_single_price(mint)
                
                if price_data:
                    # Jupiter returns SOL prices directly
                    price_sol = price_data.get('price_sol', 0)
                    price_usd = price_data.get('price_usd', 0)
                    
                    if price_sol and price_sol > 0:
                        standardized_data = {
                            'mint': mint,
                            'price_sol': price_sol,
                            'price_usd': price_usd,
                            'priceUsd': str(price_usd) if price_usd else "0",  # Legacy format for compatibility
                            'source': 'jupiter_api',
                            'timestamp': price_data.get('timestamp', _time.time()),
                            'fetchTimestamp': datetime.now(timezone.utc).isoformat()
                        }
                        
                        results[mint] = standardized_data
                        # Update main cache
                        self._token_data_cache[mint] = standardized_data
                        self._token_prices[mint] = price_sol
                        self._token_prices_usd[mint] = price_usd
                    else:
                        logger.warning(f"Jupiter API returned invalid price for {mint}: SOL={price_sol}, USD={price_usd}")
                else:
                    logger.warning(f"No price data returned from Jupiter API for {mint}")
                    
        except Exception as e:
            logger.error(f"Error fetching prices from Jupiter API: {e}")
        
        return results

    async def _fetch_prices_fallback(self, mints: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fallback to DexScreener API with SOL conversion"""
        try:
            # Use existing DexScreener fetch
            api_response = await self.dex_api_client.get_token_details(mints)
            
            if not api_response or not isinstance(api_response, dict) or "pairs" not in api_response:
                return {}
            
            results = {}
            sol_price_usd = await self.get_sol_price()
            timestamp = datetime.now(timezone.utc).isoformat()
            
            for pair_data in api_response["pairs"]:
                base_token_mint = pair_data.get("baseToken", {}).get("address")
                if base_token_mint and base_token_mint in mints:
                    price_usd = pair_data.get("priceUsd")
                    if price_usd:
                        price_usd = float(price_usd)
                        price_sol = price_usd / sol_price_usd if sol_price_usd and sol_price_usd > 0 else 0
                        
                        results[base_token_mint] = {
                            'mint': base_token_mint,
                            'price_sol': price_sol,
                            'price_usd': price_usd,
                            'source': 'dexscreener_api',
                            'timestamp': time.time(),
                            'fetchTimestamp': timestamp
                        }
            
            return results
            
        except Exception as e:
            logger.error(f"Error in fallback price fetch: {e}")
            return {}

    async def _log_price_updates(self, price_data: Dict[str, Dict[str, Any]]):
        """Log price updates in clean format to price_monitor.log"""
        if not price_data:
            return
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        for mint, data in price_data.items():
            price_sol = data.get('price_sol', 0)
            price_usd = data.get('price_usd', 0)
            source = data.get('source', 'unknown')
            
            # Get symbol if available (first 8 chars of mint as fallback)
            symbol = mint[:8] + "..."
            
            # Status indicator
            status = "✅" if price_sol > 0 else "❌"
            if 'timeout' in str(data.get('error', '')).lower():
                status = "⏰"
            
            # Log in clean format
            price_logger.info(f"{timestamp} | {symbol} | {price_sol:.8f} SOL | ${price_usd:.6f} | {source} | {status}")

    async def _update_sol_price_cache(self):
        """Update SOL price cache"""
        try:
            # Try multiple sources for SOL price
            sol_price = None
            
            # Try DexScreener first
            try:
                sol_mint = self.settings.SOL_MINT
                api_response = await self.dex_api_client.get_token_details([sol_mint])
                if api_response and "pairs" in api_response and api_response["pairs"]:
                    pair_data = api_response["pairs"][0]
                    sol_price = float(pair_data.get("priceUsd", 0))
            except Exception as e:
                logger.debug(f"Failed to get SOL price from DexScreener: {e}")
            
            # Fallback: Use settings or default
            if not sol_price or sol_price <= 0:
                sol_price = 150.0  # Reasonable fallback
            
            self._sol_price_cache = sol_price
            self._sol_price_last_updated = datetime.now()
            
            logger.debug(f"Updated SOL price cache: ${sol_price:.2f}")
            
        except Exception as e:
            logger.error(f"Error updating SOL price cache: {e}")
            if not self._sol_price_cache:
                self._sol_price_cache = 150.0  # Emergency fallback

    async def _update_price_history(self, new_data: Dict[str, Dict[str, Any]]):
        """Updates the internal price cache and historical data."""
        if not new_data:
            return

        timestamp_now_utc = datetime.now(timezone.utc) 

        for mint, pair_data in new_data.items():
            try:
                # Extract relevant info for cache and history
                price_usd_str = pair_data.get("priceUsd")
                price_usd = float(price_usd_str) if price_usd_str is not None else None

                # Get old price for change calculation and logging
                old_price = self._token_prices.get(mint)

                # Update latest price cache
                if price_usd is not None:
                    symbol = pair_data.get("baseToken", {}).get("symbol", "UNKNOWN")
                    if old_price is not None: # Existing token being updated
                        if old_price != price_usd:
                            pct_change = None
                            if old_price > 0:
                                pct_change = ((price_usd - old_price) / old_price) * 100
                            
                            if pct_change is not None:
                                logger.info(f"PRICE UPDATE: {symbol} ({mint[:8]}...) changed from ${old_price:.6f} to ${price_usd:.6f} ({pct_change:+.2f}%)")
                                # Log to specialized price logger
                                price_logger = logging.getLogger('prices')
                                price_logger.info(f"{symbol} ({mint[:8]}...) ${old_price:.6f} → ${price_usd:.6f} ({pct_change:+.2f}%)")
                            else: # Price changed but old price was 0 or new price is same (should be caught by old_price != price_usd)
                                logger.info(f"PRICE UPDATE: {symbol} ({mint[:8]}...) price is ${price_usd:.6f} (old price was ${old_price:.6f})")
                                # Log to specialized price logger
                                price_logger = logging.getLogger('prices')
                                price_logger.info(f"{symbol} ({mint[:8]}...) ${price_usd:.6f} (was ${old_price:.6f})")
                            self._token_prices[mint] = price_usd
                        # else: Price hasn't changed, no log, no update to self._token_prices needed here as it's same.
                    else: # New token price being set (old_price is None)
                        logger.info(f"PRICE INIT: {symbol} ({mint[:8]}...) initial price set to ${price_usd:.6f}")
                        # Log to specialized price logger
                        price_logger = logging.getLogger('prices')
                        price_logger.info(f"{symbol} ({mint[:8]}...) INIT ${price_usd:.6f}")
                        self._token_prices[mint] = price_usd

                    # **ADDED: Record DexScreener price for blockchain vs API comparison**
                    try:
                        # Try to access price aggregator through MarketData if available
                        if hasattr(self, '_market_data_reference') and self._market_data_reference:
                            market_data = self._market_data_reference
                            if hasattr(market_data, 'price_aggregator') and market_data.price_aggregator:
                                market_data.price_aggregator.record_price_update(
                                    mint=mint,
                                    price=price_usd,
                                    source='dexscreener',
                                    dex_id='dexscreener'
                                )
                                logger.debug(f"Recorded DexScreener price ${price_usd:.6f} for {mint[:8]}... in price comparison")
                    except Exception as e:
                        logger.debug(f"Could not record DexScreener price for comparison: {e}")

                # Update full data cache
                self._token_data_cache[mint] = pair_data

                # Update history
                if mint not in self.price_history:
                    self.price_history[mint] = []

                # Create a history entry (can customize fields)
                history_entry = {
                    "timestamp": pair_data.get("fetchTimestamp", timestamp_now_utc.isoformat()),
                    "priceUsd": price_usd,
                    "priceNative": float(pair_data.get("priceNative")) if pair_data.get("priceNative") is not None else None,
                    "liquidityUsd": float(pair_data.get("liquidity", {}).get("usd")) if pair_data.get("liquidity", {}).get("usd") is not None else None,
                    "volumeH24": float(pair_data.get("volume", {}).get("h24")) if pair_data.get("volume", {}).get("h24") is not None else None,
                    "pairAddress": pair_data.get("pairAddress")
                }
                self.price_history[mint].append(history_entry)

                # Trim history if it exceeds max length
                if len(self.price_history[mint]) > self.max_history_length:
                    self.price_history[mint].pop(0)

            except Exception as e:
                logger.error(f"Error processing pair data for {mint}: {e} - Data: {pair_data}", exc_info=False)

        # Persist to DB if configured
        if self.db and new_data:
            try:
                # Pass only the necessary processed data to the DB method
                # The DB method should handle its own data extraction/formatting
                await self.db.update_token_prices_batch(new_data) # Assuming db has a batch update method
                logger.debug(f"Persisted price updates for {len(new_data)} tokens to database.")
            except Exception as e:
                logger.error(f"Error persisting price updates to database: {e}", exc_info=True)

    async def _fetch_and_update_prices_for_active(self):
        """
        Fetches the latest prices for all tokens in self.active_tokens_details
        and updates their price history.
        """
        active_token_mints = list(self.active_tokens_details.keys())
        if not active_token_mints:
            logger.debug("_fetch_and_update_prices_for_active: No active tokens to fetch.")
            return

        logger.info(f"PriceMonitor: Polling prices for {len(active_token_mints)} active token(s)...")
        
        new_data = await self.fetch_prices(active_token_mints) # fetch_prices updates _token_prices and _token_data_cache

        # Update internal cache and history (this also logs individual price updates)
        await self._update_price_history(new_data) 
        
        cache_count = len(self._token_prices)
        logger.info(f"PriceMonitor cache now contains {cache_count} tokens after active poll.")
        
        if self._token_prices:
            sample_tokens = list(self._token_prices.keys())[:3]
            for token in sample_tokens:
                price = self._token_prices.get(token)
                logger.debug(f"  Cache sample after active poll: Token {token[:8]}... Price: ${price}")

    async def run_monitor_loop(self):
        """Main loop to periodically fetch prices for monitored tokens."""
        logger.info("Starting PriceMonitor polling loop...")
        await self.initialize() # Ensure initialized

        self._stop_event.clear()
        iteration_count = 0

        while not self._stop_event.is_set():
            try:
                iteration_count += 1
                start_time = _time.monotonic()

                # 1. Update SOL price (cached) - Placed here to run each iteration
                try:
                    current_sol_price = await self.get_sol_price() # This already logs
                    # No need for additional logging of SOL price here if get_sol_price handles it
                except Exception as e_sol:
                    logger.error(f"Error fetching SOL price in monitor loop (iter #{iteration_count}): {e_sol}", exc_info=True)


                # 2. Discover new tokens / remove old ones, and populate self.active_tokens_details
                await self._update_active_tokens_details()

                # 3. Fetch latest prices for all *active* tokens
                if not self.active_tokens_details:
                    logger.warning(f"No active tokens to monitor (iteration #{iteration_count}), sleeping...")
                else:
                    # This method now handles fetching for active_tokens_details and updating history
                    await self._fetch_and_update_prices_for_active()

                end_time = _time.monotonic()
                elapsed_time = end_time - start_time
                sleep_duration = max(0, self.poll_interval - elapsed_time)

                logger.info(f"Price monitor loop iteration #{iteration_count} took {elapsed_time:.2f}s. Sleeping for {sleep_duration:.2f}s.")
                await asyncio.sleep(sleep_duration)

            except asyncio.CancelledError:
                logger.info(f"PriceMonitor polling loop cancelled after {iteration_count} iterations.")
                break
            except Exception as e:
                logger.error(f"Error in PriceMonitor polling loop (iteration #{iteration_count}): {e}", exc_info=True)
                await asyncio.sleep(min(self.poll_interval, 30))

        logger.warning(f"PriceMonitor polling loop finished after {iteration_count} iterations.")

    async def get_price(self, mint: str) -> Optional[float]:
        """
        Retrieves the latest price for a token mint from the cache.
        If not in cache, attempts to fetch it.
        
        Args:
            mint (str): Token mint address
            
        Returns:
            Optional[float]: Price in USD if available, None otherwise
        """
        # First check in the cache
        price = self._token_prices.get(mint)
        
        # If not in cache and it's being monitored, try to fetch it
        if price is None and mint in self.active_tokens_details:
            logger.info(f"Cache miss for {mint}, attempting to fetch price...")
            try:
                # Fetch just for this token
                token_data = await self.fetch_prices([mint])
                if token_data and mint in token_data:
                    # The fetch_prices method now updates the cache, so check again
                    price = self._token_prices.get(mint)
                    if price is not None:
                        logger.info(f"Successfully fetched price for {mint}: ${price}")
                    else:
                        logger.warning(f"Fetch succeeded but price not extracted for {mint}")
                else:
                    logger.warning(f"Failed to fetch price data for {mint}")
            except Exception as e:
                logger.error(f"Error fetching price for {mint}: {e}")
        
        return price

    async def get_latest_data(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the latest full pair data for a token mint from the cache.
        If not in cache, attempts to fetch it.
        
        Args:
            mint (str): Token mint address
            
        Returns:
            Optional[Dict[str, Any]]: Full token pair data if available
        """
        # First check the cache
        data = self._token_data_cache.get(mint)
        
        if data is None and mint in self.active_tokens_details:
            logger.info(f"Cache miss for {mint} data, attempting to fetch...")
            try:
                # Fetch just for this token
                token_data = await self.fetch_prices([mint])
                if token_data and mint in token_data:
                    # Get updated data from cache (fetch_prices now updates it)
                    data = self._token_data_cache.get(mint)
                    if data is not None:
                        logger.info(f"Successfully fetched latest data for {mint}")
                    else:
                        logger.warning(f"Fetch succeeded but data not extracted for {mint}")
                else:
                    logger.warning(f"Failed to fetch latest data for {mint}")
            except Exception as e:
                logger.error(f"Error fetching latest data for {mint}: {e}")
        
        return data

    async def start_monitoring(self, mint: str):
        """Add a token to the active monitoring list. LIKELY DEPRECATED by tokens_being_monitored logic."""
        logger.warning("PriceMonitor.start_monitoring is likely deprecated. Use add_token() instead.")
        if mint not in self._active_monitors:
            self._active_monitors.add(mint)
            logger.info(f"Started monitoring token (via _active_monitors): {mint}")
            # Optionally trigger an immediate fetch for the new token
            # asyncio.create_task(self.fetch_prices([token_address]))

    async def stop_monitoring(self, mint: str):
        """Remove a token from the active monitoring list. LIKELY DEPRECATED."""
        logger.warning("PriceMonitor.stop_monitoring is likely deprecated. Modify tokens_being_monitored and let _update_active_tokens_details handle it.")
        if mint in self._active_monitors:
            self._active_monitors.discard(mint)
            logger.info(f"Stopped monitoring token (via _active_monitors): {mint}")
            # Optionally clear cache for this token immediately
            self._token_prices.pop(mint, None)
            self._token_data_cache.pop(mint, None)
            self.price_history.pop(mint, None)

    def get_price_history(self, mint: str) -> List[Dict[str, Any]]:
        """
        Get the stored price history for a specific token.

        Args:
            mint (str): Token mint address.

        Returns:
            List[Dict[str, Any]]: List of price data points, oldest first. Empty list if no history.
        """
        return self.price_history.get(mint, [])

    def get_latest_price(self, mint: str) -> Optional[Dict[str, Any]]:
        """DEPRECATED: Use get_current_price_usd or get_latest_data. 
        Gets the latest cached data for a token (does not fetch if missing).
        """
        # Consider marking as deprecated or removing if get_current_price_usd is preferred
        logger.warning("Deprecated: get_latest_price is called. Consider using get_current_price_usd or get_latest_data.")
        return self._token_data_cache.get(mint)

    async def get_current_price_usd(self, mint: str, max_age_seconds: Optional[int] = None) -> Optional[float]:
        """
        Gets the latest USD price for a token.
        First checks cache, then fetches if data is missing, stale (if max_age_seconds is set),
        or if a refresh is implicitly needed.

        Args:
            mint: The mint address of the token.
            max_age_seconds: If provided, and cached data is older, a fresh fetch will be attempted.
                             If None, returns cached price if available, otherwise fetches.

        Returns:
            The latest USD price as a float, or None if not found or an error occurs.
        """
        if not mint:
            logger.warning("get_current_price_usd called with no mint.")
            return None

        cached_data = self._token_data_cache.get(mint)
        price_to_return = None

        if cached_data:
            price_usd_str = cached_data.get("priceUsd")
            if price_usd_str is not None:
                try:
                    price_to_return = float(price_usd_str)
                except ValueError:
                    logger.warning(f"Could not convert cached priceUsd '{price_usd_str}' to float for {mint}")
                    price_to_return = None # Treat as not found

            if price_to_return is not None and max_age_seconds is not None:
                fetch_timestamp_str = cached_data.get("fetchTimestamp")
                if fetch_timestamp_str:
                    try:
                        # Ensure timezone awareness for comparison
                        fetch_timestamp = datetime.fromisoformat(fetch_timestamp_str.replace("Z", "+00:00"))
                        if fetch_timestamp.tzinfo is None:
                             fetch_timestamp = fetch_timestamp.replace(tzinfo=timezone.utc) # Assume UTC if naive
                        
                        if datetime.now(timezone.utc) - fetch_timestamp > timedelta(seconds=max_age_seconds):
                            logger.info(f"Cached price for {mint} is older than {max_age_seconds}s. Forcing refresh.")
                            price_to_return = None # Force refresh by setting to None
                    except ValueError:
                        logger.warning(f"Could not parse fetchTimestamp '{fetch_timestamp_str}' for {mint}. Assuming stale.")
                        price_to_return = None # Force refresh
                else: # No fetch timestamp, assume stale if max_age is set
                    logger.info(f"Cached price for {mint} has no fetchTimestamp. Forcing refresh due to max_age_seconds.")
                    price_to_return = None

        if price_to_return is None: # Not in cache, stale, or parsing error
            logger.info(f"Price for {mint} not in cache or needs refresh. Fetching from API.")
            fresh_data_map = await self.fetch_prices([mint])
            if mint in fresh_data_map and fresh_data_map[mint]:
                price_usd_str = fresh_data_map[mint].get("priceUsd")
                if price_usd_str is not None:
                    try:
                        price_to_return = float(price_usd_str)
                    except ValueError:
                        logger.error(f"Could not convert freshly fetched priceUsd '{price_usd_str}' to float for {mint}")
                        price_to_return = None
                else:
                    logger.warning(f"Freshly fetched data for {mint} missing 'priceUsd'.")
            else:
                logger.warning(f"Failed to fetch fresh price for {mint} or data was empty.")
            
        if price_to_return is not None:
            logger.debug(f"Returning price for {mint}: ${price_to_return}")
        # else: # Already logged specific reasons above
            # logger.warning(f"Could not determine price for {token_address} after cache check and potential fetch.")
            
        return price_to_return

    async def get_current_price_sol(self, mint: str, max_age_seconds: Optional[int] = None) -> Optional[float]:
        """
        Gets the latest SOL price for a token - MAIN METHOD FOR SOL-BASED TRADING.
        First checks cache, then fetches if data is missing, stale (if max_age_seconds is set),
        or if a refresh is implicitly needed.

        Args:
            mint: The mint address of the token.
            max_age_seconds: If provided, and cached data is older, a fresh fetch will be attempted.
                             If None, returns cached price if available, otherwise fetches.

        Returns:
            The latest SOL price as a float, or None if not found or an error occurs.
        """
        if not mint:
            logger.warning("get_current_price_sol called with no mint.")
            return None

        # Check if we have SOL price data in the new format
        cached_data = self._token_data_cache.get(mint)
        price_to_return = None

        if cached_data:
            # First try to get SOL price directly
            price_sol = cached_data.get("price_sol")
            if price_sol is not None:
                try:
                    price_to_return = float(price_sol)
                except ValueError:
                    logger.warning(f"Could not convert cached price_sol '{price_sol}' to float for {mint}")
                    price_to_return = None

            # If no SOL price but we have USD price, convert it
            elif cached_data.get("priceUsd") is not None:
                try:
                    price_usd = float(cached_data.get("priceUsd"))
                    sol_price_usd = await self.get_sol_price()
                    if sol_price_usd and sol_price_usd > 0:
                        price_to_return = price_usd / sol_price_usd
                        # Cache the SOL price for future use
                        cached_data["price_sol"] = price_to_return
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert cached priceUsd to SOL for {mint}")
                    price_to_return = None

            # Check if data is stale and needs refresh
            if price_to_return is not None and max_age_seconds is not None:
                fetch_timestamp_str = cached_data.get("fetchTimestamp")
                if fetch_timestamp_str:
                    try:
                        # Ensure timezone awareness for comparison
                        fetch_timestamp = datetime.fromisoformat(fetch_timestamp_str.replace("Z", "+00:00"))
                        if fetch_timestamp.tzinfo is None:
                             fetch_timestamp = fetch_timestamp.replace(tzinfo=timezone.utc)
                        
                        if datetime.now(timezone.utc) - fetch_timestamp > timedelta(seconds=max_age_seconds):
                            logger.info(f"Cached SOL price for {mint} is older than {max_age_seconds}s. Forcing refresh.")
                            price_to_return = None
                    except ValueError:
                        logger.warning(f"Could not parse fetchTimestamp '{fetch_timestamp_str}' for {mint}. Assuming stale.")
                        price_to_return = None
                else:
                    logger.info(f"Cached SOL price for {mint} has no fetchTimestamp. Forcing refresh due to max_age_seconds.")
                    price_to_return = None

        if price_to_return is None:
            logger.info(f"SOL price for {mint} not in cache or needs refresh. Fetching from API.")
            fresh_data_map = await self.fetch_prices([mint])
            if mint in fresh_data_map and fresh_data_map[mint]:
                # Extract SOL price from fresh data
                price_sol = fresh_data_map[mint].get("price_sol")
                if price_sol is not None:
                    try:
                        price_to_return = float(price_sol)
                    except ValueError:
                        logger.error(f"Could not convert freshly fetched price_sol '{price_sol}' to float for {mint}")
                        price_to_return = None
                else:
                    logger.warning(f"Freshly fetched data for {mint} missing 'price_sol'.")
            else:
                logger.warning(f"Failed to fetch fresh SOL price for {mint} or data was empty.")
            
        if price_to_return is not None:
            logger.debug(f"Returning SOL price for {mint}: {price_to_return:.8f} SOL")
            
        return price_to_return

    def get_history_as_dataframe(self, mint: str) -> Optional[pd.DataFrame]:
        """
        Get the stored price history for a token as a Pandas DataFrame.

        Args:
            mint (str): Token mint address.

        Returns:
            Optional[pd.DataFrame]: DataFrame with price history indexed by timestamp, or None.
        """
        history = self.get_price_history(mint)
        if not history:
            return None
        try:
            df = pd.DataFrame(history)
            # Convert timestamp string to datetime objects and set as index
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            # Ensure numeric types where expected
            numeric_cols = ['price_native', 'price_usd', 'liquidity_usd', 'volume_h24']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce') # Coerce errors to NaN
            return df
        except Exception as e:
            logger.error(f"Error converting price history to DataFrame for {mint}: {e}", exc_info=True)
            return None

    async def get_sol_price(self) -> Optional[float]:
        """
        Fetches the current price of SOL in USD from dedicated APIs (CoinGecko/Binance),
        using a cache.

        Returns:
            Optional[float]: The price of SOL in USD, or None if fetching fails.
        """
        now = datetime.now(timezone.utc)

        # Check cache first
        if self._sol_price_cache is not None and \
           self._sol_price_last_updated is not None:
            # Ensure both timestamps are timezone-aware for comparison
            last_updated = self._sol_price_last_updated
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=timezone.utc)
            if (now - last_updated < self._sol_price_cache_ttl):
                logger.debug(f"Using cached SOL price: ${self._sol_price_cache:.4f}")
                return self._sol_price_cache

        price_usd: Optional[float] = None
        api_urls = [
            getattr(self.settings, 'SOL_PRICE_API', None),
            getattr(self.settings, 'SOL_PRICE_API_BACKUP', None)
        ]
        api_urls = [url for url in api_urls if url] # Filter out None values

        if not api_urls:
             logger.error("No SOL_PRICE_API or SOL_PRICE_API_BACKUP URLs found in settings.")
             return None

        for i, url in enumerate(api_urls):
            source = "Primary (CoinGecko?)" if i == 0 else "Backup (Binance?)"
            logger.info(f"Attempting to fetch SOL price from {source} API: {url}")
            try:
                response = await self.http_client.get(url)
                response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                data = response.json()  # REMOVED await

                # --- Parse response based on likely source ---
                if 'coingecko.com' in url:
                    price_usd = data.get('solana', {}).get('usd')
                elif 'binance.com' in url:
                    price_str = data.get('price')
                    if price_str:
                         price_usd = float(price_str)
                else: # Fallback/Unknown structure
                    logger.warning(f"Unknown API structure for {url}. Attempting generic parsing.")
                    # Try common keys
                    price_usd = data.get('usd') or data.get('price') or data.get('last')
                    if isinstance(price_usd, str):
                        price_usd = float(price_usd)

                # --- Check if parsing was successful ---
                if price_usd is not None:
                    self._sol_price_cache = price_usd
                    self._sol_price_last_updated = now  # now is already timezone-aware
                    logger.info(f"Fetched and cached SOL price from {source}: ${price_usd:.4f}")
                    return price_usd # Success, return immediately
                else:
                    logger.warning(f"Could not parse SOL price from {source} API response: {data}")

            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP error fetching SOL price from {source} ({url}): {e.response.status_code} - {e.response.text[:100]}...")
            except (httpx.RequestError, json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning(f"Error fetching or parsing SOL price from {source} ({url}): {e}")
            except Exception as e:
                 logger.error(f"Unexpected error fetching SOL price from {source} ({url}): {e}", exc_info=True)

            # If this source failed, loop will continue to the next one

        # If loop finishes without returning, all sources failed
        logger.error("Failed to fetch SOL price from all configured APIs.")
        return None # Return None if all attempts failed

    def add_token(self, mint: str):
        """Adds a token to the set of tokens PriceMonitor should actively poll for prices."""
        if not mint:
            logger.warning("PriceMonitor.add_token called with empty mint.")
            return

        logger.info(f"PriceMonitor.add_token called for: {mint}")
        if mint not in self.tokens_being_monitored:
            self.tokens_being_monitored.add(mint)
            logger.info(f"Token {mint} added to PriceMonitor.tokens_being_monitored. Current set size: {len(self.tokens_being_monitored)}")
            # No need to immediately fetch price here, _poll_prices_loop will pick it up.
        else:
            logger.debug(f"Token {mint} is already in PriceMonitor.tokens_being_monitored.")

    async def _poll_prices_loop(self):
        """Periodically fetches prices for all tokens in self.tokens_being_monitored."""
        logger.info("PriceMonitor polling loop started.")
        while not self._stop_event.is_set():
            try:
                if not self.tokens_being_monitored:
                    # logger.debug("PriceMonitor: No tokens to monitor in this cycle.") # Can be noisy
                    await asyncio.sleep(self.poll_interval) # Wait before checking again
                    continue

                # Create a copy of the set for safe iteration, as it might be modified elsewhere
                current_tokens_to_poll = list(self.tokens_being_monitored)
                logger.info(f"PriceMonitor polling prices for {len(current_tokens_to_poll)} tokens: {current_tokens_to_poll[:5]}...")
                
                # Fetch prices in batches (DexScreenerAPI handles actual batching to endpoint)
                fetched_data = await self.fetch_prices(current_tokens_to_poll)
                
                if fetched_data:
                    await self._update_price_history(fetched_data)
                else:
                    logger.debug("No data fetched in this polling cycle.")

                # Wait for the next polling interval
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                logger.info("PriceMonitor polling loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in PriceMonitor polling loop: {e}", exc_info=True)
                # Avoid rapid error loops; wait before retrying
                await asyncio.sleep(self.poll_interval * 2)
        logger.info("PriceMonitor polling loop stopped.")

    async def _update_active_tokens_details(self):
        """
        Identifies new tokens from self.tokens_being_monitored,
        fetches their initial details, and adds them to self.active_tokens_details.
        Removes details for tokens no longer in self.tokens_being_monitored.
        """
        logger.debug(f"_update_active_tokens_details: Entered. self.tokens_being_monitored: {self.tokens_being_monitored}, self.active_tokens_details keys: {list(self.active_tokens_details.keys()) if hasattr(self, 'active_tokens_details') else 'N/A'}")

        # Ensure active_tokens_details exists
        if not hasattr(self, 'active_tokens_details') or self.active_tokens_details is None:
            self.active_tokens_details = {}
            logger.debug("_update_active_tokens_details: Initialized self.active_tokens_details as it was missing.")


        if not self.tokens_being_monitored and not self.active_tokens_details:
            # No tokens to add or remove, quick exit
            logger.debug("_update_active_tokens_details: Exiting early - no tokens to add or remove.")
            return

        # Identify tokens to add (in tokens_being_monitored but not yet in active_tokens_details)
        current_active_mints = set(self.active_tokens_details.keys())
        tokens_to_add_mints = self.tokens_being_monitored - current_active_mints
        
        logger.debug(f"_update_active_tokens_details: current_active_mints: {current_active_mints}")
        logger.debug(f"_update_active_tokens_details: tokens_to_add_mints: {tokens_to_add_mints}")


        if tokens_to_add_mints:
            logger.info(f"_update_active_tokens_details: Found {len(tokens_to_add_mints)} new token(s) to fetch initial details for: {list(tokens_to_add_mints)[:5]}...")
            # Fetch initial data for these new tokens
            # fetch_prices updates self._token_data_cache and self._token_prices
            initial_data_fetched = await self.fetch_prices(list(tokens_to_add_mints))

            for mint_addr in tokens_to_add_mints:
                if mint_addr in initial_data_fetched:
                    self.active_tokens_details[mint_addr] = initial_data_fetched[mint_addr]
                    # Also ensure _token_data_cache and _token_prices are updated if fetch_prices doesn't do it for all cases
                    self._token_data_cache[mint_addr] = initial_data_fetched[mint_addr]
                    if 'priceUsd' in initial_data_fetched[mint_addr] and initial_data_fetched[mint_addr]['priceUsd'] is not None:
                        try:
                            self._token_prices[mint_addr] = float(initial_data_fetched[mint_addr]['priceUsd'])
                        except (ValueError, TypeError):
                            logger.warning(f"Could not convert priceUsd to float for {mint_addr} in _update_active_tokens_details.")
                    
                    logger.info(f"Token {mint_addr[:8]}... added to active_tokens_details with initial data.")
                else:
                    # If fetching initial details failed, it won't be added to active.
                    # It will remain in tokens_being_monitored and be retried next cycle.
                    logger.warning(f"Failed to fetch initial details for new token {mint_addr[:8]}.... It will be retried.")
        
        # Identify tokens to remove (in active_tokens_details but no longer in tokens_being_monitored)
        tokens_to_remove_mints = current_active_mints - self.tokens_being_monitored
        if tokens_to_remove_mints:
            logger.info(f"_update_active_tokens_details: Removing {len(tokens_to_remove_mints)} token(s) from active monitoring: {list(tokens_to_remove_mints)[:5]}...")
            for mint_addr in tokens_to_remove_mints:
                self.active_tokens_details.pop(mint_addr, None)
                self._token_data_cache.pop(mint_addr, None)
                self._token_prices.pop(mint_addr, None)
                # Optionally clear price history too, or let it persist
                # self.price_history.pop(mint_addr, None)
                logger.info(f"Token {mint_addr[:8]}... removed from active_tokens_details and caches.")

