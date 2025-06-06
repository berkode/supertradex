import json
import os
import asyncio
import logging
import time
import base64 # Added base64
from typing import Dict, List, Optional, Any, Callable, Set, Tuple, Union
from datetime import datetime, timedelta, timezone
import httpx
import backoff # Add backoff import
from dotenv import load_dotenv
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from spl.token.instructions import get_associated_token_address
import websockets # Use websockets library directly
import borsh_construct as bc # Import with alias just before use
# from borsh_construct import Bytes, CStruct, U64, Bool # Remove direct import
# --- Import existing modules --- #
from config.settings import Settings
from config.dexscreener_api import DexScreenerAPI
from utils.logger import get_logger
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType
# Import existing data components
from .data_fetcher import DataFetcher
from .price_monitor import PriceMonitor
from .blockchain_listener import BlockchainListener
from .token_database import TokenDatabase
import base58 # Assuming base58 is available or add it to requirements
import binascii
import traceback # Add import for traceback
import importlib
from construct import ConstructError, Bytes as ConstructBytes # Import from base construct library and Bytes
from solders.transaction_status import EncodedTransactionWithStatusMeta, UiTransactionEncoding # type: ignore
from solders.rpc.responses import RpcLogsResponse, SubscriptionResult # type: ignore
from solana.exceptions import SolanaRpcException
from solders.signature import Signature # Add this import
import random

# Load environment variables
load_dotenv()
logger = get_logger(__name__)

# Known program IDs to exclude from being treated as token mints
KNOWN_PROGRAM_IDS = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", # SPL Token Program
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",   # SPL Token-2022 Program
    # Add other known program/system accounts if they become problematic
}

# --- Backoff Helper Predicate --- #
def is_rate_limit_error(e: Exception) -> bool:
    """Checks if an exception is an HTTP 429 error."""
    return isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429

class MarketData:
    """
    Consolidated service for accessing market data from various sources.
    Provides caching, data consistency checks, and a unified interface.
    """

    def __init__(self, settings: Settings, dexscreener_api: DexScreenerAPI, token_db=None, http_client=None, solana_client=None):
        """
        Initialize the MarketData service
        
        Args:
            settings: Application settings
            dexscreener_api: DexScreenerAPI instance
            token_db: Optional TokenDatabase instance
            http_client: Optional aiohttp ClientSession
            solana_client: Optional Solana client
        """
        self.logger = get_logger(__name__)
        self.settings = settings
        self.dexscreener_api = dexscreener_api # Store the passed-in DexScreenerAPI
        self.token_db = token_db
        self.db = token_db  # Add this for backward compatibility
        self.http_client = http_client
        self.solana_client = solana_client
        
        # Initialize circuit breaker
        self.circuit_breaker = CircuitBreaker(
            breaker_type=CircuitBreakerType.COMPONENT,
            identifier="market_data",
            max_consecutive_failures=5,
            reset_after_minutes=5
        )
        
        # Initialize state trackers
        self.is_monitoring = False
        self.is_streaming = False
        
        # Initialize metrics
        self.metrics = {
            "errors": 0,
            "last_error": None,
            "last_error_time": None,
            "cache_hits": 0,
            "cache_misses": 0,
            "api_calls": 0,
            "primary": {
                "connection_attempts": 0,
                "connection_successes": 0,
                "subscription_attempts": 0,
                "subscription_successes": 0,
                "connection_success_rate": 0.0,
                "subscription_success_rate": 0.0
            },
            "fallback": {
                "connection_attempts": 0,
                "connection_successes": 0,
                "subscription_attempts": 0,
                "subscription_successes": 0,
                "connection_success_rate": 0.0,
                "subscription_success_rate": 0.0
            },
            "price_monitor_fallbacks": 0,
            "timestamp": time.time()
        }
        
        # Initialize cache storage for tokens, pools, etc.
        self._token_cache = {} # mint -> token data
        self._pool_cache = {} # pool_address -> pool data
        self._price_cache = {} # mint -> price data
        self._historical_cache = {} # mint -> historical data
        self._market_data_cache = {} # mint -> market data
                
        # Create Borsh schema layouts for on-chain data parsing
        try:
            self.logger.info(f"Attempting to define Borsh schemas. Testing borsh_construct alias: {type(bc)}")
            
            # Define a schema for PumpFun Trade Event
            self._trade_event_layout = bc.CStruct( 
                "last_event_id" / bc.U64,
                "token_mint_key" / bc.Bytes[32], 
                "event_type" / bc.U8, 
                "total_token_amount" / bc.U64, 
                "total_usdc_amount" / bc.U64, 
                "token_price" / bc.U64, 
                "liquidity_fee" / bc.U64, 
                "treasury_fee" / bc.U64, 
                "tokens_outstanding" / bc.U64, 
                "reserve_balance" / bc.U64, 
            )
            self.logger.info("Defined _trade_event_layout using bc.")
            
            # Define a schema for Bonding Curve (Pump.fun)
            self._bonding_curve_layout = bc.CStruct(
                "version" / bc.U8,
                "is_frozen" / bc.Bool,
                "tokens_outstanding" / bc.U64, 
                "curve_owner" / bc.Bytes[32],
                "treasury_owner" / bc.Bytes[32],
                "token_mint" / bc.Bytes[32],
                "token_pool" / bc.Bytes[32],
                "usdc_pool" / bc.Bytes[32], 
                "initial_slot" / bc.U64,
                "virtual_sol_reserves" / bc.U64,
                "virtual_token_reserves" / bc.U64,
                "real_sol_reserves" / bc.U64,
                "real_token_reserves" / bc.U64,
                "target_sol_reserves" / bc.U64,
                "complete" / bc.Bool,
                "buy_fee_bps" / bc.U64,
                "sell_fee_bps" / bc.U64
            )
            self.logger.info("Defined _bonding_curve_layout using bc.")
            
            # Define Raydium V4 pool layout
            self._raydium_v4_pool_layout = bc.CStruct(
                "status" / bc.U64,
                "base_mint" / bc.Bytes[32],
                "quote_mint" / bc.Bytes[32],
                "lp_mint" / bc.Bytes[32],
                "open_time" / bc.U64,
                # "current_price" / bc.I64, # Removed as price is derived
                "pool_base_vault" / bc.Bytes[32], # Added to match parsing logic
                "pool_quote_vault" / bc.Bytes[32], # Added to match parsing logic
                # "base_reserve" / bc.U64, # Removed to avoid conflict/confusion with vault fetching logic
                # "quote_reserve" / bc.U64, # Removed to avoid conflict/confusion with vault fetching logic
                "lp_supply" / bc.U64
                # Potentially other fields from a complete Raydium AMM state are missing.
                # This change aims to fix the immediate bug with vault address access based on current parsing logic.
            )
            self.logger.info("Defined Raydium V4 pool layout using bc.")
            self.logger.info("Successfully defined FULL Borsh layouts using aliased 'bc'.") # Updated log

        except NameError as ne:
            self.logger.error(f"NameError involving 'bc' for Borsh layouts: {ne}. This suggests 'import borsh_construct as bc' failed or was not recognized.", exc_info=True)
            self._trade_event_layout = None
            self._bonding_curve_layout = None
            self._raydium_v4_pool_layout = None
        except Exception as e: 
            self.logger.error(f"Error during Borsh layout definition phase: {e}", exc_info=True)
            self._trade_event_layout = None
            self._bonding_curve_layout = None
            self._raydium_v4_pool_layout = None
        
        # Initialize DEX-specific parsers using the new parser system
        from data import RaydiumV4Parser, PumpSwapParser, RaydiumClmmParser, RaydiumPriceParser, JupiterPriceParser
        from config.blockchain_logging import setup_price_monitoring_logger, PriceMonitoringAggregator
        
        # Initialize parser registry
        self.parsers = {
            'raydium_v4': RaydiumV4Parser(self.settings, self.logger),
            'pumpswap': PumpSwapParser(self.settings, self.logger),
            'raydium_clmm': RaydiumClmmParser(self.settings, self.logger)
        }
        
        # Initialize price parsers (REST API based)
        self.price_parsers = {
            'raydium_price': RaydiumPriceParser(self.settings, self.logger),
            'jupiter_price': JupiterPriceParser(self.settings, self.logger, http_client)
        }
        
        # Initialize price monitoring aggregator for comparison logging
        price_monitor_logger = setup_price_monitoring_logger("MarketDataPriceMonitor")
        self.price_aggregator = PriceMonitoringAggregator(price_monitor_logger)
        
        self.logger.info(f"MarketData initialized {len(self.parsers)} DEX parsers, {len(self.price_parsers)} price parsers, and price aggregator")
        self.logger.info(f"DEX parsers: {list(self.parsers.keys())}")
        self.logger.info(f"Price parsers: {list(self.price_parsers.keys())}")
        
        # Initialize required attributes
        self.price_monitor = None
        self.blockchain_listener = None
        self.webhook_client = None
        self._price_update_callbacks = []
        
        # Track monitored tokens
        self._monitored_tokens = {}  # Map of mint -> monitoring_info
        
        # Initialize attributes for priority determination
        self.active_positions = set()  # Set of token addresses in active positions
        self.watchlist = set()  # Set of token addresses on watchlist
        self.scanner_results = []  # List of recent scanner results
        
        self.logger.info("MarketData service initialization complete")
        self.current_monitored_mint = None
        self.is_monitoring_active = False
        self.tokens_to_monitor = set() # Initialize tokens_to_monitor as a set
        self.actively_streamed_mints = set() # Initialize actively_streamed_mints as a set
        self._realtime_pair_state = {} # Initialize _realtime_pair_state as a dictionary
        self._blockchain_listener_task: Optional[asyncio.Task] = None # Task for BlockchainListener.run_forever()
        self._price_monitor_dex_api_client: Optional[DexScreenerAPI] = None # REMOVE THIS LINE
        
        # Initialize pool to tokens mapping for blockchain event processing
        self.pool_to_tokens = {} # Map pool_addresses -> {mint, base_token, etc.}
        
        # Initialize caches and related attributes
        self.cache: Dict[str, Dict[str, Tuple[Any, float]]] = { # type: ignore
            "token_info": {},
            "pair_data": {},
            "price": {},
            "historical_data": {},
            "market_data": {},
            "blockchain_data": {}
        }
        self.cache_ttl: Dict[str, int] = {
            "token_info": 300, # 5 minutes
            "pair_data": 300,
            "price": 60, # 1 minute
            "historical_data": 3600, # 1 hour
            "market_data": 120, # 2 minutes
            "blockchain_data": 60
        }
        self.last_update_time: Dict[str, float] = {} # For get_token_price
        self._token_prices: Dict[str, Dict[str, Any]] = {} # For update_token_price

        # For _log_token_price method
        self.last_price_log: Dict[str, datetime] = {}
        self.price_log_interval: timedelta = timedelta(seconds=60) # Log every 60 seconds

    async def initialize(self) -> bool:
        """
        Initialize the market data service and its components.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            self.logger.info("Initializing MarketData...")
            
            # Create HTTP client if not provided
            if not self.http_client:
                self.http_client = httpx.AsyncClient(timeout=self.settings.HTTP_TIMEOUT)
                self.logger.info("Created new HTTP client for MarketData")
            
            # Create Solana client if not provided
            if not self.solana_client:
                from solana.rpc.async_api import AsyncClient
                self.solana_client = AsyncClient(self.settings.SOLANA_RPC_URL)
                self.logger.info("Created new Solana client for MarketData")
            
            # Initialize DataFetcher
            self.data_fetcher = DataFetcher(self.settings) # Pass only settings for now
            data_fetcher_ok = await self.data_fetcher.initialize()
            
            # Initialize price monitor with the SHARED dexscreener_api parameters
            self.price_monitor = PriceMonitor(
                settings=self.settings,
                dex_api_client=self.dexscreener_api, # USE SHARED INSTANCE
                http_client=self.http_client,
                db=self.db
            )
            if not await self.price_monitor.initialize():
                self.logger.error("Failed to initialize PriceMonitor in MarketData")
                return False
            
            # Initialize price parsers
            price_parser_results = []
            for parser_name, parser in self.price_parsers.items():
                try:
                    result = await parser.initialize()
                    price_parser_results.append(result)
                    if result:
                        self.logger.info(f"Successfully initialized {parser_name} price parser")
                    else:
                        self.logger.warning(f"Failed to initialize {parser_name} price parser")
                except Exception as e:
                    self.logger.error(f"Error initializing {parser_name} price parser: {e}")
                    price_parser_results.append(False)
            
            # **ADDED: Set up price aggregator reference for price comparison recording**
            self.price_monitor._market_data_reference = self
            
            price_monitor_ok = await self.price_monitor.initialize()
            
            # Now that price_monitor is initialized, update the price_aggregator reference
            if hasattr(self, 'price_aggregator') and self.price_aggregator:
                self.price_aggregator.price_monitor = self.price_monitor
                # Initialize SOL price cache
                try:
                    await self.price_aggregator.update_sol_price_cache()
                    self.logger.info("Initialized SOL price cache for price monitoring aggregator")
                except Exception as e:
                    self.logger.warning(f"Failed to initialize SOL price cache: {e}")
            
            # Don't initialize blockchain listener here, it will be done separately
            # through initialize_blockchain_listener method
            blockchain_listener_ok = True
            
            # Check initialization results
            if not all([data_fetcher_ok, price_monitor_ok, blockchain_listener_ok]):
                self.logger.warning("Some components failed to initialize, but continuing with available functionality")
            
            self.logger.info("MarketData initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing MarketData: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            return False

    async def close(self):
        """Clean up resources (HTTP session, task cancellation, etc.)"""
        try:
            logger.info("Closing MarketData resources...")
            
            # Stop monitoring if active
            if self.is_monitoring:
                await self.stop_monitoring()
            
            # Stop monitoring specific token if active
            if hasattr(self, 'current_monitored_mint') and self.current_monitored_mint:
                await self.stop_monitoring_token(self.current_monitored_mint)
            
            # Close data components
            if self.data_fetcher:
                await self.data_fetcher.close()
            
            if self.price_monitor: # MODIFIED - check if exists before closing
                await self.price_monitor.close()
            
            # Close price parsers
            if hasattr(self, 'price_parsers'):
                for parser_name, parser in self.price_parsers.items():
                    try:
                        await parser.close()
                        self.logger.info(f"Closed {parser_name} price parser")
                    except Exception as e:
                        self.logger.error(f"Error closing {parser_name} price parser: {e}")
            
            # Close BlockchainListener if it was initialized
            if self.blockchain_listener:
                await self.blockchain_listener.close()
                
                if hasattr(self, '_blockchain_listener_task') and self._blockchain_listener_task and not self._blockchain_listener_task.done():
                    self.logger.info("Waiting for Blockchain Listener's run_forever task to complete shutdown...")
                    try:
                        # Wait for the task to finish, with a timeout
                        await asyncio.wait_for(self._blockchain_listener_task, timeout=15.0)
                        self.logger.info("Blockchain Listener's run_forever task completed gracefully.")
                    except asyncio.TimeoutError:
                        self.logger.warning("Timeout waiting for Blockchain Listener task to complete. Attempting to cancel it.")
                        self._blockchain_listener_task.cancel()
                        try:
                            await self._blockchain_listener_task # Await cancellation
                        except asyncio.CancelledError:
                            self.logger.info("Blockchain Listener task was cancelled after timeout.")
                        except Exception as e_cancel:
                            self.logger.error(f"Error awaiting blockchain listener task after cancellation: {e_cancel}")
                    except asyncio.CancelledError:
                        self.logger.info("Blockchain Listener task was already cancelled.")
                    except Exception as e_await:
                        self.logger.error(f"Error awaiting blockchain listener task during close: {e_await}")
            
            # Close HTTP client if we created it
            if self.http_client and not self.http_client.is_closed:  # Corrected to use is_closed
                await self.http_client.aclose()
                self.http_client = None
                
            # Signal end of monitoring
            self.is_monitoring = False
            if hasattr(self, 'is_streaming'):
                self.is_streaming = False
            
            logger.info("MarketData resources closed successfully")
            
        except Exception as e:
            logger.error(f"Error closing MarketData resources: {e}", exc_info=True)
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()

    # --- Cache Management ---

    def _get_cached_data(self, cache_type: str, key: str) -> Optional[Any]:
        """
        Get data from cache if it exists and is not expired.
        
        Args:
            cache_type: Type of cache to access
            key: Cache key
            
        Returns:
            Cached data if available and not expired, None otherwise
        """
        if cache_type not in self.cache:
            logger.warning(f"Invalid cache type: {cache_type}")
            return None
            
        cache_entry = self.cache[cache_type].get(key)
        if not cache_entry:
            self.metrics["cache_misses"] += 1
            return None
            
        data, timestamp = cache_entry
        ttl = self.cache_ttl.get(cache_type, 60)  # Default 60 seconds
        
        # Check if cache is expired
        if time.time() - timestamp > ttl:
            logger.debug(f"Cache expired for {cache_type}:{key}")
            self.metrics["cache_misses"] += 1
            return None
            
        logger.debug(f"Cache hit for {cache_type}:{key}")
        self.metrics["cache_hits"] += 1
        return data

    def _set_cached_data(self, cache_type: str, key: str, data: Any):
        """
        Store data in cache with current timestamp.
        
        Args:
            cache_type: Type of cache to use
            key: Cache key
            data: Data to cache
        """
        if cache_type not in self.cache:
            logger.warning(f"Invalid cache type: {cache_type}")
            return
            
        # --- Check if trying to cache data for an actively streamed token --- #
        # We generally want to avoid caching rapidly changing streamed data,
        # but allow caching for other types like 'token_info'.
        # Let's prevent caching 'blockchain_data' or 'price' if it's actively streamed.
        if cache_type in ['blockchain_data', 'price'] and key in self.actively_streamed_mints:
             logger.debug(f"Skipping cache set for actively streamed mint {key} (type: {cache_type})")
             return
        # --- End Check ---

        self.cache[cache_type][key] = (data, time.time())
        logger.debug(f"Cached data for {cache_type}:{key}")

    def _clear_cache(self, cache_type: Optional[str] = None):
        """
        Clear cache entries, optionally for a specific cache type.
        
        Args:
            cache_type: Optional cache type to clear, or None to clear all
        """
        if cache_type:
            if cache_type in self.cache:
                self.cache[cache_type] = {}
                logger.info(f"Cleared cache for {cache_type}")
            else:
                logger.warning(f"Invalid cache type: {cache_type}")
        else:
            for cache_type_key in self.cache: # Renamed loop variable for clarity
                self.cache[cache_type_key] = {}
            logger.info("Cleared all caches")

    # --- Data Access Methods ---

    async def get_token_price(self, mint: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get the current price for a token, prioritizing real-time data if streamed,
        then using cache, and finally fetching fresh data.
        
        Args:
            mint: Token mint address
            force_refresh: Whether to bypass cache and fetch fresh data
            
        Returns:
            Token price data (incl. 'source') or None if not available
        """
        # --- Check Real-time Data First (if actively streamed) ---
        if mint in self.actively_streamed_mints and not force_refresh:
            pair_address = None # Renamed variable
            try:
                # Query DB to find the associated pair address (pair_address)
                token_info = await self.db.get_token_info(mint) # Use get_token_info as it returns a dict
                pair_address = token_info.get("pair_address") if token_info else None
            except Exception as db_err:
                 logger.warning(f"DB error fetching pair address for actively streamed token {mint}: {db_err}")

            if pair_address:
                pair_state = self._realtime_pair_state.get(pair_address) # Updated dictionary name and key variable
                if pair_state:
                    # Check staleness (e.g., within 5 seconds)
                    timestamp_utc = pair_state.get("timestamp")
                    if isinstance(timestamp_utc, datetime) and (datetime.now(timezone.utc) - timestamp_utc).total_seconds() < 5:
                        logger.debug(f"Using real-time price for {mint} from pair {pair_address}") # Updated log message
                        return {
                            "price": pair_state["price"],
                            "timestamp": timestamp_utc.isoformat(),
                            "source": "realtime"
                        }
                    else:
                        logger.warning(f"Real-time data is stale or has invalid timestamp for {mint} (pair: {pair_address}). Falling back.") # Updated log message
                else:
                    logger.warning(f"No real-time state found for pair {pair_address} (mint: {mint}) despite active stream. Falling back.") # Updated log message
            else:
                logger.warning(f"Could not determine pair address for actively streamed token {mint}. Falling back.") # Updated log message
        # --- End Real-time Check ---

        # --- Fallback to Cache/Fetch Logic ---
        if self.circuit_breaker.check():
            logger.warning("Circuit breaker active. Using cached price data if available.")
            # Still try to return cached data even if circuit breaker is active
        
        # Check standard time-based cache first if not forcing refresh (disabled to avoid indent error)
        if not force_refresh:
            pass
        
        # If not in cache or force_refresh is True, fetch fresh data
        try:
            self.metrics["api_calls"] += 1
            # Note: price_monitor.fetch_prices might need adjustment if it caches internally
            # Assuming it fetches fresh prices based on its own logic/cache TTL
            prices = await self.price_monitor.fetch_prices([mint])
            if mint in prices:
                price_data = prices[mint]
                # Ensure price_data is a dictionary
                if isinstance(price_data, dict):
                    price_data["source"] = "fetch"  # Add source info
                else:
                    logger.error(f"Fetched price data for {mint} is not a dictionary: {price_data}")
                    return None
                self._set_cached_data("price", mint, price_data)
                self.last_update_time[mint] = time.time()
                
                # Record price for comparison aggregation
                price_value = price_data.get('price')
                if price_value and hasattr(self, 'price_aggregator'):
                    self.price_aggregator.record_price_update(
                        mint=mint, 
                        price=float(price_value), 
                        source='dexscreener'
                    )
                
                # Notify subscribers
                self._notify_subscribers("price_update", {
                    "mint": mint,
                    "price_data": price_data
                })
                return price_data
            else:
                logger.warning(f"No price data fetched for token {mint}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching price for token {mint}: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            
            # Return cached data as fallback if available
            cached_data = self._get_cached_data("price", mint)
            if cached_data:
                logger.info(f"Using cached price data for {mint} due to error")
                # Add source if missing
                if "source" not in cached_data:
                     cached_data["source"] = "cache_fallback"
                return cached_data
                
            return None

    async def get_token_info(self, mint: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get information about a token, using cache if available.
        
        Args:
            mint: Token mint address
            force_refresh: Whether to bypass cache and fetch fresh data
            
        Returns:
            Token information or None if not available
        """
        if self.circuit_breaker.check():
            logger.warning("Circuit breaker active. Using cached token info if available.")
        
        # Check cache first if not forcing refresh
        if not force_refresh:
            cached_data = self._get_cached_data("token_info", mint)
            if cached_data:
                return cached_data
        
        try:
            # Try to get from database first
            token_info = await self.db.get_token_info(mint)
            if token_info:
                self._set_cached_data("token_info", mint, token_info)
                return token_info
            
            # If not in database, fetch from external source
            self.metrics["api_calls"] += 1
            dex_data = await self.data_fetcher.fetch_dex_screener_data(mint)
            if dex_data and "pairs" in dex_data and dex_data["pairs"]:
                # Process and store the data
                processed_data = self._process_token_info(dex_data, mint)
                if processed_data:
                    # Store in database for future use
                    await self.db.store_token_info(mint, processed_data)
                    self._set_cached_data("token_info", mint, processed_data)
                    
                    # Notify subscribers
                    self._notify_subscribers("token_update", {
                        "mint": mint,
                        "token_info": processed_data
                    })
                    
                    return processed_data
            
            logger.warning(f"No token info found for {mint}")
            return None
                
        except Exception as e:
            logger.error(f"Error fetching token info for {mint}: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            
            # Return cached data as fallback if available
            cached_data = self._get_cached_data("token_info", mint)
            if cached_data:
                logger.info(f"Using cached token info for {mint} due to error")
                return cached_data
                
            return None

    def _process_token_info(self, dex_data: Dict[str, Any], mint: str) -> Optional[Dict[str, Any]]:
        """
        Process raw token data from DexScreener into a standardized format.
        
        Args:
            dex_data: Raw data from DexScreener
            mint: Token mint address
            
        Returns:
            Processed token information or None if processing fails
        """
        try:
            if not dex_data or "pairs" not in dex_data or not dex_data["pairs"]:
                return None
                
            # Find the pair with the highest liquidity
            best_pair = None
            max_liquidity = 0
            
            for pair in dex_data["pairs"]:
                liquidity = float(pair.get("liquidity", {}).get("usd", 0))
                if liquidity > max_liquidity:
                    max_liquidity = liquidity
                    best_pair = pair
            
            if not best_pair:
                return None
                
            # Extract token information
            base_token = best_pair.get("baseToken", {})
            quote_token = best_pair.get("quoteToken", {})
            
            return {
                "address": mint,
                "symbol": base_token.get("symbol", "Unknown"),
                "name": base_token.get("name", "Unknown Token"),
                "decimals": base_token.get("decimals", 9),
                "price_usd": float(best_pair.get("priceUsd", 0)),
                "price_native": float(best_pair.get("priceNative", 0)),
                "liquidity_usd": max_liquidity,
                "volume_24h": float(best_pair.get("volume", {}).get("h24", 0)),
                "pair_address": best_pair.get("pairAddress"),
                "quote_token_symbol": quote_token.get("symbol", "Unknown"),
                "quote_token_address": quote_token.get("address"),
                "dex": best_pair.get("dexId", "Unknown"),
                "last_updated": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error processing token info for {mint}: {e}", exc_info=True)
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            return None

    async def get_pool_data(self, pair_address: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]: # Renamed parameter
        """
        Get data for a liquidity pool (pair), using cache if available.
        
        Args:
            pair_address: Pair address (e.g., Raydium AMM ID)
            force_refresh: Whether to bypass cache and fetch fresh data
            
        Returns:
            Pair data or None if not available
        """
        if self.circuit_breaker.check():
            logger.warning("Circuit breaker active. Using cached pair data if available.") # Updated log message
        
        cache_key = pair_address # Use pair_address as cache key
        cache_type = "pair_data" # Use renamed cache type
        
        # Check cache first if not forcing refresh
        if not force_refresh:
            cached_data = self._get_cached_data(cache_type, cache_key) # Use updated cache type and key
            if cached_data:
                return cached_data
        
        try:
            # Fetch from Raydium
            self.metrics["api_calls"] += 1
            # Assuming data_fetcher.fetch_raydium_pool_data expects the pair address
            pool_data = await self.data_fetcher.fetch_raydium_pool_data(pair_address) # Pass pair_address
            if pool_data:
                self._set_cached_data(cache_type, cache_key, pool_data) # Use updated cache type and key
                return pool_data
            
            logger.warning(f"No pair data found for {pair_address}") # Updated log message
            return None
                
        except Exception as e:
            logger.error(f"Error fetching pair data for {pair_address}: {e}", exc_info=True) # Updated log message
            self.circuit_breaker.increment_failures()
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            
            # Return cached data as fallback if available
            cached_data = self._get_cached_data(cache_type, cache_key) # Use updated cache type and key
            if cached_data:
                logger.info(f"Using cached pair data for {pair_address} due to error") # Updated log message
                return cached_data
                
            return None

    async def get_historical_data(self, mint: str, timeframe: str = "1h", limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        """
        Get historical price data for a token.
        
        Args:
            mint: Token mint address
            timeframe: Timeframe for the data (e.g., "1m", "5m", "1h", "1d")
            limit: Number of data points to retrieve
            
        Returns:
            List of historical data points or None if not available
        """
        cache_key = f"{mint}:{timeframe}:{limit}"
        
        # Check cache first
        cached_data = self._get_cached_data("historical_data", cache_key)
        if cached_data:
            return cached_data
        
        try:
            self.metrics["api_calls"] += 1
            
            # Check if data_fetcher has the fetch_historical_data method
            if hasattr(self.data_fetcher, 'fetch_historical_data'):
                historical_data = await self.data_fetcher.fetch_historical_data(mint, timeframe, limit)
            else:
                logger.warning(f"DataFetcher does not have fetch_historical_data method. Skipping historical data for {mint}")
                historical_data = None
                
            if historical_data:
                self._set_cached_data("historical_data", cache_key, historical_data)
                return historical_data
            
            logger.warning(f"No historical data found for token {mint}")
            return None
                
        except Exception as e:
            logger.error(f"Error fetching historical data for {mint}: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            
            # Return cached data as fallback if available
            cached_data = self._get_cached_data("historical_data", cache_key)
            if cached_data:
                logger.info(f"Using cached historical data for {mint} due to error")
                return cached_data
                
            return None

    async def get_market_data(self, mint: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive market data for a token, combining multiple data sources.
        
        Args:
            mint: Token mint address
            force_refresh: Whether to bypass cache and fetch fresh data
            
        Returns:
            Comprehensive market data or None if not available
        """
        if self.circuit_breaker.check():
            logger.warning("Circuit breaker active. Using cached market data if available.")
        
        # Check cache first if not forcing refresh
        if not force_refresh:
            cached_data = self._get_cached_data("market_data", mint)
            if cached_data:
                return cached_data
        
        try:
            # Fetch data from multiple sources
            price_data = await self.get_token_price(mint, force_refresh=True)
            token_info = await self.get_token_info(mint, force_refresh=True)
            
            # Combine data
            market_data = {
                "mint": mint,
                "timestamp": datetime.now().isoformat(),
                "price": price_data,
                "token_info": token_info
            }
            
            # Add blockchain data if available
            blockchain_data = self._get_cached_data("blockchain_data", mint)
            if blockchain_data:
                market_data["blockchain"] = blockchain_data
            
            # Add historical data if available
            historical_data = await self.get_historical_data(mint, timeframe="1h", limit=24)
            if historical_data:
                market_data["historical"] = historical_data
            
            self._set_cached_data("market_data", mint, market_data)
            
            # Notify subscribers
            self._notify_subscribers("market_data_update", {
                "mint": mint,
                "market_data": market_data
            })
            
            return market_data
                
        except Exception as e:
            logger.error(f"Error fetching market data for {mint}: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            
            # Return cached data as fallback if available
            cached_data = self._get_cached_data("market_data", mint)
            if cached_data:
                logger.info(f"Using cached market data for {mint} due to error")
                return cached_data
                
            return None

    # --- Monitoring and Event Handling ---

    async def start_monitoring(self, monitored_programs: Optional[List[str]] = None):
        """
        Start monitoring all components (API data fetcher, price monitor, blockchain listener)
        This is the main entry point to activate real-time data collection.
        """
        if self.is_monitoring:
            self.logger.warning("Monitoring already started, ignoring request")
            return False
            
        try:
            self.logger.info("Starting monitoring components...")
            
            # Create BlockchainListener if needed
            if self.settings.USE_BLOCKCHAIN_LISTENER and not self.blockchain_listener:
                self.logger.info("Creating BlockchainListener...")
                self.blockchain_listener = BlockchainListener(
                    settings=self.settings,
                    logger=self.logger,
                    http_client=self.http_client
                )
            
            # Set up the callback handler for blockchain events (critical for price updates)
            if self.blockchain_listener:
                # Set the callback to our _handle_blockchain_update method
                self.blockchain_listener.set_callback(self._handle_blockchain_update)
                self.logger.info("Set blockchain listener callback to handle real-time updates")
            
                # **FIXED: Initialize and start the blockchain listener properly**
                # First initialize the listener with all program IDs
                listener_initialized = await self.blockchain_listener.initialize()
                if listener_initialized:
                    self.logger.info("🔌 BlockchainListener initialized successfully")
                    
                    # Start the main listening loop in the background
                    self._blockchain_listener_task = asyncio.create_task(self.blockchain_listener.run_forever())
                    self.logger.info("🎧 BlockchainListener run_forever() task started")
                else:
                    self.logger.error("❌ Failed to initialize BlockchainListener")
                
                self.logger.info("BlockchainListener monitoring started")
            else:
                self.logger.info("Blockchain listener not enabled or failed to initialize")
            
            # Mark monitoring as started
            self.is_monitoring = True
            self.logger.info("Market data monitoring successfully started")
            return True
            
        except Exception as e:
            self.logger.error(f"Error starting monitoring: {e}", exc_info=True)
            return False

    async def stop_monitoring(self):
        self.logger.info("Stopping monitoring")
        self.is_monitoring = False
        # Removed check for self.monitor_task as it's not set by start_monitoring
        # The relevant task, _blockchain_listener_task, is handled below.

        if self._blockchain_listener_task and not self._blockchain_listener_task.done():
            self.logger.info("Attempting to cancel Blockchain Listener task...")
            self._blockchain_listener_task.cancel()
            try:
                await self._blockchain_listener_task
            except asyncio.CancelledError:
                self.logger.info("Blockchain Listener task was cancelled successfully.")
            except Exception as e_cancel:
                self.logger.error(f"Error cancelling Blockchain Listener task: {e_cancel}")

    async def _monitor_loop(self):
        """Background task that monitors tokens and updates data."""
        last_indicator_log = {}  # Track last log time per token
        
        try:
            while self.is_monitoring:
                if self.circuit_breaker.check():
                    logger.warning("Circuit breaker active. Pausing monitoring.")
                    await asyncio.sleep(30)  # Wait longer when circuit breaker is active
                    continue
                
                # Update prices
                if self.tokens_to_monitor:
                    logger.debug(f"MarketData _monitor_loop: Processing tokens: {list(self.tokens_to_monitor)}") # ADDED DEBUG LOG
                    await self.price_monitor.update_prices(list(self.tokens_to_monitor))
                    
                    # Update market data and log indicators for each token
                    current_time = time.time()
                    for token in self.tokens_to_monitor:
                        # Only log indicators every minute
                        if token not in last_indicator_log or (current_time - last_indicator_log[token]) >= 60:
                            try:
                                # Get token data
                                token_data = await self.get_market_data(token, force_refresh=True)
                                if token_data:
                                    # Get indicators
                                    indicators = await self.get_trading_signals(token)
                                    if indicators:
                                        # Log compact indicator summary
                                        price = token_data.get('price', 0)
                                        volume = token_data.get('volume24h', 0)
                                        rsi = indicators.get('rsi', 0)
                                        macd = indicators.get('macd', 0)
                                        logger.info(f"Token {token[:8]}... P=${price:.6f} V=${volume:.2f} RSI={rsi:.1f} MACD={macd:.6f}")
                                        last_indicator_log[token] = current_time
                            except Exception as e:
                                logger.error(f"Error updating indicators for {token}: {str(e)}")
                
                await asyncio.sleep(self.settings.MARKETDATA_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Monitoring task cancelled")
        except Exception as e:
            logger.error(f"Error in monitoring task: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            self.is_monitoring = False

    # --- Event Subscription ---

    def subscribe(self, event_type: str, callback: Callable):
        """
        Subscribe to market data events.
        
        Args:
            event_type: Type of event to subscribe to
            callback: Callback function to invoke when event occurs
        """
        # Ensure the subscribers dictionary exists
        if not hasattr(self, 'subscribers'):
            self.subscribers = {
                "price_update": set(),
                "token_update": set(),
                "blockchain_event": set(),
                "market_data_update": set(),
                "realtime_price_update": set(),
            }
            self.logger.debug("Creating subscribers dictionary on demand")
        
        if event_type not in self.subscribers:
            self.logger.warning(f"Invalid event type: {event_type}")
            return
            
        self.subscribers[event_type].add(callback)
        self.logger.info(f"Added subscriber for {event_type} events")

    def unsubscribe(self, event_type: str, callback: Callable):
        """
        Unsubscribe from market data events.
        
        Args:
            event_type: Type of event to unsubscribe from
            callback: Callback function to remove
        """
        # Ensure the subscribers dictionary exists
        if not hasattr(self, 'subscribers'):
            self.logger.warning("Cannot unsubscribe: subscribers dictionary does not exist")
            return
            
        if event_type not in self.subscribers:
            self.logger.warning(f"Invalid event type: {event_type}")
            return
            
        if callback in self.subscribers[event_type]:
            self.subscribers[event_type].remove(callback)
            self.logger.info(f"Removed subscriber for {event_type} events")

    def _notify_subscribers(self, event_type: str, data: Any):
        """
        Notify all subscribers of an event.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        # Ensure the subscribers dictionary exists
        if not hasattr(self, 'subscribers'):
            self.logger.warning("Cannot notify subscribers: subscribers dictionary does not exist")
            return
            
        if event_type not in self.subscribers:
            return
            
        self.logger.debug(f"Notifying subscribers for event: {event_type}")
        # Create a copy of the set to avoid issues if a callback modifies the set
        callbacks_to_notify = list(self.subscribers[event_type])
        for callback in callbacks_to_notify:
            try:
                # Check if the callback is an async function
                if asyncio.iscoroutinefunction(callback):
                    # Schedule the coroutine
                    asyncio.create_task(callback(data))
                else:
                    # Execute synchronous callback directly
                    callback(data)
            except Exception as e:
                self.logger.error(f"Error executing callback {callback.__name__} for event {event_type}: {e}", exc_info=True)

    # --- Blockchain Event Processing --- #


        
    def _parse_pumpfun_trade_event(self, logs: List[str], signature: str) -> Optional[Dict[str, Any]]:
        """
        Parse a Pump.fun trade event from transaction logs
        
        Args:
            logs: List of transaction log messages
            signature: Transaction signature
            
        Returns:
            Optional[Dict]: Parsed trade event data, or None if parsing failed
        """
        try:
            logger = self.logger
            
            # Try to find the event log (contains "Program data:" line)
            event_data_log = None
            for log in logs:
                if "Program data:" in log:
                    event_data_log = log
                    break
            
            if not event_data_log:
                logger.debug(f"No program data found in logs for signature {signature}")
                return None
                
            # Extract base64 data after "Program data: "
            base64_data = event_data_log.split("Program data: ")[1].strip()
            
            # Decode base64 data
            try:
                import base64
                decoded_data = base64.b64decode(base64_data)
                
                # If we have the Borsh schema available, try to parse the data
                if hasattr(self, '_trade_event_layout') and self._trade_event_layout:
                    # Attempt to parse directly using the TradeEventSchema
                    try:
                        parsed_event = self._trade_event_layout.parse(decoded_data)
                        logger.info(f"Successfully parsed Pump.fun TradeEvent using Borsh. Sig: {signature}")
                        
                        # Convert parsed data into a standardized format
                        parsed_data = {
                            "last_event_id": parsed_event.last_event_id,
                            "token_mint": str(parsed_event.token_mint_key),
                            "event_type": "buy" if parsed_event.event_type == 0 else "sell",
                            "token_amount": parsed_event.total_token_amount,
                            "usdc_amount": parsed_event.total_usdc_amount,
                            "token_price": parsed_event.token_price / 10**6,  # Convert to USDC
                            "liquidity_fee": parsed_event.liquidity_fee,
                            "treasury_fee": parsed_event.treasury_fee,
                            "tokens_outstanding": parsed_event.tokens_outstanding,
                            "reserve_balance": parsed_event.reserve_balance,
                            "source": "pumpfun_borsh" # Indicate source
                        }
                        
                        return parsed_data
                    except Exception as e:
                        logger.error(f"Error parsing Pump.fun TradeEvent with Borsh: {e}")
                        # Continue to try other parsing methods
                
                # Fallback to regex/text parsing if Borsh parsing fails
                # TODO: Implement regex parsing fallback
                
                return None  # No successful parsing
                
            except Exception as base64_error:
                logger.error(f"Error decoding base64 data: {base64_error}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error parsing Pump.fun trade event: {e}", exc_info=True)
            return None





    async def process_blockchain_event(self, event_data: Dict[str, Any]):
        """
        Process a blockchain event notification - FIXED to handle real events from blockchain listener.
        Parse blockchain logs to extract price, volume, liquidity info.
        """
        try:
            # FIXED: Handle the actual event structure from blockchain listener
            event_type = event_data.get('type')
            
            if event_type == "blockchain_event":
                # Extract basic event info
                program_id = event_data.get('program_id')
                signature = event_data.get('signature', 'unknown')[:8]
                logs = event_data.get('logs', [])
                has_swap = event_data.get('has_swap_activity', False)
                
                self.logger.debug(f"🔄 Processing blockchain event: Program {program_id[:8] if program_id else 'unknown'}... | TX {signature}... | {len(logs)} logs | Swap: {has_swap}")
                
                # Only process if it has swap activity
                if not has_swap or not logs:
                    return
                
                # FIXED: Parse logs through the appropriate DEX parser
                dex_name = None
                for name, prog_id in self.settings.DEX_PROGRAM_IDS.items():
                    if prog_id == program_id:
                        dex_name = name
                        break
                
                if not dex_name:
                    self.logger.debug(f"No DEX mapping found for program {program_id[:8] if program_id else 'unknown'}...")
                    return
                
                # Get the appropriate parser
                parser = None
                try:
                    if dex_name == 'pumpswap':
                        from data.pumpswap_parser import PumpSwapParser
                        parser = PumpSwapParser(self.settings, logger=self.logger)
                    elif dex_name == 'raydium_v4':
                        from data.raydium_v4_parser import RaydiumV4Parser
                        parser = RaydiumV4Parser(self.settings, logger=self.logger)
                    elif dex_name == 'raydium_clmm':
                        from data.raydium_clmm_parser import RaydiumClmmParser  
                        parser = RaydiumClmmParser(self.settings, logger=self.logger)
                except ImportError as e:
                    self.logger.warning(f"Parser not available for {dex_name}: {e}")
                    return
                
                if not parser:
                    self.logger.debug(f"No parser available for DEX {dex_name}")
                    return
                
                # Parse the logs
                try:
                    swap_data = parser.parse_swap_logs(logs, signature)
                    if swap_data:
                        self.logger.info(f"✅ Parsed {dex_name.upper()} swap data: {swap_data}")
                        
                        # Process the parsed swap data
                        await self._process_parsed_swap(swap_data, None, dex_name)
                    else:
                        self.logger.debug(f"No swap data extracted from {dex_name} logs")
                except Exception as parse_error:
                    self.logger.warning(f"Error parsing {dex_name} logs: {parse_error}")
                    
            else:
                self.logger.debug(f"Unhandled event type: {event_type}")
                
        except Exception as e:
            self.logger.error(f"Error processing blockchain event: {e}", exc_info=True)

    async def start_monitoring_token(self, mint: str) -> bool:
        """
        Start monitoring a specific token for real-time price updates.
        
        Args:
            mint: The token mint address to monitor
            
        Returns:
            bool: True if monitoring started successfully, False otherwise
        """
        if not mint:
            logger.error("Cannot start monitoring: No mint address provided")
            return False
            
        logger.info(f"Starting monitoring for token: {mint}")
        
        # Stop any existing monitoring
        if self.is_monitoring_active and self.current_monitored_mint:
            await self.stop_monitoring_token(self.current_monitored_mint)
            
        try:
            # Add token to price monitor
            self.price_monitor.add_token(mint)
            
            # Start price parser monitoring for this token
            await self._start_price_parser_monitoring(mint)
            
            # Update state
            self.current_monitored_mint = mint
            self.is_monitoring_active = True
            
            logger.info(f"Successfully started monitoring token: {mint}")
            return True
        except Exception as e:
            logger.error(f"Failed to start monitoring token {mint}: {str(e)}")
            self.is_monitoring_active = False
            self.current_monitored_mint = None
            return False
    
    async def stop_monitoring_token(self, mint: str) -> bool:
        """
        Stop monitoring a specific token.
        
        Args:
            mint: The token mint address to stop monitoring
            
        Returns:
            bool: True if monitoring stopped successfully, False otherwise
        """
        if not self.is_monitoring_active or mint != self.current_monitored_mint:
            logger.warning(f"Not currently monitoring token: {mint}")
            return True
            
        logger.info(f"Stopping monitoring for token: {mint}")
        
        try:
            # Remove token from price monitor (PriceMonitor doesn't have a stop method)
            # Instead, we just remove it from tokens_being_monitored set
            if hasattr(self.price_monitor, 'tokens_being_monitored') and mint in self.price_monitor.tokens_being_monitored:
                self.price_monitor.tokens_being_monitored.discard(mint)
                logger.info(f"Removed {mint} from PriceMonitor.tokens_being_monitored")
            
            # Stop price parser monitoring for this token
            await self._stop_price_parser_monitoring(mint)
            
            # Update state
            self.is_monitoring_active = False
            self.current_monitored_mint = None
            
            logger.info(f"Successfully stopped monitoring token: {mint}")
            return True
        except Exception as e:
            logger.error(f"Error stopping monitoring for token {mint}: {str(e)}")
            return False
    
    async def get_current_monitoring_status(self) -> dict:
        """
        Get the current monitoring status.
        
        Returns:
            dict: Information about current monitoring status
        """
        return {
            "is_active": self.is_monitoring_active,
            "current_mint": self.current_monitored_mint,
            "tokens_being_monitored": len(self.price_monitor.tokens_being_monitored) if hasattr(self.price_monitor, 'tokens_being_monitored') else 0,
            "data_points": len(self.price_monitor.get_price_history(self.current_monitored_mint)) if self.current_monitored_mint else 0
        }
        
    # This duplicate close() method has been removed.
    # The close() method at line 265 already handles all necessary cleanup.

    async def initialize_blockchain_listener(self):
        """Initialize and start the blockchain listener for real-time price monitoring"""
        if self.blockchain_listener:
            self.logger.warning("Blockchain listener already initialized")
            return
            
        try:
            # Import here to avoid circular imports
            from data.blockchain_listener import BlockchainListener
            
            # Initialize the blockchain listener with our callback
            self.blockchain_listener = BlockchainListener(
                settings=self.settings,
                callback=self.process_blockchain_event,
                solana_client=self.solana_client,
                multi_connection_mode=True
            )
            
            # Initialize and start listening
            await self.blockchain_listener.initialize()
            # self.blockchain_listener.start_listening() # REMOVED - run_forever is started by main.py
            
            self.logger.info("Blockchain listener initialized for real-time price updates")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize blockchain listener: {e}", exc_info=True)
            return False

    async def update_token_price(self, mint: str, price: float, source: str = "api"):
        """
        Update the price of a token and notify subscribers.
        
        Args:
            mint: The token's mint address
            price: The new price
            source: Source of the price update ('api' or 'blockchain')
        """
        # Update our internal cache
        self._token_prices[mint] = {
            'price': price,
            'timestamp': int(time.time())
        }
        
        # Update the token database if available
        if self.token_db:
            await self.token_db.update_token_price(mint, price)
            
        # Notify subscribers (this would be implemented based on your architecture)
        # For example: await self.notify_price_update(mint, price, source)
        
    async def update_token_liquidity(self, mint: str, liquidity: float):
        """Update token liquidity information in the database"""
        if self.token_db:
            await self.token_db.update_token_liquidity(mint, liquidity)
            
    async def update_token_volume(self, mint: str, volume_increment: float):
        """Update token volume information in the database"""
        if self.token_db:
            # This assumes your token DB has a method to increment volume rather than set it
            await self.token_db.increment_token_volume(mint, volume_increment)

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on all components.
        
        Returns:
            Dictionary with health status of each component
        """
        health_status = {
            "service": "ok",
            "data_fetcher": "unknown",
            "price_monitor": "unknown",
            "blockchain_listener": "unknown",
            "circuit_breaker": "ok" if not self.circuit_breaker.is_active() else "active",
            "cache": "ok",
            "database": "unknown"
        }
        
        try:
            # Check data fetcher
            if self.data_fetcher:
                try:
                    # Try a simple operation
                    test_data = await self.data_fetcher.fetch_dex_screener_data("So11111111111111111111111111111111111111112")  # SOL token
                    health_status["data_fetcher"] = "ok" if test_data else "error"
                except Exception as e:
                    health_status["data_fetcher"] = f"error: {str(e)}"
            
            # Check price monitor
            if self.price_monitor:
                try:
                    # Try a simple operation
                    test_prices = await self.price_monitor.fetch_prices(["So11111111111111111111111111111111111111112"])
                    health_status["price_monitor"] = "ok" if test_prices else "error"
                except Exception as e:
                    health_status["price_monitor"] = f"error: {str(e)}"
            
            # Check blockchain listener
            if self.blockchain_listener:
                try:
                    # Check if listener is connected
                    health_status["blockchain_listener"] = "ok" if self.blockchain_listener.is_connected() else "disconnected"
                except Exception as e:
                    health_status["blockchain_listener"] = f"error: {str(e)}"
            
            # Check database
            if self.db:
                try:
                    # Try a simple operation
                    test_token = await self.db.get_token_info("So11111111111111111111111111111111111111112")
                    health_status["database"] = "ok"
                except Exception as e:
                    health_status["database"] = f"error: {str(e)}"
            
            # Overall service health
            if any(status != "ok" and status != "active" and status != "disconnected" for status in health_status.values() if status != "service"): # Check for actual errors
                health_status["service"] = "degraded"
            
            return health_status
            
        except Exception as e:
            logger.error(f"Error during health check: {e}", exc_info=True)
            health_status["service"] = "error"
            return health_status

    # --- Data Export ---

    async def export_market_data(self, mints: List[str], format: str = "json") -> Optional[str]:
        """
        Export market data for specified tokens in the requested format.
        
        Args:
            mints: List of token mint addresses to export
            format: Export format (json, csv)
            
        Returns:
            Exported data as string or None if export fails
        """
        try:
            # Fetch market data for all tokens
            market_data = await self.get_market_data_batch(mints)
            
            if format.lower() == "json":
                return json.dumps(market_data, indent=2)
            
            elif format.lower() == "csv":
                import csv
                import io
                
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Write header
                writer.writerow(["mint", "symbol", "price_usd", "liquidity_usd", "volume_24h", "timestamp"])
                
                # Write data
                for mint, data in market_data.items():
                    if data and "token_info" in data:
                        token_info = data["token_info"]
                        price = data.get("price", {}).get("price", 0)
                        writer.writerow([
                            mint,
                            token_info.get("symbol", "Unknown"),
                            price,
                            token_info.get("liquidity_usd", 0),
                            token_info.get("volume_24h", 0),
                            data.get("timestamp", datetime.now().isoformat())
                        ])
                
                return output.getvalue()
            
            else:
                logger.error(f"Unsupported export format: {format}")
                return None
                
        except Exception as e:
            logger.error(f"Error exporting market data: {e}", exc_info=True)
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            return None

    # --- Integration with Trading System ---

    async def get_trading_signals(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Generate trading signals based on market data.
        
        Args:
            mint: Token mint address to generate signals for
            
        Returns:
            Trading signals or None if generation fails
        """
        try:
            # Get comprehensive market data
            market_data = await self.get_market_data(mint)
            if not market_data:
                return None
            
            # Extract relevant data
            price_data = market_data.get("price", {})
            token_info = market_data.get("token_info", {})
            historical_data = market_data.get("historical", [])
            
            if not price_data or not token_info:
                return None
            
            # Calculate basic indicators
            current_price = price_data.get("price", 0)
            price_change_24h = token_info.get("price_change_24h", 0)
            volume_24h = token_info.get("volume_24h", 0)
            liquidity_usd = token_info.get("liquidity_usd", 0)
            
            # Generate signals
            signals = {
                "mint": mint,
                "timestamp": datetime.now().isoformat(),
                "current_price": current_price,
                "price_change_24h": price_change_24h,
                "volume_24h": volume_24h,
                "liquidity_usd": liquidity_usd,
                "signals": {}
            }
            
            # Price momentum signal
            if price_change_24h > 5:
                signals["signals"]["price_momentum"] = "strong_buy"
            elif price_change_24h > 2:
                signals["signals"]["price_momentum"] = "buy"
            elif price_change_24h < -5:
                signals["signals"]["price_momentum"] = "strong_sell"
            elif price_change_24h < -2:
                signals["signals"]["price_momentum"] = "sell"
            else:
                signals["signals"]["price_momentum"] = "neutral"
            
            # Volume signal
            if volume_24h > liquidity_usd * 0.5:
                signals["signals"]["volume"] = "high"
            elif volume_24h > liquidity_usd * 0.2:
                signals["signals"]["volume"] = "medium"
            else:
                signals["signals"]["volume"] = "low"
            
            # Liquidity signal
            if liquidity_usd > 100000:
                signals["signals"]["liquidity"] = "high"
            elif liquidity_usd > 100000:
                signals["signals"]["liquidity"] = "medium"
            else:
                signals["signals"]["liquidity"] = "low"
            
            # Overall signal
            if signals["signals"]["price_momentum"] in ["strong_buy", "buy"] and signals["signals"]["liquidity"] in ["high", "medium"]:
                signals["signals"]["overall"] = "buy"
            elif signals["signals"]["price_momentum"] in ["strong_sell", "sell"] and signals["signals"]["liquidity"] in ["high", "medium"]:
                signals["signals"]["overall"] = "sell"
            else:
                signals["signals"]["overall"] = "hold"
            
            return signals
                
        except Exception as e:
            logger.error(f"Error generating trading signals for {mint}: {e}", exc_info=True)
            self.metrics["errors"] += 1
            self.metrics["last_error"] = str(e)
            self.metrics["last_error_time"] = datetime.now().isoformat()
            return None

    # --- NEW: Real-time Streaming Control ---

    async def start_streaming(self, mint: str, pair_address: Optional[str] = None, dex_id: Optional[str] = None):
        """
        Initiates real-time data streaming for a specific token mint.
        Fetches initial pool/curve state and subscribes to relevant blockchain logs.

        Args:
            mint_address: The token mint address to start streaming for.
            pair_address: Optional. The associated AMM pair address (if known).
            dex_id: Optional. The DEX identifier ('raydium_v4', 'pumpswap', 'pumpfun') (if known).
        """
        logger.info(f"Request received to start streaming for mint: {mint}")

        if mint in self.actively_streamed_mints:
            logger.info(f"Streaming already active for mint: {mint}. Skipping.")
            return

        # --- Resolve Pair Address and DEX ID if not provided ---
        if not pair_address or not dex_id:
            logger.debug(f"Pair address or dex_id missing for {mint}. Attempting DB lookup...")
            try:
                token_info = await self.db.get_token_info(mint)
                if token_info:
                    # Use fetched info only if existing args are None
                    pair_address = pair_address or token_info.get("pair_address")
                    dex_id = dex_id or token_info.get("dex_id")
                    logger.info(f"Found pair_address='{pair_address}', dex_id='{dex_id}' in DB for {mint}.")
                else:
                    logger.warning(f"No token info found in DB for mint {mint}. Cannot determine pair/dex.")
                    # Decide if we should proceed without pair/dex (e.g., only Pump.fun if ID is known?)
                    # For now, require pair/dex for AMMs. Pump.fun might subscribe by program ID only later.
                    # Let's check if dex_id *could* be 'pumpfun' even without DB info
                    # if self.settings.DEX_PROGRAM_IDS.get('pumpfun') == <potential_program_id_from_context?>:
                    #     dex_id = 'pumpfun'
                    # else:
                    logger.error(f"Cannot start streaming for {mint}: Missing DB info and cannot determine pair/dex.")
                    return

            except Exception as db_err:
                logger.error(f"DB error fetching token info for {mint}: {db_err}. Cannot start streaming.")
                return

        # Validate final pair_address and dex_id
        if not dex_id: # Check only dex_id as pair_address is not needed for pump.fun program subscription
            logger.error(f"Failed to resolve dex_id for {mint} after DB lookup. Cannot start streaming.")
            return
            
        # --- Subscribe via BlockchainListener ---
        subscription_successful = False
        if not self.blockchain_listener:
            logger.error(f"BlockchainListener not initialized. Cannot subscribe for {mint}.")
            return

        # MODIFIED: Use self.settings.PUMPFUN_PROGRAM_ID
        if dex_id == 'pumpfun':
            logger.info(f"Attempting to subscribe to Pump.fun program events (Program ID: {self.settings.PUMPFUN_PROGRAM_ID}) for mint: {mint}")
            # The listener's subscribe_to_pumpfun_events should ideally use settings.PUMPFUN_PROGRAM_ID
            subscription_successful = await self.blockchain_listener.subscribe_to_pumpfun_events(mint) 

        # MODIFIED: Use self.settings.PUMPSWAP_PROGRAM_ID for 'pumpswap' dex_id
        elif dex_id == 'pumpswap':
            if not pair_address:
                logger.error(f"Pair address is required for PUMPSWAP AMM subscription (Mint: {mint}). Cannot subscribe.")
                return
            logger.info(f"Attempting to subscribe to PumpSwap AMM (Program ID: {self.settings.PUMPSWAP_PROGRAM_ID}) pool logs for pair: {pair_address} (Mint: {mint})")
            subscription_successful = await self.blockchain_listener.subscribe_to_pool_account(pair_address, dex_id)


        elif dex_id in ['raydium_v4', 'raydium']: # ADD 'raydium' here
            # AMMs use specific pool log subscriptions
            # Treat generic 'raydium' the same as 'raydium_v4' for subscription purposes
            actual_dex_id_for_listener = 'raydium_v4' if dex_id == 'raydium' else dex_id
            logger.info(f"Attempting to subscribe to {actual_dex_id_for_listener} pool (account then logs) for pair: {pair_address} (Mint: {mint}) using original dex_id '{dex_id}'")
            subscription_successful = await self.blockchain_listener.subscribe_to_pool_account(pair_address, actual_dex_id_for_listener)

        else:
            logger.warning(f"Unsupported dex_id '{dex_id}' for streaming subscription for mint {mint}. Skipping subscription.")
            # Don't mark as actively streamed if subscription is skipped

        # --- Fetch Initial State & Mark Active ---
        if subscription_successful:
            logger.info(f"Blockchain subscription request successful for {dex_id} (Mint: {mint}, Context: {pair_address if dex_id != 'pumpfun' else 'program_sub'}). Fetching initial state...")
            # Fetch initial state regardless of subscription *confirmation* timing,
            # as the state is needed immediately for potential incoming events.
            fetched = await self._fetch_initial_pool_state(pair_address, dex_id, mint)
            if fetched:
                self.actively_streamed_mints.add(mint)
                logger.info(f"Successfully fetched initial state and marked mint {mint} as actively streamed.")
            else:
                logger.error(f"Failed to fetch initial state for {mint} ({pair_address}, {dex_id}) after successful subscription request. Streaming may be incomplete.")
                # Keep subscription attempt but don't mark as active? Or mark active but log error?
                # Let's mark active but with the error logged.
                self.actively_streamed_mints.add(mint)
        else:
            logger.error(f"Blockchain subscription request failed for {dex_id} (Mint: {mint}, Context: {pair_address if dex_id != 'pumpfun' else 'program_sub'}). Cannot reliably stream.")
            # Do not mark as actively streamed

    async def stop_streaming(self, mint_address: str):
        """
        Stops real-time data streaming for a specific token mint.
        Unsubscribes from relevant blockchain logs.

        Args:
            mint_address: The token mint address to stop streaming for.
        """
        logger.info(f"Request received to stop streaming for mint: {mint_address}")

        if mint_address not in self.actively_streamed_mints:
            logger.warning(f"Streaming not currently active for mint: {mint_address}. Skipping.")
            return
            
        # --- Resolve Pair Address and DEX ID ---
        pair_address: Optional[str] = None
        dex_id: Optional[str] = None
        try:
            token_info = await self.db.get_token_info(mint_address)
            if token_info:
                pair_address = token_info.get("pair_address")
                dex_id = token_info.get("dex_id")
            else:
                logger.warning(f"No token info found in DB for mint {mint_address} during stop_streaming. Cannot determine pair/dex for unsubscribe.")
                # Fallback: Check realtime state cache?
                for p_addr, state in self._realtime_pair_state.items():
                    if state.get('mint') == mint_address:
                        pair_address = p_addr
                        dex_id = state.get('dex')
                        logger.info(f"Found pair/dex info from realtime state cache for {mint_address}: {pair_address}, {dex_id}")
                        break
                    if not pair_address or not dex_id:
                        logger.error(f"Cannot determine pair/dex for {mint_address} from DB or cache. Unsubscribe may fail.")
                        # Attempt Pump.fun unsubscribe as a guess?
                        dex_id = 'pumpfun' # Best guess without info

        except Exception as db_err:
            logger.error(f"DB error fetching token info for {mint_address} during stop_streaming: {db_err}. Unsubscribe may fail.")
            # Attempt Pump.fun unsubscribe as a guess?
            dex_id = 'pumpfun' # Best guess without info

        # --- Unsubscribe via BlockchainListener ---
        unsubscription_successful = False
        if not self.blockchain_listener:
            logger.error(f"BlockchainListener not initialized. Cannot unsubscribe for {mint_address}.")
            # Remove from active set anyway to reflect intent
            self.actively_streamed_mints.discard(mint_address)
            return

        # MODIFIED: Use self.settings.PUMPFUN_PROGRAM_ID logic for 'pumpfun'
        if dex_id == 'pumpfun':
            logger.info(f"Attempting to unsubscribe from Pump.fun program events (Program ID: {self.settings.PUMPFUN_PROGRAM_ID}) for mint: {mint_address}")
            # This should ensure the listener unsubscribes from the PUMPFUN_PROGRAM_ID if it's the last token for that program.
            unsubscription_successful = await self.blockchain_listener.unsubscribe_from_pumpfun_events(mint_address)
        
        # MODIFIED: Use self.settings.PUMPSWAP_PROGRAM_ID logic for 'pumpswap'
        elif dex_id == 'pumpswap' and pair_address:
            logger.info(f"Attempting to unsubscribe from PumpSwap AMM (Program ID: {self.settings.PUMPSWAP_PROGRAM_ID}) pool logs for pair: {pair_address} (Mint: {mint_address})")
            unsubscription_successful = await self.blockchain_listener.unsubscribe_from_pool_data(pair_address) # dex_id here is 'pumpswap'

        elif dex_id in ['raydium_v4', 'pumpswap'] and pair_address: # Original 'pumpswap' was likely a typo for raydium variant here
            # AMMs use specific pool log subscriptions
            logger.info(f"Attempting to unsubscribe from {dex_id} pool logs for pair: {pair_address} (Mint: {mint_address})")
            unsubscription_successful = await self.blockchain_listener.unsubscribe_from_pool_data(pair_address)

        else:
            logger.warning(f"Unsupported/missing dex_id ('{dex_id}') or pair_address ('{pair_address}') for unsubscribe for mint {mint_address}. Cannot send unsubscribe request.")

        # --- Mark Inactive ---
        self.actively_streamed_mints.discard(mint_address)
        if unsubscription_successful:
            logger.info(f"Successfully sent unsubscribe request and marked mint {mint_address} as inactive for streaming.")
        else:
            logger.warning(f"Failed to send unsubscribe request for {mint_address}, but marked as inactive anyway.")

        # Optional: Clear real-time state for this pair?
        if pair_address and pair_address in self._realtime_pair_state:
            del self._realtime_pair_state[pair_address]
            logger.info(f"Cleared real-time state cache for pair {pair_address}.")

    # --- NEW: Fetch Initial State --- #

    async def _fetch_initial_pool_state(self, pair_address: str, dex_id: str, mint_address: str) -> bool:
        """
        Enhanced method to fetch initial pool state with retry mechanisms and better error handling.
        """
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Attempt {attempt + 1}/{max_retries}: Fetching initial pool state for pair {pair_address[:8]}...")
                
                if not self.solana_client:
                    self.logger.warning(f"No Solana client available for initial state fetch (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2 ** attempt))
                        continue
                    return False
                
                # Enhanced pool data fetching with timeout
                try:
                    pool_data = await asyncio.wait_for(
                        self.get_pool_data(pair_address, force_refresh=True),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    self.logger.warning(f"Timeout fetching pool data for {pair_address[:8]} (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2 ** attempt))
                        continue
                    return False
                
                if pool_data:
                    # Store the pool-to-token mapping for future event processing
                    self.pool_to_tokens[pair_address] = {
                        "mint": mint_address,
                        "dex_id": dex_id,
                        "fetched_at": time.time(),
                        "reserve_a": pool_data.get("reserve_a"),
                        "reserve_b": pool_data.get("reserve_b"),
                        "last_price": pool_data.get("price")
                    }
                    
                    self.logger.info(f"✅ Successfully fetched initial pool state for {pair_address[:8]} (attempt {attempt + 1})")
                    
                    # Log helpful initial state info
                    if pool_data.get("price"):
                        self.logger.info(f"Initial price for {mint_address[:8]}: ${pool_data['price']}")
                    if pool_data.get("liquidity_sol"):
                        self.logger.info(f"Initial liquidity: {pool_data['liquidity_sol']:.2f} SOL")
                        
                    return True
                else:
                    self.logger.warning(f"No pool data returned for {pair_address[:8]} (attempt {attempt + 1})")
                    
            except Exception as e:
                error_msg = f"Error fetching initial pool state for {pair_address[:8]} (attempt {attempt + 1}): {e}"
                if attempt == max_retries - 1:
                    self.logger.error(error_msg, exc_info=True)
                else:
                    self.logger.warning(error_msg)
                    
            # Wait before retry with exponential backoff
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                self.logger.info(f"Retrying in {delay}s...")
                await asyncio.sleep(delay)
                
        self.logger.error(f"❌ Failed to fetch initial pool state for {pair_address[:8]} after {max_retries} attempts")
        return False

    async def _enhanced_websocket_reconnection(self, program_id_str: str, max_retries: int = 5):
        """
        Enhanced WebSocket reconnection logic with exponential backoff and health checking.
        """
        base_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Attempting WebSocket reconnection for {program_id_str[:8]}... (attempt {attempt + 1}/{max_retries})")
                
                # Clean up any existing connection
                if program_id_str in self.ws_connections:
                    try:
                        old_ws = self.ws_connections[program_id_str]
                        if hasattr(old_ws, 'close'):
                            await old_ws.close()
                    except Exception as e:
                        self.logger.debug(f"Error closing old connection: {e}")
                    finally:
                        del self.ws_connections[program_id_str]
                        
                # Wait before attempting connection
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    self.logger.info(f"Waiting {delay}s before reconnection attempt...")
                    await asyncio.sleep(delay)
                
                # Attempt new connection through existing mechanism
                success = await self._establish_connection_for_program(program_id_str)
                
                if success:
                    self.logger.info(f"✅ Successfully reconnected WebSocket for {program_id_str[:8]} (attempt {attempt + 1})")
                    
                    # Verify connection health
                    await asyncio.sleep(1.0)  # Give connection time to stabilize
                    ws = self.ws_connections.get(program_id_str)
                    if ws and self._is_connection_open(ws):
                        self.logger.info(f"✅ WebSocket connection verified healthy for {program_id_str[:8]}")
                        return True
                    else:
                        self.logger.warning(f"WebSocket connection appears unhealthy after reconnect for {program_id_str[:8]}")
                        
            except Exception as e:
                error_msg = f"Reconnection attempt {attempt + 1} failed for {program_id_str[:8]}: {e}"
                if attempt == max_retries - 1:
                    self.logger.error(error_msg, exc_info=True)
                else:
                    self.logger.warning(error_msg)
                    
        self.logger.error(f"❌ Failed to reconnect WebSocket for {program_id_str[:8]} after {max_retries} attempts")
        return False

    async def _handle_websocket_error(self, program_id_str: str, error: Exception, context: str = ""):
        """
        Centralized WebSocket error handling with smart recovery strategies.
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()
        
        self.logger.warning(f"WebSocket error for {program_id_str[:8]} ({context}): {error_type} - {error}")
        
        # Categorize error severity and recovery strategy
        should_reconnect = False
        immediate_retry = False
        
        # Connection-related errors (reconnect immediately)
        if any(keyword in error_msg for keyword in ['connection', 'closed', 'reset', 'timeout']):
            should_reconnect = True
            self.logger.info(f"Connection error detected for {program_id_str[:8]}, will attempt reconnection")
            
        # Rate limiting or server errors (wait before retry)
        elif any(keyword in error_msg for keyword in ['rate limit', '429', 'too many requests']):
            should_reconnect = True
            await asyncio.sleep(5.0)  # Wait before reconnecting
            self.logger.info(f"Rate limit detected for {program_id_str[:8]}, waited 5s before reconnection")
            
        # Temporary server issues (immediate retry once)
        elif any(keyword in error_msg for keyword in ['500', '502', '503', 'server error', 'internal error']):
            immediate_retry = True
            self.logger.info(f"Server error detected for {program_id_str[:8]}, will retry immediately once")
            
        # Authentication or permanent errors (don't reconnect)
        elif any(keyword in error_msg for keyword in ['401', '403', 'unauthorized', 'forbidden']):
            self.logger.error(f"Authentication error for {program_id_str[:8]}, will not attempt reconnection")
            return False
            
        # Unknown errors (reconnect with caution)
        else:
            should_reconnect = True
            await asyncio.sleep(2.0)  # Brief wait for unknown errors
            
        if immediate_retry:
            # Single immediate retry for temporary issues
            try:
                await asyncio.sleep(0.5)
                return await self._establish_connection_for_program(program_id_str)
            except Exception as retry_error:
                self.logger.warning(f"Immediate retry failed for {program_id_str[:8]}: {retry_error}")
                should_reconnect = True
                
        if should_reconnect:
            return await self._enhanced_websocket_reconnection(program_id_str)
            
        return False

    async def _monitor_websocket_health(self):
        """
        Background task to monitor WebSocket health and automatically recover failed connections.
        """
        check_interval = 30.0  # Check every 30 seconds
        
        while True:
            try:
                await asyncio.sleep(check_interval)
                
                if not hasattr(self, 'ws_connections') or not self.ws_connections:
                    continue
                    
                self.logger.debug("Performing WebSocket health check...")
                unhealthy_connections = []
                
                for program_id, ws in list(self.ws_connections.items()):
                    try:
                        if not self._is_connection_open(ws):
                            unhealthy_connections.append(program_id)
                            self.logger.warning(f"Detected unhealthy WebSocket for {program_id[:8]}")
                    except Exception as e:
                        self.logger.warning(f"Error checking health for {program_id[:8]}: {e}")
                        unhealthy_connections.append(program_id)
                        
                # Attempt to recover unhealthy connections
                for program_id in unhealthy_connections:
                    self.logger.info(f"Attempting to recover unhealthy WebSocket for {program_id[:8]}")
                    try:
                        success = await self._enhanced_websocket_reconnection(program_id, max_retries=3)
                        if success:
                            self.logger.info(f"✅ Successfully recovered WebSocket for {program_id[:8]}")
                        else:
                            self.logger.error(f"❌ Failed to recover WebSocket for {program_id[:8]}")
                    except Exception as e:
                        self.logger.error(f"Error during health recovery for {program_id[:8]}: {e}")
                        
                if unhealthy_connections:
                    self.logger.info(f"Health check completed. Recovered {len([p for p in unhealthy_connections if p in self.ws_connections])} connections.")
                else:
                    self.logger.debug(f"All {len(self.ws_connections)} WebSocket connections healthy")
                    
            except Exception as e:
                self.logger.error(f"Error in WebSocket health monitor: {e}", exc_info=True)
                # Continue monitoring despite errors

    # --- NEW: Helper for Fetching Transaction with Fallback & Retry ---
    async def _fetch_transaction_with_fallback(self, signature: str):
        """
        Fetches transaction details using the primary RPC client with backoff retries,
        then falls back to a single attempt on the public RPC if the primary fails.

        Args:
            signature: The transaction signature string.

        Returns:
            The RpcResponse containing transaction details, or None if all attempts fail.
        """
        tx_sig_obj = Signature.from_string(signature)
        primary_client = self.solana_client
        fallback_client = None
        # Define errors that should trigger backoff/retries
        RECOVERABLE_ERRORS = (SolanaRpcException, httpx.HTTPStatusError, httpx.RequestError, asyncio.TimeoutError) # Added TimeoutError

        # Use settings for max_retries, default to 5 if not set
        max_retries = getattr(self.settings, 'API_MAX_RETRIES', 5) 

        @backoff.on_exception(
            backoff.expo,
            RECOVERABLE_ERRORS,
            max_tries=max_retries,
            max_time=60, # Example: Max total time for retries = 60 seconds
            # Use 'giveup' to stop retrying on non-recoverable errors immediately
            giveup=lambda e: not isinstance(e, RECOVERABLE_ERRORS),
            logger=logger, # Use our configured logger
            # --- MODIFIED LOGGING ---
            on_backoff=lambda details: logger.warning(f"Backoff attempt {details['tries']}/{max_retries} for Sig {signature} after {details['wait']:.2f}s. Error: {repr(details['exception'])}"),
            on_giveup=lambda details: logger.error(f"Giving up fetch for Sig {signature} after {details['tries']} attempts due to non-recoverable error: {repr(details['exception'])}")
            # --- END MODIFIED LOGGING ---
        )
        async def _attempt_get_transaction(client, sig, rpc_name):
            # Log which RPC is being attempted
            # Use the internal attribute _provider.endpoint_uri to access the URL
            rpc_url = getattr(client._provider, 'endpoint_uri', 'Unknown RPC URL')
            logger.debug(f"Attempting get_transaction via {rpc_name} RPC ({rpc_url}) for Sig: {sig}")
            # --- ADDED DEBUG LOGGING ---
            logger.debug(f"BEFORE await client.get_transaction for Sig: {sig}")
            # --- END ADDED DEBUG LOGGING ---
            response = await client.get_transaction(
                sig,
                encoding="jsonParsed",
                max_supported_transaction_version=0
            )
            # --- ADDED DEBUG LOGGING ---
            logger.debug(f"AFTER await client.get_transaction for Sig: {sig}. Response received: {response is not None}")
            # --- END ADDED DEBUG LOGGING ---

            logger.debug(f"get_transaction via {rpc_name} successful for Sig: {sig}")
            return response

        tx_response = None
        try:
            # --- Try Primary RPC with Backoff ---
            tx_response = await _attempt_get_transaction(primary_client, tx_sig_obj, "Primary")
            # If successful, return immediately
            # Check for None value *after* successful fetch (if not raised inside decorator)
            # --- ADDED LOGGING ---
            if tx_response:
                logger.warning(f"Primary RPC fetch response (before None check): {tx_response}")
            # --- END ADDED LOGGING ---
            if tx_response and tx_response.value is None:
                logger.warning(f"Primary RPC fetch for Sig {signature} returned None value. Treating as failure.")
                tx_response = None # Set to None to trigger fallback attempt below
            
            if tx_response:
                return tx_response
            
            # If tx_response is None here, it means the fetch succeeded but value was None. Fall through to fallback.
            logger.warning(f"Primary RPC fetch for Sig: {signature} succeeded but returned None value. Attempting fallback...")


        # Catch errors *after* backoff finishes retrying the primary
        except RECOVERABLE_ERRORS as e_primary:
            logger.warning(f"Primary RPC fetch failed after {max_retries} retries for Sig: {signature}. Error: {e_primary}. Attempting fallback...")
            # Fall through to fallback block

        except Exception as e_primary_unexpected:
            # Catch unexpected errors from the primary attempt (after backoff)
            logger.exception(f"Unexpected error during primary RPC fetch (after retries) for Sig {signature}: {e_primary_unexpected}")
            self.circuit_breaker.increment_failures() # Increment on unexpected error
            return None # Give up fetch

        # --- Try Fallback RPC (Single Attempt) ---
        # This block is reached if primary succeeded with None value, OR if primary failed after all retries
        if tx_response is None: # Check again in case it was set to None just above
            try:
                fallback_rpc_url = self.settings.SOLANA_MAINNET_RPC # Get from settings
                if not fallback_rpc_url:
                    logger.error(f"Fallback RPC URL (SOLANA_MAINNET_RPC) not configured. Cannot attempt fallback for Sig: {signature}")
                    self.circuit_breaker.increment_failures() # Increment as we cannot proceed
                    return None
                
                fallback_client = AsyncClient(fallback_rpc_url)
                logger.debug(f"Attempting fallback RPC ({fallback_rpc_url}) for Sig: {signature}")

                # Use the decorated function with max_tries=1 for a single attempt
                # Or call get_transaction directly if backoff isn't needed/desired for fallback
                # Let's call directly for simplicity and to match original logic intent
                tx_response = await fallback_client.get_transaction(
                    tx_sig_obj,
                    encoding="jsonParsed",
                    max_supported_transaction_version=0
                )

                # Check for None value after fallback attempt
                # --- ADDED LOGGING ---
                if tx_response:
                    logger.warning(f"Fallback RPC fetch response (before None check): {tx_response}")
                # --- END ADDED LOGGING ---
                if tx_response and tx_response.value is None:
                    logger.warning(f"Fallback RPC fetch for Sig {signature} returned None value.")
                    tx_response = None # Treat as failure

                if tx_response:
                    logger.info(f"Fallback RPC fetch successful for Sig: {signature}")
                    return tx_response # Return successful fallback response
                else:
                    logger.error(f"Fallback RPC fetch also failed or returned None for Sig: {signature}. Giving up.")
                    self.circuit_breaker.increment_failures() # Increment after fallback failure
                    return None # Give up

            except RECOVERABLE_ERRORS as e_fallback:
                logger.error(f"Fallback RPC fetch failed for Sig: {signature}. Error: {e_fallback}. Giving up.")
                self.circuit_breaker.increment_failures() # Increment after fallback failure
                return None # Give up
            except Exception as e_fallback_unexpected:
                logger.exception(f"Unexpected error during fallback RPC attempt for Sig {signature}: {e_fallback_unexpected}")
                self.circuit_breaker.increment_failures() # Increment on unexpected error
                return None # Give up
            finally:
                if fallback_client:
                    try:
                        await fallback_client.close()
                        logger.debug(f"Closed fallback client for Sig: {signature}")
                    except Exception as close_err:
                        logger.warning(f"Error closing fallback client for Sig {signature}: {close_err}")

        # Failsafe return if logic somehow reaches here without returning
        logger.error(f"Reached end of _fetch_transaction_with_fallback unexpectedly for Sig: {signature}. Returning None.")
        return None
    # --- END Helper --- 

    async def _log_token_price(self, mint: str):
        """Log token price and indicators."""
        try:
            current_time = datetime.now()
            last_log = self.last_price_log.get(mint, 0)
            
            if (current_time - last_log).total_seconds() >= self.price_log_interval:
                price_data = await self.price_monitor.get_token_price(mint)
                if price_data:
                    logger.info(f"Token {mint} - Price: ${price_data['price']:.6f} "
                                 f"24h Volume: ${price_data['volume_24h']:.2f} "
                                 f"Market Cap: ${price_data['market_cap']:.2f}")
                    self.last_price_log[mint] = current_time
                    
        except Exception as e:
            logger.error(f"Error logging token price: {str(e)}")

    def add_token_to_monitor(self, mint: str, pair_address: Optional[str] = None, dex_id: Optional[str] = None):
        """Adds a token to the monitoring list and informs the PriceMonitor."""
        logger.info(f"MarketData.add_token_to_monitor called for mint: {mint}, pair: {pair_address}, dex: {dex_id}")
        self.tokens_to_monitor.add(mint)
        logger.debug(f"Mint {mint} added to MarketData.tokens_to_monitor. Current set: {self.tokens_to_monitor}")
        
        # Ensure token_pair_map and token_dex_map are initialized if not already
        if not hasattr(self, 'token_pair_map'):
            self.token_pair_map: Dict[str, str] = {}
        if not hasattr(self, 'token_dex_map'):
            self.token_dex_map: Dict[str, str] = {}

        if pair_address:
            self.token_pair_map[mint] = pair_address
            logger.debug(f"Pair address {pair_address} mapped to mint {mint}.")
        if dex_id:
            self.token_dex_map[mint] = dex_id
            logger.debug(f"Dex ID {dex_id} mapped to mint {mint}.")

        if self.price_monitor:
            logger.info(f"Calling PriceMonitor.add_token for mint: {mint}")
            self.price_monitor.add_token(mint) # Ensure PriceMonitor also tracks this token
            logger.info(f"Finished calling PriceMonitor.add_token for mint: {mint}")
        else:
            logger.warning(f"PriceMonitor not available in MarketData when trying to add token {mint}")

    # --- NEW: Central method to handle adding a token for all types of monitoring ---
    async def add_token_for_monitoring(self, mint: str, pair_address: Optional[str] = None, dex_id: Optional[str] = None):
        """Central method to add a token for monitoring by PriceMonitor and attempt real-time streaming."""
        logger.info(f"MarketData.add_token_for_monitoring called for mint: {mint}, pair: {pair_address}, dex: {dex_id}")
        
        # Add to PriceMonitor and general MarketData monitoring lists
        self.add_token_to_monitor(mint, pair_address, dex_id)
        
        # Attempt to start real-time streaming for this token
        # This is an async operation, so it's called directly (not in a new task from here,
        # as this method itself is already expected to be called in a task or awaited)
        await self.start_streaming(mint, pair_address, dex_id)
        logger.info(f"Completed add_token_for_monitoring for {mint}. Streaming attempt initiated.")

    async def _handle_blockchain_update(self, update_data: Dict):
        """
        Handles incoming updates from the BlockchainListener.
        Enhanced to process the new blockchain event data with swap log analysis.
        This method is the callback registered with BlockchainListener.
        """
        event_type = update_data.get('type')
        
        # Enhanced logging with swap activity detection
        has_swap_activity = update_data.get('has_swap_activity', False)
        log_count = update_data.get('log_count', 0)
        swap_logs = update_data.get('swap_logs', [])
        
        if has_swap_activity:
            self.logger.debug(f"🔥 SWAP ACTIVITY DETECTED | MarketData processing {log_count} logs with {len(swap_logs)} swap-related entries")
        else:
            self.logger.debug(f"📭 No swap activity | MarketData processing {log_count} logs")

        if event_type == 'log_update':
            logs = update_data.get('logs')
            signature_str = update_data.get('signature')
            # slot = update_data.get('slot') # Slot might not always be present for logs
            
            dex_identifier = update_data.get('dex_id')  # This can be a name like 'pumpswap' or a program_id string
            subscribed_item_address = update_data.get('pool_address') # Address the subscription was made to (pool or program)

            program_id_for_parsing = None
            canonical_dex_name = None  # e.g., 'pumpfun', 'pumpswap', 'raydium_v4'

            if not dex_identifier:
                self.logger.error(f"_handle_blockchain_update (log_update): 'dex_id' is missing from BlockchainListener. Data: {update_data}")
                return

            # 1. Check if dex_identifier is one of the known program IDs directly
            if dex_identifier == self.settings.PUMPFUN_PROGRAM_ID:
                program_id_for_parsing = self.settings.PUMPFUN_PROGRAM_ID
                canonical_dex_name = 'pumpfun'
            elif dex_identifier == self.settings.PUMPSWAP_PROGRAM_ID:
                program_id_for_parsing = self.settings.PUMPSWAP_PROGRAM_ID
                canonical_dex_name = 'pumpswap'
            elif dex_identifier == self.settings.RAYDIUM_V4_PROGRAM_ID:
                program_id_for_parsing = self.settings.RAYDIUM_V4_PROGRAM_ID
                canonical_dex_name = 'raydium_v4'
            elif dex_identifier == self.settings.RAYDIUM_CLMM_PROGRAM_ID:
                program_id_for_parsing = self.settings.RAYDIUM_CLMM_PROGRAM_ID
                canonical_dex_name = 'raydium_clmm'
            else:
                # 2. If not a direct program ID match, treat dex_identifier as a canonical name string
                dex_id_lower = dex_identifier.lower()
                if dex_id_lower == 'pumpfun':
                    program_id_for_parsing = self.settings.PUMPFUN_PROGRAM_ID
                    canonical_dex_name = 'pumpfun'
                elif dex_id_lower == 'pumpswap':
                    program_id_for_parsing = self.settings.PUMPSWAP_PROGRAM_ID
                    canonical_dex_name = 'pumpswap'
                elif dex_id_lower == 'raydium_v4' or dex_id_lower == 'raydium':
                    program_id_for_parsing = self.settings.RAYDIUM_V4_PROGRAM_ID
                    canonical_dex_name = 'raydium_v4'
                elif dex_id_lower == 'raydium_clmm':
                    program_id_for_parsing = self.settings.RAYDIUM_CLMM_PROGRAM_ID
                    canonical_dex_name = 'raydium_clmm'
                # 3. Fallback: Check DEX_PROGRAM_IDS (mapping from other names to program_ids)
                elif dex_identifier in self.settings.DEX_PROGRAM_IDS:
                    program_id_for_parsing = self.settings.DEX_PROGRAM_IDS[dex_identifier]
                    # Attempt to infer canonical_dex_name if the key in DEX_PROGRAM_IDS is standard
                    # This part might need more robust mapping if keys are arbitrary
                    if dex_identifier.lower() in ['pumpfun', 'pumpswap', 'raydium_v4', 'raydium_clmm', 'raydium']:
                        canonical_dex_name = dex_identifier.lower().replace('raydium', 'raydium_v4') # normalize
                    else:
                        canonical_dex_name = dex_identifier # Use the key as is
                    self.logger.info(f"Mapped dex_identifier '{dex_identifier}' to program_id '{program_id_for_parsing}' using DEX_PROGRAM_IDS. Canonical name set to '{canonical_dex_name}'.")

                else:
                    self.logger.warning(f"_handle_blockchain_update (log_update): dex_identifier '{dex_identifier}' is not a recognized program ID, canonical name, or key in DEX_PROGRAM_IDS. Update data: {update_data}")
                    try:
                        Pubkey.from_string(dex_identifier)
                        program_id_for_parsing = dex_identifier # Assume it's the program_id
                        # Attempt to reverse map program_id to canonical_dex_name
                        if program_id_for_parsing == self.settings.PUMPFUN_PROGRAM_ID: canonical_dex_name = 'pumpfun'
                        elif program_id_for_parsing == self.settings.PUMPSWAP_PROGRAM_ID: canonical_dex_name = 'pumpswap'
                        elif program_id_for_parsing == self.settings.RAYDIUM_V4_PROGRAM_ID: canonical_dex_name = 'raydium_v4'
                        elif program_id_for_parsing == self.settings.RAYDIUM_CLMM_PROGRAM_ID: canonical_dex_name = 'raydium_clmm'
                        self.logger.info(f"Treating dex_identifier '{dex_identifier}' as a direct program_id for parsing. Inferred canonical_dex_name: '{canonical_dex_name}'.")
                    except ValueError:
                        self.logger.error(f"_handle_blockchain_update (log_update): dex_identifier '{dex_identifier}' is not a valid Pubkey. Cannot determine program_id. Update data: {update_data}")
                        return

            if not program_id_for_parsing:
                self.logger.error(f"_handle_blockchain_update (log_update): Could not determine program_id_for_parsing. Original dex_identifier='{dex_identifier}'. Data: {update_data}")
                return

            # If canonical_dex_name is still None but program_id_for_parsing is set, try one more reverse map
            if not canonical_dex_name and program_id_for_parsing:
                if program_id_for_parsing == self.settings.PUMPFUN_PROGRAM_ID: canonical_dex_name = 'pumpfun'
                elif program_id_for_parsing == self.settings.PUMPSWAP_PROGRAM_ID: canonical_dex_name = 'pumpswap'
                elif program_id_for_parsing == self.settings.RAYDIUM_V4_PROGRAM_ID: canonical_dex_name = 'raydium_v4'
                elif program_id_for_parsing == self.settings.RAYDIUM_CLMM_PROGRAM_ID: canonical_dex_name = 'raydium_clmm'

            # Enhanced logging for debugging
            if has_swap_activity:
                self.logger.warning(f"🎯 PARSING TARGET | Program: {canonical_dex_name} | Sig: {signature_str[:8]}... | Logs: {log_count} | Swap logs: {len(swap_logs)}")
                
                # 🔍 DEBUG: Log first few raw logs to understand the format
                if logs and len(logs) > 0:
                    blockchain_logger = logging.getLogger('blockchain_listener')
                    blockchain_logger.debug(f"📋 RAW LOGS for {signature_str[:8]}... (first 5 of {len(logs)}):")
                    for i, log in enumerate(logs[:5]):
                        blockchain_logger.debug(f"  [{i}]: {log}")
            else:
                self.logger.debug(f"Parsing target: {canonical_dex_name} for {signature_str[:8]}... with {log_count} logs")

            # --- Parsing Logic based on program_id_for_parsing ---
            if program_id_for_parsing == self.settings.PUMPFUN_PROGRAM_ID:
                parsed_event = self._parse_pumpfun_trade_event(logs, signature_str)
                if parsed_event:
                    self.logger.debug(f"Pump.fun event processed for {subscribed_item_address or 'N/A'}: {parsed_event.get('event_type', 'Unknown Event')}")
                    mint_key_bytes = parsed_event.get('token_mint_key')
                    if mint_key_bytes:
                        try:
                            token_mint_pubkey = Pubkey(mint_key_bytes) # Assuming token_mint_key is bytes
                            token_mint_str = str(token_mint_pubkey)
                            await self._update_realtime_token_state(
                                mint_address=token_mint_str,
                                event_type=parsed_event.get('event_type'),
                                price=parsed_event.get('token_price'),
                                raw_event_data=parsed_event,
                                dex_id='pumpfun', # Use canonical name
                                pair_address=subscribed_item_address # This is the bonding curve address for pump.fun
                            )
                        except Exception as e:
                            self.logger.error(f"Error processing PUMPFUN_PROGRAM_ID event after parsing: {e}. Mint key bytes: {mint_key_bytes}", exc_info=True)
                            
            elif program_id_for_parsing == self.settings.PUMPSWAP_PROGRAM_ID:
                # Parse PumpSwap AMM events using new parser
                parser = self.parsers.get('pumpswap')
                if parser:
                    # ✅ CRITICAL FIX: Pass target_mint to ensure parser filters for relevant tokens
                    target_mint = self._get_target_mint_for_pool(subscribed_item_address)
                    swap_info = parser.parse_swap_logs(logs, signature_str, target_mint=target_mint)
                    self.logger.debug(f"Parser 'pumpswap' returned: {swap_info} (target_mint: {target_mint[:8] if target_mint else 'None'}...)")
                    if swap_info and swap_info.get('found_swap'):
                        self.logger.debug(f"PumpSwap AMM event processed for {subscribed_item_address or 'N/A'}: {swap_info.get('instruction_type', 'Unknown')}")
                        
                        # Extract price from PumpSwap reserves if available
                        virtual_token_reserves = swap_info.get('virtual_token_reserves')
                        virtual_sol_reserves = swap_info.get('virtual_sol_reserves')
                        mint_address = swap_info.get('mint') or swap_info.get('token_mint')
                        
                        if virtual_token_reserves and virtual_sol_reserves and virtual_token_reserves > 0:
                            # Calculate price from reserves (SOL per token) with proper decimal handling
                            # Most PumpSwap tokens use 6 decimals, SOL uses 9 decimals
                            sol_decimals = 9
                            token_decimals = 6  # Default for most meme tokens
                            
                            # Normalize reserves to actual amounts
                            sol_amount = virtual_sol_reserves / (10 ** sol_decimals)
                            token_amount = virtual_token_reserves / (10 ** token_decimals)
                            
                            if token_amount > 0:
                                calculated_price = sol_amount / token_amount
                                
                                # Sanity check: price should be reasonable (0.000001 to 10 SOL)
                                if not (0.000001 <= calculated_price <= 10.0):
                                    # Try different decimal combinations
                                    for test_token_decimals in [6, 9, 4, 8, 3]:
                                        test_token_amount = virtual_token_reserves / (10 ** test_token_decimals)
                                        if test_token_amount > 0:
                                            test_price = sol_amount / test_token_amount
                                            if 0.000001 <= test_price <= 10.0:
                                                calculated_price = test_price
                                                token_decimals = test_token_decimals
                                                break
                            else:
                                calculated_price = virtual_sol_reserves / virtual_token_reserves  # Fallback to raw calculation
                            
                            # Try to get mint address from swap data first
                            if mint_address:
                                await self._update_realtime_token_state(
                                    mint_address=mint_address,
                                    event_type='swap',
                                    price=calculated_price,
                                    raw_event_data=swap_info,
                                    dex_id='pumpswap',
                                    pair_address=subscribed_item_address
                                )
                            else:
                                # Fallback: Find which mint this relates to using token_pair_map
                                token_pair_map = getattr(self, 'token_pair_map', {})
                                for mint, pair_addr in token_pair_map.items():
                                    if pair_addr == subscribed_item_address:
                                        await self._update_realtime_token_state(
                                            mint_address=mint,
                                            event_type='swap',
                                            price=calculated_price,
                                            raw_event_data=swap_info,
                                            dex_id='pumpswap',
                                            pair_address=subscribed_item_address
                                        )
                                        break
                    else:
                        # Check if transaction failed
                        is_failed_tx = any("failed:" in log or "error:" in log.lower() for log in logs) if logs else False
                        if is_failed_tx:
                            self.logger.debug(f"Failed transaction for PUMPSWAP_PROGRAM_ID {signature_str}. Skipping detailed parsing.")
                        else:
                            self.logger.debug(f"No recognizable PumpSwap AMM events found in logs for {subscribed_item_address}")
                else:
                    self.logger.warning("PumpSwap parser not available in MarketData")

            elif program_id_for_parsing == self.settings.RAYDIUM_V4_PROGRAM_ID:
                # Parse Raydium V4 swap events using generic parser
                parser = self.parsers.get('raydium_v4')
                if parser:
                    # ✅ CRITICAL FIX: Pass target_mint to ensure parser filters for relevant tokens
                    target_mint = self._get_target_mint_for_pool(subscribed_item_address)
                    swap_info = parser.parse_swap_logs(logs, signature_str, target_mint=target_mint)
                    if swap_info and swap_info.get('found_swap'):
                        # Generic swap processing - parser handles all DEX-specific logic
                        await self._process_parsed_swap(swap_info, subscribed_item_address, 'raydium_v4')
                    else:
                        self.logger.debug(f"No swap found by raydium_v4 parser for signature {signature_str} (target_mint: {target_mint[:8] if target_mint else 'None'}...)")
                else:
                    self.logger.warning("Raydium V4 parser not available in MarketData")

            elif program_id_for_parsing == self.settings.PUMPSWAP_PROGRAM_ID:
                # Parse PumpSwap AMM events using generic parser
                parser = self.parsers.get('pumpswap')
                if parser:
                    # ✅ CRITICAL FIX: Pass target_mint to ensure parser filters for relevant tokens
                    target_mint = self._get_target_mint_for_pool(subscribed_item_address)
                    swap_info = parser.parse_swap_logs(logs, signature_str, target_mint=target_mint)
                    if swap_info and swap_info.get('found_swap'):
                        # Generic swap processing - parser handles all DEX-specific logic
                        await self._process_parsed_swap(swap_info, subscribed_item_address, 'pumpswap')
                    else:
                        self.logger.debug(f"No swap found by pumpswap parser for signature {signature_str} (target_mint: {target_mint[:8] if target_mint else 'None'}...)")
                else:
                    self.logger.warning("PumpSwap parser not available in MarketData")

            elif program_id_for_parsing == self.settings.RAYDIUM_CLMM_PROGRAM_ID:
                # Parse Raydium CLMM swap events using generic parser
                parser = self.parsers.get('raydium_clmm')
                if parser:
                    # ✅ CRITICAL FIX: Pass target_mint to ensure parser filters for relevant tokens
                    target_mint = self._get_target_mint_for_pool(subscribed_item_address)
                    swap_info = parser.parse_swap_logs(logs, signature_str, target_mint=target_mint)
                    if swap_info and swap_info.get('found_swap'):
                        # Generic swap processing - parser handles all DEX-specific logic
                        await self._process_parsed_swap(swap_info, subscribed_item_address, 'raydium_clmm')
                    else:
                        self.logger.debug(f"No swap found by raydium_clmm parser for signature {signature_str} (target_mint: {target_mint[:8] if target_mint else 'None'}...)")
                else:
                    self.logger.warning("Raydium CLMM parser not available in MarketData")
            else:
                self.logger.warning(f"_handle_blockchain_update: No specific log parser implemented for program_id {program_id_for_parsing} (derived from dex_id: {dex_identifier}). Logs: {logs[:2] if logs else 'No logs'}")

        elif event_type == 'account_update':
            dex_identifier = update_data.get('dex_id') # Can be a name like 'pumpswap' or a program_id
            account_address = update_data.get('pool_address') # This IS the account being updated
            raw_data_list = update_data.get('raw_data') # Should be a list with one b64 string
            # slot = update_data.get('slot')

            self.logger.info(f"_handle_blockchain_update (account_update) for DEX/Program: {dex_identifier}, Account: {account_address}")

            if not dex_identifier or not account_address or not raw_data_list or not isinstance(raw_data_list, list) or not raw_data_list:
                self.logger.error(f"_handle_blockchain_update (account_update): Missing or invalid critical data. Data: {update_data}")
                return

            account_data_b64 = raw_data_list[0]
            program_id_for_parsing = None # This should be the program ID that OWNS the account_address
            canonical_dex_name = None

            # 1. Check if dex_identifier is one of the known program IDs (i.e., it's the owner program ID)
            if dex_identifier == self.settings.PUMPFUN_PROGRAM_ID:
                program_id_for_parsing = self.settings.PUMPFUN_PROGRAM_ID
                canonical_dex_name = 'pumpfun'
            elif dex_identifier == self.settings.PUMPSWAP_PROGRAM_ID:
                program_id_for_parsing = self.settings.PUMPSWAP_PROGRAM_ID
                canonical_dex_name = 'pumpswap'
            elif dex_identifier == self.settings.RAYDIUM_V4_PROGRAM_ID:
                program_id_for_parsing = self.settings.RAYDIUM_V4_PROGRAM_ID
                canonical_dex_name = 'raydium_v4'
            elif dex_identifier == self.settings.RAYDIUM_CLMM_PROGRAM_ID:
                program_id_for_parsing = self.settings.RAYDIUM_CLMM_PROGRAM_ID
                canonical_dex_name = 'raydium_clmm'
            else:
                # 2. If not a direct program ID match, treat dex_identifier as a canonical name for the type of account
                dex_id_lower = dex_identifier.lower()
                if dex_id_lower == 'pumpfun': # Implies account_address is a pump.fun bonding curve
                    program_id_for_parsing = self.settings.PUMPFUN_PROGRAM_ID
                    canonical_dex_name = 'pumpfun'
                elif dex_id_lower == 'pumpswap': # Implies account_address is a pumpswap AMM
                    program_id_for_parsing = self.settings.PUMPSWAP_PROGRAM_ID
                    canonical_dex_name = 'pumpswap'
                elif dex_id_lower == 'raydium_v4' or dex_id_lower == 'raydium':
                    program_id_for_parsing = self.settings.RAYDIUM_V4_PROGRAM_ID
                    canonical_dex_name = 'raydium_v4'
                elif dex_id_lower == 'raydium_clmm':
                    program_id_for_parsing = self.settings.RAYDIUM_CLMM_PROGRAM_ID
                    canonical_dex_name = 'raydium_clmm'
                else:
                    self.logger.warning(f"_handle_blockchain_update (account_update): dex_identifier '{dex_identifier}' for account '{account_address}' is not a recognized program ID or canonical name. Account data parsing will be skipped.")
                    return # Cannot reliably parse without knowing the account type / owner program

            if not program_id_for_parsing:
                 self.logger.error(f"_handle_blockchain_update (account_update): Could not determine program_id for parsing for account '{account_address}'. Original dex_identifier='{dex_identifier}'.")
                 return

            self.logger.info(f"_handle_blockchain_update (account_update): Determined program_id_for_parsing: '{program_id_for_parsing}', canonical_dex_name: '{canonical_dex_name}' for account '{account_address}' from original dex_identifier: '{dex_identifier}'")

            decoded_data = None
            try:
                decoded_data = base64.b64decode(account_data_b64)
            except Exception as e:
                self.logger.error(f"Error decoding base64 account data for {account_address}: {e}", exc_info=True)
                return

            if program_id_for_parsing == self.settings.PUMPFUN_PROGRAM_ID and self._bonding_curve_layout:
                try:
                    parsed_state = self._bonding_curve_layout.parse(decoded_data)
                    token_mint_pubkey = Pubkey(parsed_state.token_mint)
                    token_mint_str = str(token_mint_pubkey)
                    
                    pump_fun_assumed_decimals = await self._fetch_token_decimals(token_mint_str) or 6 # Fetch or default
                    sol_decimals = 9

                    virtual_sol_reserves = parsed_state.virtual_sol_reserves
                    virtual_token_reserves = parsed_state.virtual_token_reserves

                    price = None
                    if virtual_token_reserves > 0 and virtual_sol_reserves > 0 :
                        price = (virtual_sol_reserves / (10**sol_decimals)) / (virtual_token_reserves / (10**pump_fun_assumed_decimals))
                    
                    self.logger.info(f"Pump.fun Account Update for {account_address} (Token: {token_mint_str}): Price ~{price if price else 'N/A'}, V_SOL_Res: {virtual_sol_reserves}, V_Token_Res: {virtual_token_reserves}")
                    
                    await self._update_realtime_token_state(
                        mint_address=token_mint_str,
                        event_type='account_update_pumpfun',
                        price=price,
                        raw_event_data=parsed_state._asdict() if hasattr(parsed_state, '_asdict') else vars(parsed_state),
                        dex_id='pumpfun', # Use canonical name
                        pair_address=account_address, # This is the bonding curve address
                        liquidity_sol = parsed_state.real_sol_reserves / (10**sol_decimals) if hasattr(parsed_state, 'real_sol_reserves') and parsed_state.real_sol_reserves else 0
                    )
                except Exception as e:
                    self.logger.error(f"Error parsing Pump.fun bonding curve account data for {account_address}: {e}", exc_info=True)
            
            elif program_id_for_parsing == self.settings.PUMPSWAP_PROGRAM_ID:
                self.logger.info(f"Received account update for PumpSwap AMM program ({program_id_for_parsing}) account {account_address}. Parsing for specific layout not yet implemented.")
                # TODO: Implement PumpSwap AMM account state parsing if layout (e.g., self._pumpswap_amm_layout) is available.

            elif program_id_for_parsing == self.settings.RAYDIUM_V4_PROGRAM_ID and self._raydium_v4_pool_layout:
                try:
                    parsed_state = self._raydium_v4_pool_layout.parse(decoded_data)
                    # Extract base_mint, quote_mint from parsed_state
                    base_mint_str = str(Pubkey(parsed_state.base_mint))
                    quote_mint_str = str(Pubkey(parsed_state.quote_mint))
                    
                    # Determine target mint (this might need more context, e.g. which token we are tracking for this pool)
                    # For now, let's assume we might update state for both if they are being tracked.
                    # This part requires careful handling of which mint's price we're calculating.
                    # The _fetch_initial_pool_state has more complete logic for this.
                    # Here, we'd update reserves and recalculate price.

                    # Example: Fetch decimals and vault balances (similar to _fetch_initial_pool_state)
                    # This can be simplified if BlockchainListener can provide vault addresses or if state has direct reserves
                    
                    # For now, just log parsed fields
                    self.logger.info(f"Raydium V4 Account Update for {account_address}: BaseMint: {base_mint_str}, QuoteMint: {quote_mint_str}, LP Supply: {parsed_state.lp_supply}")
                    # TODO: Implement full price update logic based on new reserves/state.
                    # Requires fetching decimals and vault balances if not directly in the account state.
                    # This part needs to be robust.
                    # For example, one would need to identify which mint is SOL or USDC to get a USD price.
                    # And then update the relevant token via _update_realtime_token_state
                    
                    # Placeholder: try to get mint_address related to this pool_address from local mapping
                    target_mint_for_update = None
                    for mint, pair_addr in self.token_pair_map.items():
                        if pair_addr == account_address:
                            target_mint_for_update = mint
                            break
                    
                    if target_mint_for_update:
                         # Simplified update: mark that state changed, actual price recalc needs more
                        await self._update_realtime_token_state(
                            mint_address=target_mint_for_update,
                            event_type='account_update_raydium_v4',
                            price=None, # Price calculation from raw pool state is complex here
                            raw_event_data=parsed_state._asdict() if hasattr(parsed_state, '_asdict') else vars(parsed_state),
                            dex_id='raydium_v4',
                            pair_address=account_address
                        )
                    else:
                        self.logger.warning(f"No target mint found in token_pair_map for Raydium V4 pool account update: {account_address}")

                except Exception as e:
                    self.logger.error(f"Error parsing Raydium V4 pool account data for {account_address}: {e}", exc_info=True)

            elif program_id_for_parsing == self.settings.RAYDIUM_CLMM_PROGRAM_ID:
                try:
                    # Basic CLMM account state parsing
                    # For now, just detect that an account update occurred and log it
                    self.logger.info(f"Received account update for Raydium CLMM pool {account_address}. Data size: {len(decoded_data)} bytes")
                    
                    # TODO: Implement proper CLMM pool state layout parsing
                    # This would require defining the proper Borsh layout for CLMM pool accounts
                    # For now, just mark that we received an update
                    
                    # Try to find which mint this pool relates to
                    target_mint_for_update = None
                    for mint, pair_addr in self.token_pair_map.items():
                        if pair_addr == account_address:
                            target_mint_for_update = mint
                            break
                    
                    if target_mint_for_update:
                        await self._update_realtime_token_state(
                            mint_address=target_mint_for_update,
                            event_type='account_update_raydium_clmm',
                            price=None, # Price calculation requires proper layout parsing
                            raw_event_data={"account_data_size": len(decoded_data)},
                            dex_id='raydium_clmm',
                            pair_address=account_address
                        )
                        self.logger.info(f"Marked CLMM account update for token {target_mint_for_update} at pool {account_address}")
                    else:
                        self.logger.debug(f"No target mint found for CLMM pool account update: {account_address}")
                        
                except Exception as e:
                    self.logger.error(f"Error processing Raydium CLMM account data for {account_address}: {e}", exc_info=True)
            else:
                self.logger.warning(f"_handle_blockchain_update (account_update): No specific account parser for program_id '{program_id_for_parsing}' / dex_id '{canonical_dex_name}' for account {account_address}.")

        elif event_type == 'blockchain_event':
            # Handle general blockchain events (log notifications)
            logs = update_data.get('logs', [])
            signature = update_data.get('signature', 'unknown')
            program_id = update_data.get('program_id')
            has_swap_activity = update_data.get('has_swap_activity', False)
            
            if has_swap_activity and logs:
                self.logger.debug(f"🔥 Processing blockchain event with swap activity: {signature[:8]}... from program {program_id[:8]}...")
                
                # Convert to log_update format for existing processing pipeline
                converted_update = {
                    'type': 'log_update',
                    'logs': logs,
                    'signature': signature,
                    'dex_id': program_id,  # Use program_id as dex_id for routing
                    'pool_address': None   # General event doesn't have specific pool
                }
                
                # Process through existing log_update pipeline
                await self._handle_blockchain_update(converted_update)
            else:
                self.logger.debug(f"📝 Blockchain event without swap activity: {signature[:8]}... from {program_id[:8]}...")

        else:
            self.logger.warning(f"_handle_blockchain_update: Unknown event type '{event_type}'. Data: {update_data}")

    async def monitor_token(self, mint: str, symbol: str = None, dex_id: str = 'raydium_v4', pool_address: str = None, priority: str = None):
        """
        Start monitoring a specific token for price and volume updates with appropriate priority
        
        Args:
            mint: The token's mint address on Solana
            symbol: The token's symbol (optional, for display purposes)
            dex_id: The DEX where this token is traded (default: raydium_v4)
            pool_address: If known, the pool/AMM address to monitor directly.
                          If not provided, will attempt to find it.
            priority: Priority level - 'high', 'medium', or 'low'
                      If None, will be determined automatically based on token status
        """
        # Determine priority if not specified
        if priority is None:
            priority = await self._determine_token_priority(mint)
            
        if priority not in ['high', 'medium', 'low']:
            self.logger.warning(f"Invalid priority level '{priority}' for token {mint}. Using 'low' as default.")
            priority = 'low'
            
        self.logger.info(f"Starting to monitor token {mint} ({symbol or 'Unknown'}) with {priority} priority")
        
        if not self.blockchain_listener:
            self.logger.error("Cannot monitor token: blockchain listener not initialized")
            # Fall back to price monitor for all tokens if blockchain listener not available
            await self._setup_price_monitor_for_token(mint, symbol, pool_address)
            return False
            
        # Check if already monitoring this token
        if mint in self._monitored_tokens:
            existing_priority = self._monitored_tokens[mint].get('priority', 'low')
            self.logger.info(f"Already monitoring token: {mint} ({symbol or 'Unknown'}) with {existing_priority} priority")
            
            # If requested priority is higher than current, upgrade monitoring
            if (priority == 'high' and existing_priority != 'high') or (priority == 'medium' and existing_priority == 'low'):
                self.logger.info(f"Upgrading monitoring for {mint} from {existing_priority} to {priority} priority")
                # Remove from current monitoring approach
                await self._remove_token_from_current_monitoring(mint)
                # Continue to set up the new monitoring approach
            else:
                return True
            
        # If we don't have a pool_address, try to find it
        if not pool_address:
            self.logger.info(f"Looking up pool address for token: {mint}")
            # In a real implementation, query for pool address
            # For now, mark as missing; could be implemented later
            self.logger.warning(f"No pool address provided for token {mint}, cannot monitor")
            # Still try using the price monitor for low-tier monitoring
            await self._setup_price_monitor_for_token(mint, symbol, None)
            return False
            
        # Store the token info
        self._monitored_tokens[mint] = {
            'address': mint,
            'symbol': symbol or mint[:8],
            'pool_address': pool_address,
            'dex_id': dex_id,
            'monitoring_started': int(time.time()),
            'last_price': None,
            'last_price_updated': None,
            'hourly_volume': 0,
            'priority': priority  # Store the priority level
        }
        
        # Choose monitoring approach based on priority
        if priority == 'high':
            # HIGH PRIORITY: Direct account subscribe for immediate updates
            return await self._setup_direct_account_monitoring(mint, pool_address, dex_id)
        elif priority == 'medium':
            # MEDIUM PRIORITY: Use webhooks for efficient event notifications
            return await self._setup_webhook_monitoring(mint, pool_address, dex_id)
        else:
            # LOW PRIORITY: Use price monitor polling
            return await self._setup_price_monitor_for_token(mint, symbol, pool_address)

    async def _determine_token_priority(self, mint: str) -> str:
        """
        Determine the appropriate monitoring priority for a token based on its status
        
        Args:
            mint: The token's mint address
            
        Returns:
            str: Priority level ('high', 'medium', or 'low')
        """
        # Check if this token is actively traded (in positions)
        is_in_active_position = await self._check_if_in_active_position(mint)
        if is_in_active_position:
            self.logger.info(f"Token {mint} is in active position - using HIGH priority monitoring")
            return 'high'
            
        # Check if token is in watchlist (potential trade)
        is_in_watchlist = await self._check_if_in_watchlist(mint)
        if is_in_watchlist:
            self.logger.info(f"Token {mint} is in watchlist - using MEDIUM priority monitoring")
            return 'medium'
            
        # Default for other tokens
        self.logger.info(f"Token {mint} is not in active position or watchlist - using LOW priority monitoring")
        return 'low'
        
    async def _check_if_in_active_position(self, mint: str) -> bool:
        """
        Check if a token is in an active trading position
        
        Args:
            mint: The token's mint address
            
        Returns:
            bool: True if in active position
        """
        # In a real implementation, you would:
        # 1. Check with OrderManager if token is in any active position
        # 2. Check if token is being actively traded
        
        try:
            # Check if we have an order manager reference
            if hasattr(self, 'order_manager') and self.order_manager:
                # Get active positions from order manager
                active_positions = await self.order_manager.get_active_positions()
                if active_positions and mint in [p.get('mint') for p in active_positions]:
                    return True
                    
            # Alternative check if we have local active positions tracking
            if hasattr(self, 'active_positions') and self.active_positions:
                if mint in self.active_positions:
                    return True
                    
            return False
        except Exception as e:
            self.logger.error(f"Error checking if token {mint} is in active position: {e}")
            return False  # Default to false on error
            
    async def _check_if_in_watchlist(self, mint: str) -> bool:
        """
        Check if a token is in the watchlist for potential trading
        
        Args:
            mint: The token's mint address
            
        Returns:
            bool: True if in watchlist
        """
        # In a real implementation, you would:
        # 1. Check with scanner results if token is being monitored
        # 2. Check if token is flagged for potential entry
        
        try:
            if hasattr(self, 'watchlist') and self.watchlist:
                if mint in self.watchlist:
                    return True
                    
            # Check if token was recently scanned
            if hasattr(self, 'scanner_results') and self.scanner_results:
                for result in self.scanner_results:
                    if result.get('mint') == mint:
                        return True
                        
            return False
        except Exception as e:
            self.logger.error(f"Error checking if token {mint} is in watchlist: {e}")
            return False  # Default to false on error
            
    async def get_active_monitored_tokens(self) -> List[str]:
        """Returns a list of mints currently being monitored."""
        return list(self._monitored_tokens.keys())

    async def _setup_direct_account_monitoring(self, mint: str, pool_address: str, dex_id: str):
        """
        Set up direct account subscription monitoring for high-priority tokens (active trading)
        
        Args:
            mint: The token's mint address
            pool_address: The pool/AMM address
            dex_id: The DEX identifier
            
        Returns:
            bool: Success status
        """
        self.logger.info(f"Setting up HIGH PRIORITY direct account monitoring for {mint} on pool {pool_address}")
        
        # Try to subscribe to the pool account directly
        account_sub_success = await self.blockchain_listener.subscribe_to_pool_account(
            pool_address=pool_address, 
            dex_id=dex_id
        )
        
        if account_sub_success:
            self.logger.info(f"Successfully set up direct account monitoring for {mint}")
            self._monitored_tokens[mint]['monitoring_method'] = 'direct_account'
            return True
        else:
            self.logger.warning(f"Failed to set up direct account monitoring for {mint}, falling back to logs")
            
            # Try logs subscription as fallback for high priority tokens
            logs_sub_success = await self.blockchain_listener.subscribe_to_pool_logs(
                pool_address=pool_address, 
                dex_id=dex_id
            )
            
            if logs_sub_success:
                self.logger.info(f"Successfully set up logs monitoring as fallback for {mint}")
                self._monitored_tokens[mint]['monitoring_method'] = 'logs_fallback'
                return True
            else:
                self.logger.error(f"Failed to set up both direct account and logs monitoring for {mint}")
                # Record fallback to PriceMonitor
                self.record_price_monitor_fallback(mint=mint, reason="high_priority_fallback")
                
                # Fall back to price monitor
                await self._setup_price_monitor_for_token(mint, 
                                                        self._monitored_tokens[mint].get('symbol'), 
                                                        pool_address)
                return False
    
    async def _setup_webhook_monitoring(self, mint: str, pool_address: str, dex_id: str):
        """
        Set up webhook monitoring for medium-priority tokens (monitoring for potential trading)
        
        Args:
            mint: The token's mint address
            pool_address: The pool/AMM address
            dex_id: The DEX identifier
            
        Returns:
            bool: Success status
        """
        if not hasattr(self, 'settings') or not hasattr(self.settings, 'API_BASE_URL'):
            self.logger.error("Cannot set up webhook monitoring: API_BASE_URL not configured")
            # Fall back to price monitor
            await self._setup_price_monitor_for_token(mint, 
                                                    self._monitored_tokens[mint].get('symbol'), 
                                                    pool_address)
            return False
            
        self.logger.info(f"Setting up MEDIUM PRIORITY webhook monitoring for {mint} on pool {pool_address}")
        
        try:
            # Set up webhook using Helius API
            webhook_url = f"{self.settings.API_BASE_URL}/token-updates"
            
            # Prepare payload for Helius webhook API
            webhook_payload = {
                "webhookURL": webhook_url,
                "accountAddresses": [pool_address],
                "type": "raw",  # Raw account data for direct pool monitoring
                "webhookType": "raw",
                "authHeader": self.settings.WEBHOOK_AUTH_HEADER if hasattr(self.settings, 'WEBHOOK_AUTH_HEADER') else None
            }
            
            # Placeholder for actual implementation
            # In a real implementation, you would:
            # 1. Call Helius API to register webhook
            # 2. Store webhook ID for management
            
            self.logger.info(f"Would set up webhook with payload: {webhook_payload}")
            self.logger.warning("Webhook implementation is a placeholder - falling back to PriceMonitor")
            
            # Since this is a placeholder, fall back to price monitor
            self._monitored_tokens[mint]['monitoring_method'] = 'price_monitor_fallback'
            self.record_price_monitor_fallback(mint=mint, reason="webhook_not_implemented")
            
            # Actually set up price monitor
            await self._setup_price_monitor_for_token(mint, 
                                                   self._monitored_tokens[mint].get('symbol'), 
                                                   pool_address)
            
            return False  # Return false since webhook isn't actually implemented
            
        except Exception as e:
            self.logger.error(f"Error setting up webhook for {mint}: {e}")
            # Fall back to price monitor
            self.record_price_monitor_fallback(mint=mint, reason="webhook_error")
            await self._setup_price_monitor_for_token(mint, 
                                                   self._monitored_tokens[mint].get('symbol'), 
                                                   pool_address)
            return False
    
    async def _setup_price_monitor_for_token(self, mint: str, symbol: str = None, pool_address: str = None):
        """
        Set up price monitor polling for low-priority tokens
        
        Args:
            mint: The token's mint address
            symbol: The token's symbol
            pool_address: The pool/AMM address (optional)
            
        Returns:
            bool: Success status
        """
        if mint not in self._monitored_tokens:
            # Initialize token info if not already present
            self._monitored_tokens[mint] = {
                'address': mint,
                'symbol': symbol or mint[:8],
                'pool_address': pool_address,
                'monitoring_started': int(time.time()),
                'last_price': None,
                'last_price_updated': None,
                'hourly_volume': 0,
                'priority': 'low',  # Always low priority for price monitor
                'monitoring_method': 'price_monitor'
            }
        else:
            # Update existing record
            self._monitored_tokens[mint]['monitoring_method'] = 'price_monitor'
            
        self.logger.info(f"Setting up LOW PRIORITY price monitor polling for {mint}")
        
        # Register with price monitor for polling updates
        if hasattr(self, 'price_monitor') and self.price_monitor:
            try:
                # Just pass the mint to add_token since it only accepts one parameter
                self.price_monitor.add_token(mint)
                self.logger.info(f"Added {mint} to price monitor polling")
                return True
            except Exception as e:
                self.logger.error(f"Error adding token to price monitor: {e}")
                return False
        else:
            self.logger.error("Cannot set up price monitor: price_monitor not initialized")
            return False
            
    async def _remove_token_from_current_monitoring(self, mint: str):
        """
        Remove a token from its current monitoring approach to prepare for a different approach
        
        Args:
            mint: The token's mint address
        """
        if mint not in self._monitored_tokens:
            return
            
        monitoring_method = self._monitored_tokens[mint].get('monitoring_method')
        pool_address = self._monitored_tokens[mint].get('pool_address')
        dex_id = self._monitored_tokens[mint].get('dex_id')
        
        if monitoring_method == 'direct_account' and pool_address and self.blockchain_listener:
            # Unsubscribe from direct account monitoring
            await self.blockchain_listener.unsubscribe_from_pool_data(pool_address)
            self.logger.info(f"Removed {mint} from direct account monitoring")
            
        elif monitoring_method == 'logs_fallback' and pool_address and dex_id and self.blockchain_listener:
            # Unsubscribe from logs monitoring
            await self.blockchain_listener.unsubscribe_from_pool_logs(pool_address, dex_id)
            self.logger.info(f"Removed {mint} from logs monitoring")
            
        elif monitoring_method == 'price_monitor' and hasattr(self, 'price_monitor') and self.price_monitor:
            # Remove from price monitor polling
            self.price_monitor.remove_token(mint)
            self.logger.info(f"Removed {mint} from price monitor polling")
            
        # No specific action needed for webhook monitoring currently

    async def get_blockchain_listener_metrics(self) -> Dict[str, Any]:
        """
        Get metrics from the blockchain listener about connection and subscription success rates
        and fallbacks to PriceMonitor.
        
        Returns:
            Dict: Current metrics for RPC endpoint reliability and fallbacks
        """
        if not self.blockchain_listener:
            return {
                "error": "Blockchain listener not initialized",
                "timestamp": time.time()
            }
            
        # Get metrics from blockchain listener if it has the method
        if hasattr(self.blockchain_listener, "get_metrics"):
            metrics = self.blockchain_listener.get_metrics()
            
            # Add summary metrics
            primary_metrics = metrics["primary"]
            fallback_metrics = metrics["fallback"]
            
            # Calculate overall success rates
            primary_conn_rate = primary_metrics.get("connection_success_rate", 0)
            fallback_conn_rate = fallback_metrics.get("connection_success_rate", 0)
            
            primary_sub_rate = primary_metrics.get("subscription_success_rate", 0)
            fallback_sub_rate = fallback_metrics.get("subscription_success_rate", 0)
            
            # Add price monitor fallbacks (comes from our tracking)
            metrics["price_monitor_fallbacks"] = getattr(self, "_price_monitor_fallback_count", 0)
            
            # Create summary stats
            metrics["summary"] = {
                "primary_overall_success_rate": (primary_conn_rate + primary_sub_rate) / 2,
                "fallback_overall_success_rate": (fallback_conn_rate + fallback_sub_rate) / 2,
                "any_blockchain_success_rate": max(
                    (primary_conn_rate + primary_sub_rate) / 2,
                    (fallback_conn_rate + fallback_sub_rate) / 2
                ),
                "description": "Reliability metrics for blockchain event monitoring"
            }
            
            return metrics
        else:
            # Simplified metrics if get_metrics not available
            return {
                "primary": {
                    "is_active": getattr(self.blockchain_listener, "_endpoint_status", {}).get("primary", {}).get("is_active", False),
                    "url": self._mask_endpoint_url(getattr(self.blockchain_listener, "primary_websocket_url", "unknown")),
                },
                "fallback": {
                    "is_active": getattr(self.blockchain_listener, "_endpoint_status", {}).get("fallback", {}).get("is_active", False),
                    "url": self._mask_endpoint_url(getattr(self.blockchain_listener, "fallback_websocket_url", "unknown")),
                },
                "price_monitor_fallbacks": getattr(self, "_price_monitor_fallback_count", 0),
                "timestamp": time.time()
            }
            
    def _mask_endpoint_url(self, url: str) -> str:
        """Mask API keys in endpoint URLs"""
        if not url or not isinstance(url, str):
            return "unknown"
            
        try:
            from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            if 'api-key' in query_params:
                query_params['api-key'] = ['***'] # Mask the key

            new_query = urlencode(query_params, doseq=True)
            # Reconstruct the URL
            masked_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
            return masked_url
        except Exception as e:
            self.logger.warning(f"Failed to mask URL: {e}")
            # Return with generic masking as fallback
            return url.replace("api-key=", "api-key=***")
            
    def record_price_monitor_fallback(self, mint: str = None, reason: str = None):
        """
        Record that we had to fall back to PriceMonitor for a token price update
        
        Args:
            mint: Optional token mint address that needed fallback
            reason: Optional reason for the fallback
        """
        # Initialize counter if it doesn't exist
        if not hasattr(self, "_price_monitor_fallback_count"):
            self._price_monitor_fallback_count = 0
            
        # Initialize tracking dictionary if it doesn't exist
        if not hasattr(self, "_price_monitor_fallbacks"):
            self._price_monitor_fallbacks = {}
            
        # Increment counter
        self._price_monitor_fallback_count += 1
        
        # Record specific instance with timestamp
        timestamp = int(time.time())
        fallback_id = f"fallback_{timestamp}_{random.randint(1000, 9999)}"
        
        self._price_monitor_fallbacks[fallback_id] = {
            "mint": mint,
            "reason": reason,
            "timestamp": timestamp
        }
        
        # Log the fallback
        token_info = f"for token {mint}" if mint else ""
        reason_info = f"due to {reason}" if reason else ""
        self.logger.info(f"Falling back to PriceMonitor {token_info} {reason_info} (total fallbacks: {self._price_monitor_fallback_count})")
        
        # Update blockchain listener metrics if possible
        if (self.blockchain_listener and hasattr(self.blockchain_listener, "metrics") and "price_monitor_fallbacks" in self.blockchain_listener.metrics): 
            self.blockchain_listener.metrics["price_monitor_fallbacks"] = self._price_monitor_fallback_count
        
        # Prune old entries (keep last 100)
        if len(self._price_monitor_fallbacks) > 100:
            oldest_keys = sorted(self._price_monitor_fallbacks.keys(), 
                               key=lambda k: self._price_monitor_fallbacks[k]["timestamp"])[:len(self._price_monitor_fallbacks) - 100]
            for key in oldest_keys:
                self._price_monitor_fallbacks.pop(key, None)
    
    def _get_target_mint_for_pool(self, pool_address: str) -> Optional[str]:
        """
        Get the target token mint for a given pool address.
        This is essential for parser filtering to only process relevant swaps.
        
        Args:
            pool_address: The pool/pair address being monitored
            
        Returns:
            str: Token mint address if known, None otherwise
        """
        if not pool_address:
            return None
            
        # Check the monitored tokens mapping
        if hasattr(self, '_monitored_tokens'):
            for mint, token_info in self._monitored_tokens.items():
                if token_info.get('pool_address') == pool_address or token_info.get('pair_address') == pool_address:
                    return mint
        
        # Check the token_pair_map if it exists
        if hasattr(self, 'token_pair_map'):
            for mint, pair_addr in self.token_pair_map.items():
                if pair_addr == pool_address:
                    return mint
        
        # Fallback: Check if we have any stored pool mappings
        # This could be enhanced to query the database or other sources
        well_known_pools = {
            "8BnEgHoWFysVcuFFX7QztDmzuH8r5ZFvyP3sYwn1XTh6": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
            "GHtwNAYk8UyABF7gUTLWQmdu5SfHs9vE4SpTkZnPqUAV": "7ZYyESa8TkuoBVFi5seeLPr7B3MeLvyPgEgv5MDTpump",  # Saphi
        }
        
        target_mint = well_known_pools.get(pool_address)
        if target_mint:
            return target_mint
        
        # Log that we couldn't find the mapping
        if self.logger:
            self.logger.debug(f"🔍 No target mint mapping found for pool {pool_address[:8]}...")
        
        return None

    async def _update_realtime_token_state(self, mint_address: str, event_type: str, price: Optional[float] = None, 
                                         raw_event_data: Optional[Dict] = None, dex_id: Optional[str] = None,
                                         pair_address: Optional[str] = None, liquidity_sol: Optional[float] = None):
        """
        Update real-time token state with enhanced price handling - SOL primary, USD secondary.
        """
        # Filter out insignificant events early
        if not self._is_event_significant(event_type, price, raw_event_data):
            self.logger.debug(f"Filtered out insignificant {event_type} event for {mint_address[:8]}...")
            return
        
        # Store SOL price as primary (no conversion)
        price_sol = price  # Keep original SOL price from parser
        price_usd = None   # Calculate USD as secondary
        
        # Convert to USD only for display/logging purposes
        if price_sol and price_sol > 0:
            price_usd = await self._convert_sol_price_to_usd(price_sol, dex_id)
        
        # Initialize state if not exists
        if not hasattr(self, '_realtime_token_state'):
            self._realtime_token_state = {}
            
        current_state = self._realtime_token_state.get(mint_address, {
            'last_price_sol': None,
            'last_price_usd': None,
            'last_update': None,
            'event_count': 0,
            'dex_id': dex_id,
            'pair_address': pair_address
        })
        
        # Update state with SOL price as primary
        if price_sol:
            current_state.update({
                'last_price_sol': price_sol,
                'last_price_usd': price_usd,
                'last_update': time.time(),
                'event_count': current_state.get('event_count', 0) + 1,
                'dex_id': dex_id,
                'pair_address': pair_address,
                'liquidity_sol': liquidity_sol
            })
            
            self._realtime_token_state[mint_address] = current_state
            
            # Log with SOL as primary and USD as secondary
            sol_price_str = f"{price_sol:.8f} SOL" if price_sol is not None else "None SOL"
            usd_price_str = f"(${price_usd:.6f})" if price_usd else "(USD unknown)"
            
            self.logger.debug(f"💰 BLOCKCHAIN PRICE: {mint_address[:8]}... = {sol_price_str} {usd_price_str} | Source: {dex_id.upper()}")
            
            # Store in database with SOL price as primary
            if self.db and hasattr(self.db, 'update_token_price'):
                try:
                    await self.db.update_token_price(
                        mint=mint_address,
                        price=price_sol  # Use correct parameter name
                    )
                except Exception as e:
                    self.logger.error(f"Error updating token price in database: {e}")
            elif self.db:
                self.logger.warning(f"Database object exists but missing update_token_price method: {type(self.db)}")
        
        self.logger.debug(f"Updated real-time state for {mint_address[:8]}: {event_type} at {price_sol:.8f} SOL (events: {current_state['event_count']})" if price_sol is not None else f"Updated real-time state for {mint_address[:8]}: {event_type} at None SOL (events: {current_state['event_count']})")

    async def _convert_sol_price_to_usd(self, price_sol: float, dex_id: Optional[str] = None) -> Optional[float]:
        """
        Convert SOL price to USD for secondary display only.
        
        Args:
            price_sol: Price in SOL (primary)
            dex_id: DEX identifier for context
            
        Returns:
            USD price or None if conversion fails
        """
        try:
            # Sanity check on SOL price first
            if not (0.000000001 <= price_sol <= 1000.0):  # Reasonable SOL price range
                self.logger.warning(f"SOL price {price_sol:.8f} outside reasonable range, skipping USD conversion")
                return None
                
            # Get current SOL price in USD
            sol_price_usd = await self._get_sol_price_usd()
            if sol_price_usd and sol_price_usd > 0:
                price_usd = price_sol * sol_price_usd
                
                # Final sanity check on USD price
                if 0.0000001 <= price_usd <= 100000.0:  # Reasonable USD range for crypto
                    if self.logger and price_sol is not None and price_usd is not None and sol_price_usd is not None:
                        self.logger.debug(f"Converted {dex_id or 'unknown'}: {price_sol:.8f} SOL → ${price_usd:.6f} USD (SOL=${sol_price_usd:.2f})")
                    return price_usd
                else:
                    self.logger.warning(f"USD conversion result ${price_usd:.6f} outside reasonable range, discarding")
                    return None
            else:
                self.logger.debug(f"Could not get SOL price for USD conversion")
                return None
                
        except Exception as e:
            self.logger.error(f"Error converting SOL price to USD: {e}")
            return None

    async def get_token_price_sol(self, mint: str, max_age_seconds: Optional[int] = None) -> Optional[float]:
        """
        Get token price in SOL - PRIMARY METHOD FOR SOL-BASED TRADING.
        
        Args:
            mint: Token mint address
            max_age_seconds: Maximum age of cached data in seconds
            
        Returns:
            Optional[float]: Token price in SOL, or None if not available
        """
        try:
            if hasattr(self, 'price_monitor') and self.price_monitor:
                price_sol = await self.price_monitor.get_current_price_sol(mint, max_age_seconds)
                if price_sol and price_sol > 0:
                    self.logger.debug(f"Got SOL price for {mint[:8]}...: {price_sol:.8f} SOL")
                    return price_sol
                    
            self.logger.warning(f"Could not get SOL price for {mint[:8]}... from PriceMonitor")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting SOL price for {mint}: {e}")
            return None

    async def get_token_price_usd(self, mint: str, max_age_seconds: Optional[int] = None) -> Optional[float]:
        """
        Get token price in USD - FOR DISPLAY PURPOSES ONLY.
        
        Args:
            mint: Token mint address
            max_age_seconds: Maximum age of cached data in seconds
            
        Returns:
            Optional[float]: Token price in USD, or None if not available
        """
        try:
            if hasattr(self, 'price_monitor') and self.price_monitor:
                price_usd = await self.price_monitor.get_current_price_usd(mint, max_age_seconds)
                if price_usd and price_usd > 0:
                    self.logger.debug(f"Got USD price for {mint[:8]}...: ${price_usd:.6f}")
                    return price_usd
                    
            self.logger.warning(f"Could not get USD price for {mint[:8]}... from PriceMonitor")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting USD price for {mint}: {e}")
            return None

    async def _get_sol_price_usd(self) -> Optional[float]:
        """Get current SOL price in USD using PriceMonitor."""
        try:
            if hasattr(self, 'price_monitor') and self.price_monitor:
                sol_price = await self.price_monitor.get_sol_price()
                if sol_price and sol_price > 0:
                    return sol_price
                    
            # Fallback: try via token price lookup
            sol_mint = "So11111111111111111111111111111111111111112"
            if hasattr(self, 'price_monitor') and self.price_monitor:
                sol_price = await self.price_monitor.get_current_price_usd(sol_mint, max_age_seconds=300)
                if sol_price and sol_price > 0:
                    return sol_price
                    
            # Final fallback: approximate price
            self.logger.warning("Could not get SOL price from PriceMonitor, using fallback")
            return 150.0  # Approximate fallback
            
        except Exception as e:
            self.logger.error(f"Error getting SOL price: {e}")
            return 150.0  # Fallback price

    async def _fetch_token_decimals(self, mint_address: str) -> Optional[int]:
        """
        Fetch actual token decimals from Helius API.
        
        Args:
            mint_address: Token mint address
            
        Returns:
            int: Token decimals or None if fetch fails
        """
        # **ADDED: Confirm method is being called**
        self.logger.info(f"🎯 Fetching decimals for token {mint_address[:8]}...")
        
        try:
            # Check if we have cached decimals first
            if hasattr(self, '_decimal_cache'):
                if mint_address in self._decimal_cache:
                    cached_value = self._decimal_cache[mint_address]
                    self.logger.info(f"💾 Using cached decimals for {mint_address[:8]}...: {cached_value}")
                    return cached_value
            else:
                self._decimal_cache = {}
            
            # Try to get from Helius using getAccountInfo
            if hasattr(self, 'http_client') and self.http_client:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getAccountInfo",
                    "params": [
                        mint_address,
                        {
                            "encoding": "jsonParsed"
                        }
                    ]
                }
                
                # Use Helius RPC URL from settings
                rpc_url = getattr(self.settings, 'SOLANA_RPC_URL', 'https://mainnet.helius-rpc.com')
                if not rpc_url.startswith('http'):
                    rpc_url = f"https://{rpc_url}"
                
                self.logger.info(f"🌐 Making Helius API call for {mint_address[:8]}... to {rpc_url[:30]}...")
                response = await self.http_client.post(rpc_url, json=payload, timeout=10.0)
                response.raise_for_status()
                
                data = response.json()
                
                if "result" in data and data["result"] and "value" in data["result"]:
                    account_info = data["result"]["value"]
                    if account_info and "data" in account_info:
                        parsed_data = account_info["data"]
                        if "parsed" in parsed_data and "info" in parsed_data["parsed"]:
                            decimals = parsed_data["parsed"]["info"].get("decimals")
                            if decimals is not None:
                                self._decimal_cache[mint_address] = decimals
                                self.logger.info(f"✅ HELIUS SUCCESS: {mint_address[:8]}... has {decimals} decimals")
                                return decimals
                
                # If we couldn't parse, log and fall back
                self.logger.warning(f"❌ Could not parse token decimals from Helius response for {mint_address[:8]}...")
                    
        except Exception as e:
            self.logger.warning(f"❌ Error fetching decimals from Helius for {mint_address[:8]}...: {e}")
        
        # Fallback to common values based on token patterns
        fallback_decimals = 6  # Most meme tokens use 6 decimals
        
        # Store fallback in cache to avoid repeated API calls
        if hasattr(self, '_decimal_cache'):
            self._decimal_cache[mint_address] = fallback_decimals
        
        self.logger.info(f"📊 Using fallback decimals for {mint_address[:8]}...: {fallback_decimals}")
        return fallback_decimals

    def _is_event_significant(self, event_type: str, price: Optional[float], raw_event_data: Optional[Dict]) -> bool:
        """
        Filter events by significance to reduce processing overhead.
        """
        # Always allow price updates
        if event_type in ['price_update', 'trade'] and price:
            return True
            
        # Check minimum transaction value
        if raw_event_data:
            # Extract amount values for significance check
            amount_values = []
            
            if isinstance(raw_event_data, dict):
                # Check for swap amounts
                for key in ['amount_in', 'amount_out', 'usdc_amount', 'token_amount']:
                    if key in raw_event_data and raw_event_data[key]:
                        try:
                            amount_values.append(float(raw_event_data[key]))
                        except (ValueError, TypeError):
                            continue
                            
                # Check parsing confidence for CLMM/V4 events
                confidence = raw_event_data.get('parsing_confidence', 1.0)
                if confidence < 0.3:  # Low confidence events are less significant
                    return False
                    
            # Filter by minimum transaction value (equivalent to ~$1 USD)
            if amount_values:
                max_amount = max(amount_values)
                if max_amount < 1000000:  # Less than 1M tokens/smallest units (rough $1 threshold)
                    return False
                    
        # Allow all other event types by default
        return True

    async def _queue_for_batch_processing(self, event_data: Dict):
        """
        Queue events for efficient batch processing.
        """
        if not hasattr(self, '_batch_queue'):
            self._batch_queue = []
            self._last_batch_process = time.time()
            
        self._batch_queue.append(event_data)
        
        # Process batch if queue is full or time threshold reached
        batch_size_threshold = 50
        batch_time_threshold = 5.0  # seconds
        
        should_process = (
            len(self._batch_queue) >= batch_size_threshold or
            (time.time() - self._last_batch_process) >= batch_time_threshold
        )
        
        if should_process:
            await self._process_batch_events()

    async def _process_batch_events(self):
        """
        Process queued events in batch for optimal database performance.
        """
        if not hasattr(self, '_batch_queue') or not self._batch_queue:
            return
            
        batch = self._batch_queue.copy()
        self._batch_queue.clear()
        self._last_batch_process = time.time()
        
        self.logger.debug(f"Processing batch of {len(batch)} events")
        
        try:
            # Group events by type for optimized processing
            price_updates = []
            volume_updates = []
            liquidity_updates = []
            
            for event in batch:
                event_type = event.get('event_type')
                mint_address = event.get('mint_address')
                
                if event_type in ['trade', 'swap'] and event.get('price'):
                    price_updates.append({
                        'mint': mint_address,
                        'price': event['price'],
                        'source': f"realtime_{event.get('dex_id', 'unknown')}",
                        'timestamp': event.get('timestamp', time.time())
                    })
                    
                    # Also track volume if we have amount data
                    if event.get('raw_event_data', {}).get('amount_in'):
                        try:
                            volume_increment = float(event['raw_event_data']['amount_in']) / 1e6  # Rough conversion
                            volume_updates.append({
                                'mint': mint_address,
                                'volume_increment': volume_increment,
                                'timestamp': event.get('timestamp', time.time())
                            })
                        except (ValueError, TypeError):
                            pass
                            
                if event_type == 'liquidity_change' and event.get('liquidity_sol'):
                    liquidity_updates.append({
                        'mint': mint_address,
                        'liquidity': event['liquidity_sol'],
                        'timestamp': event.get('timestamp', time.time())
                    })
            
            # Batch update database
            await self._batch_update_database(price_updates, volume_updates, liquidity_updates)
            
            # Update analytics
            await self._update_batch_analytics(batch)
            
            self.logger.info(f"✅ Processed batch: {len(price_updates)} prices, {len(volume_updates)} volumes, {len(liquidity_updates)} liquidity updates")
            
        except Exception as e:
            self.logger.error(f"Error processing batch events: {e}", exc_info=True)

    async def _batch_update_database(self, price_updates: List[Dict], volume_updates: List[Dict], liquidity_updates: List[Dict]):
        """
        Efficiently update database with batched operations.
        """
        if not self.db:
            return
            
        try:
            # Batch price updates
            if price_updates:
                await self._execute_batch_price_updates(price_updates)
                
            # Batch volume updates  
            if volume_updates:
                await self._execute_batch_volume_updates(volume_updates)
                
            # Batch liquidity updates
            if liquidity_updates:
                await self._execute_batch_liquidity_updates(liquidity_updates)
                
        except Exception as e:
            self.logger.error(f"Error in batch database update: {e}", exc_info=True)

    async def _execute_batch_price_updates(self, price_updates: List[Dict]):
        """
        Execute batch price updates with optimized database operations.
        """
        if not price_updates:
            return
            
        # Group by mint to use latest price for each
        mint_prices = {}
        for update in price_updates:
            mint = update['mint']
            if mint not in mint_prices or update['timestamp'] > mint_prices[mint]['timestamp']:
                mint_prices[mint] = update
                
            # Record price for comparison aggregation 
            if hasattr(self, 'price_aggregator'):
                self.price_aggregator.record_price_update(
                    mint=mint,
                    price=update['price'],
                    source='blockchain'
                )
                
        # Update database with latest prices
        for mint, price_data in mint_prices.items():
            try:
                await self.update_token_price(mint, price_data['price'], price_data['source'])
            except Exception as e:
                self.logger.warning(f"Failed to update price for {mint[:8]}: {e}")

    async def _execute_batch_volume_updates(self, volume_updates: List[Dict]):
        """
        Execute batch volume updates with aggregation.
        """
        if not volume_updates:
            return
            
        # Aggregate volume by mint
        mint_volumes = {}
        for update in volume_updates:
            mint = update['mint']
            if mint not in mint_volumes:
                mint_volumes[mint] = 0
            mint_volumes[mint] += update['volume_increment']
            
        # Update database with aggregated volumes
        for mint, total_volume in mint_volumes.items():
            try:
                await self.update_token_volume(mint, total_volume)
            except Exception as e:
                self.logger.warning(f"Failed to update volume for {mint[:8]}: {e}")

    async def _execute_batch_liquidity_updates(self, liquidity_updates: List[Dict]):
        """
        Execute batch liquidity updates with latest value per mint.
        """
        if not liquidity_updates:
            return
            
        # Use latest liquidity for each mint
        mint_liquidity = {}
        for update in liquidity_updates:
            mint = update['mint']
            if mint not in mint_liquidity or update['timestamp'] > mint_liquidity[mint]['timestamp']:
                mint_liquidity[mint] = update
                
        # Update database with latest liquidity
        for mint, liquidity_data in mint_liquidity.items():
            try:
                await self.update_token_liquidity(mint, liquidity_data['liquidity'])
            except Exception as e:
                self.logger.warning(f"Failed to update liquidity for {mint[:8]}: {e}")

    async def _update_batch_analytics(self, batch: List[Dict]):
        """
        Update analytics and metrics from batch processing.
        """
        try:
            # Track event processing metrics
            if not hasattr(self, '_analytics'):
                self._analytics = {
                    'events_processed_total': 0,
                    'events_by_type': {},
                    'events_by_dex': {},
                    'batch_processing_times': [],
                    'last_analytics_update': time.time()
                }
                
            start_time = time.time()
            
            for event in batch:
                event_type = event.get('event_type', 'unknown')
                dex_id = event.get('dex_id', 'unknown')
                
                self._analytics['events_processed_total'] += 1
                self._analytics['events_by_type'][event_type] = self._analytics['events_by_type'].get(event_type, 0) + 1
                self._analytics['events_by_dex'][dex_id] = self._analytics['events_by_dex'].get(dex_id, 0) + 1
                
            # Record batch processing time
            processing_time = time.time() - start_time
            self._analytics['batch_processing_times'].append(processing_time)
            
            # Keep only last 100 processing times
            if len(self._analytics['batch_processing_times']) > 100:
                self._analytics['batch_processing_times'] = self._analytics['batch_processing_times'][-100:]
                
            self._analytics['last_analytics_update'] = time.time()
            
            # Log performance metrics every 1000 events
            if self._analytics['events_processed_total'] % 1000 == 0:
                avg_processing_time = sum(self._analytics['batch_processing_times']) / len(self._analytics['batch_processing_times'])
                self.logger.info(f"📊 Analytics: {self._analytics['events_processed_total']} events processed, avg batch time: {avg_processing_time:.3f}s")
                self.logger.info(f"📊 Top event types: {sorted(self._analytics['events_by_type'].items(), key=lambda x: x[1], reverse=True)[:3]}")
                
        except Exception as e:
            self.logger.warning(f"Error updating batch analytics: {e}")

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get current performance metrics and statistics.
        """
        metrics = {
            'timestamp': time.time(),
            'realtime_tokens_tracked': len(getattr(self, '_realtime_token_state', {})),
            'active_streams': len(self.actively_streamed_mints),
            'batch_queue_size': len(getattr(self, '_batch_queue', [])),
        }
        
        if hasattr(self, '_analytics'):
            metrics.update({
                'total_events_processed': self._analytics['events_processed_total'],
                'events_by_type': self._analytics['events_by_type'],
                'events_by_dex': self._analytics['events_by_dex'],
                'avg_batch_processing_time': sum(self._analytics['batch_processing_times']) / len(self._analytics['batch_processing_times']) if self._analytics['batch_processing_times'] else 0,
                'last_analytics_update': self._analytics['last_analytics_update']
            })
            
        # Add WebSocket health metrics
        if hasattr(self, 'blockchain_listener') and self.blockchain_listener:
            if hasattr(self.blockchain_listener, 'ws_connections'):
                metrics['websocket_connections'] = len(self.blockchain_listener.ws_connections)
                metrics['websocket_health'] = {
                    program_id: 'healthy' if hasattr(self.blockchain_listener, '_is_connection_open') and self.blockchain_listener._is_connection_open(ws) else 'unhealthy'
                    for program_id, ws in self.blockchain_listener.ws_connections.items()
                }
        
        return metrics

    async def _process_parsed_swap(self, swap_info: Dict, subscribed_item_address: Optional[str], dex_id: str):
        """
        Process parsed swap information from any DEX parser in a generic way.
        This method handles standardized swap data regardless of which parser generated it.
        
        Args:
            swap_info: Standardized swap information from parser
            subscribed_item_address: The pool/pair address being monitored  
            dex_id: The DEX identifier (e.g., 'raydium_v4', 'pumpswap', 'raydium_clmm')
        """
        try:
            # Extract standardized fields that all parsers should provide
            price = swap_info.get('price') or swap_info.get('price_ratio')
            amount_in = swap_info.get('amount_in')
            amount_out = swap_info.get('amount_out')
            mint_address = (swap_info.get('mint') or 
                          swap_info.get('token_mint') or 
                          swap_info.get('mint_address'))
            
            # If direct price not available, calculate from amounts
            if not price and amount_in and amount_out and amount_in > 0:
                calculated_price = amount_out / amount_in
                
                # Apply decimal adjustments if available
                in_decimals = swap_info.get('amount_in_decimals', 9)  # Default SOL decimals
                out_decimals = swap_info.get('amount_out_decimals', 6)  # Default token decimals
                if in_decimals != out_decimals:
                    decimal_factor = 10 ** (in_decimals - out_decimals)
                    calculated_price = calculated_price * decimal_factor
                    
                price = calculated_price
            
            # Log the swap event generically
            instruction_type = swap_info.get('instruction_type', 'swap')
            swap_direction = swap_info.get('swap_direction', 'N/A')
            self.logger.debug(f"{dex_id.upper()} {instruction_type} event processed for {subscribed_item_address or 'N/A'}: {swap_direction}")
            
            # Update real-time state if we have sufficient data
            if mint_address and price:
                await self._update_realtime_token_state(
                    mint_address=mint_address,
                    event_type='swap',
                    price=price,
                    raw_event_data=swap_info,
                    dex_id=dex_id,
                    pair_address=subscribed_item_address
                )
            elif price:
                # Fallback: Find which mint this relates to using token_pair_map
                token_pair_map = getattr(self, 'token_pair_map', {})
                for mint, pair_addr in token_pair_map.items():
                    if pair_addr == subscribed_item_address:
                        await self._update_realtime_token_state(
                            mint_address=mint,
                            event_type='swap',
                            price=price,
                            raw_event_data=swap_info,
                            dex_id=dex_id,
                            pair_address=subscribed_item_address
                        )
                        break
                else:
                    self.logger.debug(f"{dex_id} swap event detected with price {price} but no matching mint found for pair {subscribed_item_address}")
            else:
                self.logger.debug(f"{dex_id} swap event detected but missing price ({price}) or mint_address ({mint_address}) for real-time update")
                
        except Exception as e:
            self.logger.error(f"Error processing parsed swap from {dex_id}: {e}", exc_info=True)

    # === Price Parser Integration Methods ===
    
    async def _start_price_parser_monitoring(self, mint: str):
        """Start price parser monitoring for a token"""
        try:
            # Add token to all price parsers
            for parser_name, parser in self.price_parsers.items():
                parser.add_token_to_monitor(mint)
                self.logger.info(f"Added {mint[:8]}... to {parser_name} monitoring")
            
            # Start price monitoring if not already running
            await self._ensure_price_parsers_running()
            
        except Exception as e:
            self.logger.error(f"Error starting price parser monitoring for {mint}: {e}")
    
    async def _stop_price_parser_monitoring(self, mint: str):
        """Stop price parser monitoring for a token"""
        try:
            # Remove token from all price parsers
            for parser_name, parser in self.price_parsers.items():
                parser.remove_token_from_monitor(mint)
                self.logger.info(f"Removed {mint[:8]}... from {parser_name} monitoring")
                
        except Exception as e:
            self.logger.error(f"Error stopping price parser monitoring for {mint}: {e}")
    
    async def _ensure_price_parsers_running(self):
        """Ensure all price parsers are running"""
        try:
            for parser_name, parser in self.price_parsers.items():
                if not parser.is_running:
                    # Create callback for price updates
                    async def price_callback(price_data):
                        await self._handle_price_parser_update(price_data)
                    
                    await parser.start_price_monitoring(callback=price_callback)
                    self.logger.info(f"Started {parser_name} price monitoring")
                    
        except Exception as e:
            self.logger.error(f"Error ensuring price parsers are running: {e}")
    
    async def _handle_price_parser_update(self, price_data: Dict[str, Any]):
        """Handle price updates from price parsers"""
        try:
            mint = price_data.get('mint')
            if not mint:
                return
            
            # Update real-time token state
            await self._update_realtime_token_state(
                mint_address=mint,
                event_type='price_api_update',
                price=price_data.get('price_sol'),
                raw_event_data=price_data,
                dex_id=price_data.get('dex_id'),
                pair_address=None
            )
            
            # Log the price update
            source = price_data.get('source', 'unknown')
            price_sol = price_data.get('price_sol')
            price_usd = price_data.get('price_usd')
            
            if price_sol:
                try:
                    price_sol_float = float(price_sol)
                    price_str = f"{price_sol_float:.8f} SOL"
                    if price_usd:
                        price_str += f" (${price_usd:.6f})"
                    self.logger.info(f"💰 {source.upper()} price: {mint[:8]}... = {price_str}")
                except (ValueError, TypeError):
                    self.logger.warning(f"💰 {source.upper()} price: {mint[:8]}... = {price_sol} SOL (invalid format)")
            
        except Exception as e:
            self.logger.error(f"Error handling price parser update: {e}")
    
    async def get_price_parser_status(self) -> Dict[str, Any]:
        """Get status of all price parsers"""
        try:
            status = {}
            for parser_name, parser in self.price_parsers.items():
                status[parser_name] = parser.get_monitoring_status()
            return status
        except Exception as e:
            self.logger.error(f"Error getting price parser status: {e}")
            return {}
    
    async def fetch_single_price_from_parsers(self, mint: str) -> Dict[str, Any]:
        """Fetch current price for a token from all price parsers"""
        try:
            prices = {}
            for parser_name, parser in self.price_parsers.items():
                try:
                    price_data = await parser.fetch_single_price(mint)
                    if price_data:
                        prices[parser_name] = price_data
                except Exception as e:
                    self.logger.error(f"Error fetching price from {parser_name}: {e}")
            
            return prices
        except Exception as e:
            self.logger.error(f"Error fetching prices from parsers for {mint}: {e}")
            return {}
