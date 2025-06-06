import os
import logging
import asyncio
import json
from pathlib import Path
import sys
from typing import Coroutine, Dict, Any, List, Optional, Callable, TYPE_CHECKING, Tuple, Set, Union
from solders.pubkey import Pubkey
from dotenv import load_dotenv
from datetime import datetime, timezone
# import websockets # Use websockets library directly # MODIFIED
import websockets  # ADDED: Import websockets module for proper exception handling
from websockets import connect as websockets_connect # MODIFIED: Use standard connect instead of legacy
from websockets.exceptions import WebSocketException, ConnectionClosed, InvalidStatusCode # MODIFIED: Explicitly import exceptions
import backoff # For retry logic
import base64 # Added base64
import borsh_construct as bc # Added borsh_construct
from utils.logger import get_logger
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType
# from utils.rate_limiter import RateLimiter # Commented out
from websockets.protocol import State # Import the State enum
from websockets.asyncio.client import ClientConnection as WebSocketCommonProtocol # MODIFIED: Use ClientConnection for websockets 15.x
import random
import time
import itertools
import urllib.parse
import socket

# Import Settings for type hinting and access
if TYPE_CHECKING:
    from config.settings import Settings
from config.settings import Settings # Direct import for runtime

# Load environment variables from .env
# Ensure the path is correct relative to the execution directory (usually project root)
# env_path = Path(__file__).parent.parent / 'config' / '.env' # Loading handled by Settings
# load_dotenv(dotenv_path=env_path)

# Configure logging using centralized logger
logger = get_logger(__name__)

# --- Define known DEX program IDs --- # REMOVED - Now loaded via settings
# KNOWN_DEX_PROGRAMS = { ... }
# --------------------------------- #

# Define default DEX program IDs to monitor (can be overridden by env var)
# These are used for the initial, broad program subscriptions if multi-connection mode is on
# REMOVED - Logic now uses settings.monitored_programs directly
# DEFAULT_PROGRAMS_TO_MONITOR = [ ... ]

# Define backoff handlers outside the class or as static methods
# These handlers won't have access to 'self'
def _backoff_handler(details):
    exc_type, exc_value, _ = sys.exc_info()
    # Note: We don't know which program_id this is for without more context passing
    logger.warning(
        f"WebSocket connection error ({exc_value}), backing off {details['wait']:.1f}s "
        f"(attempt {details['tries']})"
    )

def _giveup_handler(details):
     # Note: We don't know which program_id this is for without more context passing
     exception_details = details.get('exception') # Get the exception from details
     logger.error(
         f"WebSocket connection failed after {details['tries']} attempts. Giving up. Exception: {exception_details}"
     )
     # Consider setting a flag or notifying another component that the listener is down for this program

# Define program IDs (Consider moving these to settings)
PUMPFUN_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
PUMPSWAP_PROGRAM_ID = Pubkey.from_string("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA")

MAX_LISTEN_RETRIES = 10  # Maximum retries for the listen method - Reverted to module constant

class BlockchainListener:
    """
    Listens to Solana WebSocket endpoint for logs involving specified programs or accounts.
    Manages multiple connections (one per program) to comply with free tier limits.
    Can subscribe to specific pool addresses using logsSubscribe with mentions filter.
    Uses the `websockets` library directly for connection and message handling.
    """
    # Add new attributes for time-based aggregated logging
    _program_message_cumulative_counts: Dict[str, int] # To hold existing cumulative counts
    _program_last_log_flush_time: Dict[str, float] # Tracks last log time per program
    LOG_AGGREGATION_INTERVAL_SECONDS: int # Interval for logging

    def __init__(self,
                 settings: 'Settings', # Accept settings object
                 callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]] = None,
                 solana_client = None, # Keep optional for now if needed elsewhere
                 multi_connection_mode: bool = True,
                 logger = None,
                 http_client = None): # Default to multi-connection
        """
        Initializes the BlockchainListener.

        Args:
            settings: The application settings object.
            callback: Async function to call with each received notification.
            solana_client: Optional Solana client instance (currently unused here).
            multi_connection_mode: If True, creates one WebSocket connection per program ID.
                                 If False, uses one connection for all programs (not recommended for free tiers).
            logger: Optional logger instance
            http_client: Optional HTTP client instance
        """
        # Store references
        self.settings = settings
        self.logger = logger or get_logger(__name__)
        self.http_client = http_client
        self._initialized = False # Initialize state flag
        self._callback = callback # Store with underscore
        
        # Initialize configuration access directly from settings
        self.config_manager = settings
        
        # Legacy attributes for backward compatibility
        self.websocket_url = getattr(self.settings, 'SOLANA_WSS_URL', '')
        
        self.solana_client = solana_client # Store if needed later
        self._stop_event = asyncio.Event()
        self._multi_connection_mode = multi_connection_mode
        
        self._task_group: Optional[asyncio.TaskGroup] = None
        self._listen_tasks: Dict[str, asyncio.Task] = {} # Program ID (str) -> Task (managed by TaskGroup)
        
        # WebSocket connections are now managed by connection_manager
        # Legacy attribute for backward compatibility
        self.ws_connections: Dict[str, Optional[WebSocketCommonProtocol]] = {}
        
        # Circuit breakers for connection reliability
        self.circuit_breakers = {}
        
        # Endpoint status and metrics tracking
        self._endpoint_status = {
            "primary": {
                "connection_attempts": 0,
                "connection_successes": 0,
                "subscription_attempts": 0,
                "subscription_successes": 0,
                "failures": 0,
                "last_success_time": None,
                "last_failure": None
            },
            "fallback": {
                "connection_attempts": 0,
                "connection_successes": 0,
                "subscription_attempts": 0,
                "subscription_successes": 0,
                "failures": 0,
                "last_success_time": None,
                "last_failure": None
            }
        }
        
        self.metrics = {
            "primary": {
                "total_connections": 0,
                "successful_connections": 0,
                "failed_connections": 0,
                "total_subscriptions": 0,
                "successful_subscriptions": 0,
                "failed_subscriptions": 0,
                "last_hour_attempts": 0,
                "last_hour_successes": 0,
                "last_hour_timestamp": time.time()
            },
            "fallback": {
                "total_connections": 0,
                "successful_connections": 0,
                "failed_connections": 0,
                "total_subscriptions": 0,
                "successful_subscriptions": 0,
                "failed_subscriptions": 0,
                "last_hour_attempts": 0,
                "last_hour_successes": 0,
                "last_hour_timestamp": time.time()
            }
        }

        # --- Subscription Tracking ---
        self._callbacks = {}  # Mapping from program ID to callback
        self._program_log_subscription_ids: Dict[str, int] = {} # program_id_str -> subscription_id (stores actual sub ID after confirmation)
        self._program_log_request_ids: Dict[str, int] = {} # program_id_str -> request_id (tracks pending confirmation)
        self._pending_confirmations = {}  # Mapping from request ID to confirmation event & result holder
        self._pending_account_subs = {}  # Mapping from request ID to account addresses for pending account subscriptions
        self._pending_pool_subs = {}  # Mapping from request ID to pool addresses for pending pool subscriptions
        self._account_subscriptions: Dict[str, int] = {} # account_pubkey -> subscription_id
        self._pool_log_subscriptions: Dict[str, int] = {} # pool_address -> subscription_id
        # self._connection_tasks = {} # Replaced by TaskGroup management for listen tasks

        # --- Initialize counter attributes ---
        self._next_request_id = 1 # Counter for unique request IDs
        self._program_message_cumulative_counts = {}  # Message counts by program ID
        self._program_message_rates = {}  # Message rates by program ID
        self._program_last_reset_time = {}  # Last reset time for rate calculation by program ID
        self._program_message_count_at_last_log = {}  # Message counts at last log
        self._program_time_of_last_log = {}  # Time of last log
        
        # --- Enhanced Subscription Tracking ---
        # Maps subscription_id -> (target_address, dex_id, subscription_type)
        self._active_subscriptions: Dict[int, Tuple[str, str, str]] = {}
        # Maps pool_address -> {'account': subscription_id, 'logs': subscription_id, 'dex_id': str}
        self._pool_subscriptions: Dict[str, Dict[str, Union[int, str]]] = {}
        
        # Enhanced tracking for subscriptions
        self._pool_account_subscriptions = {}  # Mapping from pool address to {'subscription_id': id, 'dex_id': dex_id}
        
        # Initialize message counter tracking
        self._message_count = 0
        self._start_time = time.time()
        
        # Initialize monitored tokens and program IDs
        self.monitored_tokens = set()
        self.subscribers = []
        self._resolved_monitored_program_ids = set()  # Will hold validated program IDs
        
        # Parse monitored programs from settings
        self.dex_names_to_monitor_initially = getattr(self.settings, 'MONITORED_PROGRAMS_LIST', [])
        
        # --- WebSocket connection lock ---
        self._ws_lock = asyncio.Lock() # May not be needed with TaskGroup, review later
        


        # New priority tiers for token monitoring strategy
        self.PRIORITY_HIGH = 'high'
        self.PRIORITY_MEDIUM = 'medium'
        self.PRIORITY_LOW = 'low'
        
        self._token_priority_levels = {}
        
        self.debug_mode = True
        
        # Connection timeout constant
        self.CONNECTION_TIMEOUT = 30  # Default WebSocket connection timeout in seconds
        
        self.logger.info("BlockchainListener basic initialization complete")
        
        # Initialize WebSocket connection manager
        from data.websocket_connection_manager import WebSocketConnectionManager
        self.connection_manager = WebSocketConnectionManager(settings, self.logger)
        
        # Initialize DEX-specific parsers with dedicated blockchain logger
        from config.blockchain_logging import setup_blockchain_logger, setup_price_monitoring_logger, PriceMonitoringAggregator
        from data import RaydiumV4Parser, PumpSwapParser, RaydiumClmmParser
        
        self.blockchain_logger = setup_blockchain_logger("BlockchainListener")
        
        # Initialize price monitoring aggregator for 60-second summaries to main log
        price_monitor_logger = setup_price_monitoring_logger("PriceMonitoring")
        self.price_aggregator = PriceMonitoringAggregator(price_monitor_logger)
        
        # Initialize parser registry
        self.parsers = {
            'raydium_v4': RaydiumV4Parser(self.settings, self.blockchain_logger),
            'pumpswap': PumpSwapParser(self.settings, self.blockchain_logger),
            'raydium_clmm': RaydiumClmmParser(self.settings, self.blockchain_logger)
        }
        
        # Initialize message dispatcher for handling WebSocket messages
        from data.message_dispatcher import MessageDispatcher
        self.message_dispatcher = MessageDispatcher(self, self.logger)
        
        self.blockchain_logger.info(f"Initialized connection manager, {len(self.parsers)} DEX parsers, price monitoring aggregator, and message dispatcher: {list(self.parsers.keys())}")
        
        try:
            self._pumpswap_amm_layout = bc.CStruct(
                "version" / bc.U8,
                "status" / bc.U8,
                "bump" / bc.U8,
                "decimals" / bc.U8,
                "minimum_sol_amount" / bc.U64,
                "minimum_token_amount" / bc.U64,
                "total_trade_volume_sol" / bc.U64,
                "total_trade_volume_token" / bc.U64,
                "sol_balance" / bc.U64,
                "token_balance" / bc.U64,
                "last_swap_timestamp" / bc.I64,
                "owner" / bc.Bytes[32],
                "token_mint" / bc.Bytes[32],
                "token_vault" / bc.Bytes[32],
                "sol_vault" / bc.Bytes[32],
                "quote_token_mint" / bc.Bytes[32],
                "fee_percentage" / bc.U16,
                "fee_owner" / bc.Bytes[32],
                "config" / bc.Bytes[32]
            )
            self.blockchain_logger.info("BlockchainListener: Defined _pumpswap_amm_layout.")
            
            # Define Raydium V4 pool layout for price calculation
            self._raydium_v4_pool_layout = bc.CStruct(
                "status" / bc.U64,
                "nonce" / bc.U64,
                "max_order" / bc.U64,
                "depth" / bc.U64,
                "base_decimal" / bc.U64,
                "quote_decimal" / bc.U64,
                "state" / bc.U64,
                "reset_flag" / bc.U64,
                "min_size" / bc.U64,
                "vol_max_cut_ratio" / bc.U64,
                "amount_wave_ratio" / bc.U64,
                "base_lot_size" / bc.U64,
                "quote_lot_size" / bc.U64,
                "min_price_multiplier" / bc.U64,
                "max_price_multiplier" / bc.U64,
                "system_decimal_value" / bc.U64,
                "min_separate_numerator" / bc.U64,
                "min_separate_denominator" / bc.U64,
                "trade_fee_numerator" / bc.U64,
                "trade_fee_denominator" / bc.U64,
                "pnl_numerator" / bc.U64,
                "pnl_denominator" / bc.U64,
                "swap_fee_numerator" / bc.U64,
                "swap_fee_denominator" / bc.U64,
                "base_need_take_pnl" / bc.U64,
                "quote_need_take_pnl" / bc.U64,
                "quote_total_pnl" / bc.U64,
                "base_total_pnl" / bc.U64,
                "pool_open_time" / bc.U64,
                "punish_pc_amount" / bc.U64,
                "punish_coin_amount" / bc.U64,
                "orderbook_to_init_time" / bc.U64,
                "swap_base_in_amount" / bc.U128,
                "swap_quote_out_amount" / bc.U128,
                "swap_base_out_amount" / bc.U128,
                "swap_quote_in_amount" / bc.U128,
                "swap_base_to_quote_fee" / bc.U64,
                "swap_quote_to_base_fee" / bc.U64,
                "pool_base_vault" / bc.Bytes[32],
                "pool_quote_vault" / bc.Bytes[32],
                "base_mint" / bc.Bytes[32],
                "quote_mint" / bc.Bytes[32],
                "lp_mint" / bc.Bytes[32],
                "open_orders" / bc.Bytes[32],
                "market_id" / bc.Bytes[32],
                "market_program_id" / bc.Bytes[32],
                "target_orders" / bc.Bytes[32],
                "withdraw_queue" / bc.Bytes[32],
                "lp_vault" / bc.Bytes[32],
                "owner" / bc.Bytes[32],
                "lp_reserve" / bc.U64
                # Skip protocol_fee_recipients array and padding for now as they're not needed for price calculation
            )
            self.blockchain_logger.info("BlockchainListener: Defined _raydium_v4_pool_layout.")
            
        except Exception as e:
            self.blockchain_logger.error(f"BlockchainListener: Error defining AMM layouts: {e}", exc_info=True)
            self._pumpswap_amm_layout = None
            self._raydium_v4_pool_layout = None

    def _is_connection_open(self, ws) -> bool:
        """Check if WebSocket connection is open (compatible with both old and new websockets API)"""
        if not ws:
            return False
        
        # For websockets 15.x (ClientConnection with state attribute)
        if hasattr(ws, 'state'):
            return ws.state == State.OPEN
        
        # For older websockets versions (with .open attribute)
        if hasattr(ws, 'open'):
            return ws.open
            
        # Fallback
        return False

    def _ensure_valid_ws_url(self, url: str) -> str:
        """
        Ensure that a WebSocket URL is properly formatted with scheme and API key.
        
        Args:
            url: The WebSocket URL to validate and fix if needed
            
        Returns:
            str: Properly formatted WebSocket URL
        """
        # Debug the input URL
        self.blockchain_logger.debug(f"Validating WebSocket URL: {self._mask_url(url)}")
        
        if not url:
            self.logger.error("Empty WebSocket URL provided")
            # Return a placeholder that will fail gracefully
            return "wss://invalid-placeholder"
            
        # Fix URL if it doesn't have the wss:// prefix
        if not url.startswith("wss://"):
            if url.startswith("http://"):
                url = url.replace("http://", "wss://")
            elif url.startswith("https://"):
                url = url.replace("https://", "wss://")
            else:
                url = f"wss://{url}"
            self.blockchain_logger.debug(f"Fixed WebSocket protocol: {self._mask_url(url)}")
        
        # Ensure URL has api-key parameter for Helius endpoints
        if "helius" in url.lower() and "api-key" not in url:
            # Check if URL already has query parameters
            if "?" in url:
                url = f"{url}&api-key={self.settings.HELIUS_API_KEY}"
            else:
                url = f"{url}?api-key={self.settings.HELIUS_API_KEY}"
            self.blockchain_logger.debug(f"Added API key to Helius URL: {self._mask_url(url)}")
            
        # Ensure there are no spaces or invalid characters in the URL
        url = url.strip()
        
        # Log the final URL (masked)
        self.blockchain_logger.debug(f"Final WebSocket URL: {self._mask_url(url)}")
        
        return url

    async def add_token_to_monitor(self, token_address: str):
        """Add a token to the monitoring list."""
        self.monitored_tokens.add(token_address)
        self.logger.info(f"Added token to monitoring: {token_address}")
        
    async def remove_token_from_monitor(self, token_address: str):
        """Remove a token from the monitoring list."""
        if token_address in self.monitored_tokens:
            self.monitored_tokens.remove(token_address)
            self.logger.info(f"Removed token from monitoring: {token_address}")

    async def _process_event(self, event_data: Dict):
        """Process an event and check if it's for a monitored token."""
        try:
            if not self.monitored_tokens:  # If no tokens are being monitored
                return
                
            # Extract token address from event
            token_address = self._extract_token_address(event_data)
            if not token_address:
                return
                
            # Only process events for monitored tokens
            if token_address not in self.monitored_tokens:
                return
                
            # Process and notify subscribers
            for subscriber in self.subscribers:
                try:
                    await subscriber(event_data)
                except Exception as e:
                    self.logger.error(f"Error in subscriber callback: {str(e)}")
                    
        except Exception as e:
            self.logger.error(f"Error processing event: {str(e)}")
            
    def _extract_token_address(self, event_data: Dict) -> Optional[str]:
        """Extract token address from event data."""
        try:
            # Add logic to extract token address from event
            # This will depend on your event structure
            return event_data.get("token_address")
        except Exception as e:
            self.logger.error(f"Error extracting token address: {str(e)}")
            return None



    # Add a helper method to mask API keys in URLs
    def _mask_url(self, url: str) -> str:
        """Masks the api-key parameter in a URL string."""
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
            # Fallback if parsing fails
            self.logger.warning(f"Failed to parse and mask URL: {e}")
            return url # Return original URL on error
        
    async def initialize(self) -> bool:
        """
        Initialize the BlockchainListener.
        Sets up WebSocket connections and subscriptions based on settings.
        Returns True if initialization was successful, False otherwise.
        """
        if self._initialized:
            self.blockchain_logger.warning("BlockchainListener already initialized. Skipping.")
            return True

        try:
            self.blockchain_logger.info("Initializing BlockchainListener...")
            
            # Get DEX names to monitor from settings
            self.dex_names_to_monitor_initially = self.settings.MONITORED_PROGRAMS_LIST
            if not self.dex_names_to_monitor_initially:
                self.blockchain_logger.warning("MONITORED_PROGRAMS setting is empty. Listener will rely on dynamic subscriptions only.")
                # Still mark as initialized for dynamic subscriptions
                self._initialized = True
                return True

            # Resolve program IDs for each DEX
            for dex_name in self.dex_names_to_monitor_initially:
                program_id_str = self.settings.DEX_PROGRAM_IDS.get(dex_name)
                if program_id_str:
                    try:
                        Pubkey.from_string(program_id_str)
                        self._resolved_monitored_program_ids.add(program_id_str)
                        self.blockchain_logger.info(f"Added program ID {program_id_str} for {dex_name} to monitoring set.")
                    except ValueError:
                        self.blockchain_logger.error(f"Invalid program ID format for {dex_name}: {program_id_str}")
                else:
                    self.blockchain_logger.warning(f"No program ID found for {dex_name} in settings.")

            # Initialize connections and circuit breakers for each program
            if self._multi_connection_mode:
                for prog_id_str in self._resolved_monitored_program_ids:
                    self.ws_connections[prog_id_str] = None
                    # self._listen_tasks[prog_id_str] = None # Tasks will be managed by TaskGroup
                    self.circuit_breakers[prog_id_str] = CircuitBreaker(
                        breaker_type=CircuitBreakerType.COMPONENT,
                        identifier=f"wss_{prog_id_str}",
                        max_consecutive_failures=5,
                        reset_after_minutes=5,
                    )
                    self.blockchain_logger.info(f"Initialized connection tracking for program {prog_id_str}")

            self._initialized = True
            # Use main logger for successful initialization - this is important for system status
            self.logger.info("🚀 BlockchainListener initialized successfully and ready for real-time monitoring")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize BlockchainListener: {e}", exc_info=True)
            return False

    def set_callback(self, callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]):
        """Set the callback function for blockchain events."""
        self._callback = callback
        self.blockchain_logger.info("Callback set for blockchain events")

    async def close(self):
        """Close all WebSocket connections and clean up resources."""
        try:
            self.blockchain_logger.info("Closing BlockchainListener...")
            
            # Set stop event
            self._stop_event.set()
            
            # Close all WebSocket connections through connection manager
            if hasattr(self, 'connection_manager'):
                await self.connection_manager.close_all_connections()
            
            # Clean up tasks
            if hasattr(self, '_listen_tasks'):
                for task in self._listen_tasks.values():
                    if task and not task.done():
                        task.cancel()
                
                if self._listen_tasks:
                    await asyncio.gather(*self._listen_tasks.values(), return_exceptions=True)
                    self._listen_tasks.clear()
            
            self.blockchain_logger.info("BlockchainListener closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error closing BlockchainListener: {e}", exc_info=True)

    async def run_forever(self):
        """Main loop for blockchain listening - establishes connections and processes messages."""
        try:
            self.logger.info("🔗 Starting BlockchainListener main loop for real-time monitoring")
            
            if not self._initialized:
                self.logger.error("BlockchainListener not initialized. Call initialize() first.")
                return
            
            # Start listening tasks for each program
            await self._start_listening_tasks()
            
            # Keep running until stop event is set
            while not self._stop_event.is_set():
                await asyncio.sleep(1)
                
                # Check connection health periodically
                if hasattr(self, '_last_health_check'):
                    if time.time() - self._last_health_check > 30:  # Every 30 seconds
                        await self._check_connection_health()
                        self._last_health_check = time.time()
                else:
                    self._last_health_check = time.time()
            
            self.logger.info("BlockchainListener main loop stopped")
            
        except Exception as e:
            self.logger.error(f"Error in BlockchainListener main loop: {e}", exc_info=True)

    async def _start_listening_tasks(self):
        """Start WebSocket listening tasks for all configured programs."""
        try:
            for program_id_str in self._resolved_monitored_program_ids:
                if program_id_str not in self._listen_tasks:
                    self.blockchain_logger.info(f"Starting listening task for program {program_id_str[:8]}...")
                    task = asyncio.create_task(self._listen_to_program(program_id_str))
                    self._listen_tasks[program_id_str] = task
                    
            self.logger.info(f"🎧 Started {len(self._listen_tasks)} blockchain listening tasks")
            
        except Exception as e:
            self.logger.error(f"Error starting listening tasks: {e}", exc_info=True)

    async def _listen_to_program(self, program_id_str: str):
        """Listen to WebSocket events for a specific program."""
        try:
            self.blockchain_logger.info(f"🔌 Establishing WebSocket connection for program {program_id_str[:8]}...")
            
            # Get connection through connection manager
            ws = await self.connection_manager.ensure_connection(program_id_str)
            if not ws:
                self.blockchain_logger.error(f"Failed to establish connection for {program_id_str[:8]}")
                return
            
            self.logger.info(f"🔗 BLOCKCHAIN CONNECTION SUCCESS for program {program_id_str[:8]}")
            
            # Subscribe to program logs
            await self._subscribe_to_program_logs(ws, program_id_str)
            
            # Process messages
            await self._process_messages(ws, program_id_str)
            
        except Exception as e:
            self.blockchain_logger.error(f"Error in _listen_to_program for {program_id_str[:8]}: {e}", exc_info=True)

    async def _subscribe_to_program_logs(self, ws, program_id_str: str):
        """Subscribe to logs for a specific program."""
        try:
            subscription_request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id,
                "method": "logsSubscribe",
                "params": [
                    {
                        "mentions": [program_id_str]
                    },
                    {
                        "commitment": "processed",
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            }
            
            await ws.send(json.dumps(subscription_request))
            self.blockchain_logger.info(f"📡 Subscribed to logs for program {program_id_str[:8]}")
            self._next_request_id += 1
            
        except Exception as e:
            self.blockchain_logger.error(f"Error subscribing to program logs for {program_id_str[:8]}: {e}")

    async def _process_messages(self, ws, program_id_str: str):
        """Process incoming WebSocket messages for a program."""
        try:
            async for message in ws:
                if self._stop_event.is_set():
                    break
                    
                try:
                    data = json.loads(message)
                    await self._handle_message(data, program_id_str)
                    
                except json.JSONDecodeError as e:
                    self.blockchain_logger.warning(f"Invalid JSON from {program_id_str[:8]}: {e}")
                except Exception as e:
                    self.blockchain_logger.error(f"Error processing message from {program_id_str[:8]}: {e}")
                    
        except Exception as e:
            self.blockchain_logger.error(f"Error in message processing loop for {program_id_str[:8]}: {e}")

    async def _handle_message(self, data: Dict, program_id_str: str):
        """Handle a single WebSocket message."""
        try:
            # Check if this is a subscription confirmation
            if "result" in data and "method" not in data:
                self.blockchain_logger.debug(f"Subscription confirmed for {program_id_str[:8]}: {data.get('result')}")
                return
            
            # Check if this is a log notification
            if data.get("method") == "logsNotification":
                params = data.get("params", {})
                result = params.get("result", {})
                
                # Extract transaction logs
                logs = result.get("value", {}).get("logs", [])
                signature = result.get("value", {}).get("signature", "unknown")
                
                if logs:
                    self.blockchain_logger.info(f"📡 BLOCKCHAIN EVENT: Program {program_id_str[:8]} - Transaction {signature[:8]}... - {len(logs)} logs")
                    
                    # Process with parsers to extract swap information
                    await self._process_swap_logs(logs, signature, program_id_str)
                    
                    # Call the callback if set
                    if self._callback:
                        event_data = {
                            "type": "blockchain_event",
                            "program_id": program_id_str,
                            "signature": signature,
                            "logs": logs,
                            "log_count": len(logs),
                            "has_swap_activity": self._contains_swap_activity(logs)
                        }
                        await self._callback(event_data)
                        
        except Exception as e:
            self.blockchain_logger.error(f"Error handling message from {program_id_str[:8]}: {e}")

    async def _process_swap_logs(self, logs: List[str], signature: str, program_id_str: str):
        """Process logs to extract swap information and calculate prices."""
        try:
            # Determine which DEX parser to use based on program ID
            dex_parser = None
            dex_name = None
            
            for name, prog_id in self.settings.DEX_PROGRAM_IDS.items():
                if prog_id == program_id_str:
                    dex_name = name
                    break
            
            if dex_name and dex_name in self.parsers:
                dex_parser = self.parsers[dex_name]
                
                # Parse the swap logs (FIXED: removed await since parse_swap_logs is synchronous)
                swap_data = dex_parser.parse_swap_logs(logs, signature)
                
                if swap_data:
                    # Extract price information
                    token_mint = swap_data.get("token_mint")
                    price_usd = swap_data.get("price_usd")
                    
                    if token_mint and price_usd:
                        self.blockchain_logger.info(f"💰 REALTIME PRICE UPDATE: Token {token_mint[:8]}... = ${price_usd:.8f} (from {dex_name})")
                        
                        # Aggregate price updates
                        if hasattr(self, 'price_aggregator'):
                            self.price_aggregator.add_price_update(token_mint, price_usd, dex_name)
                            
        except Exception as e:
            self.blockchain_logger.error(f"Error processing swap logs: {e}")

    def _contains_swap_activity(self, logs: List[str]) -> bool:
        """Check if logs contain swap-related activity."""
        swap_keywords = ["swap", "trade", "buy", "sell", "exchange"]
        log_text = " ".join(logs).lower()
        return any(keyword in log_text for keyword in swap_keywords)

    async def _check_connection_health(self):
        """Check the health of all WebSocket connections."""
        try:
            unhealthy_connections = []
            
            for program_id_str, task in self._listen_tasks.items():
                if task.done() or task.cancelled():
                    unhealthy_connections.append(program_id_str)
                    self.blockchain_logger.warning(f"Connection task for {program_id_str[:8]} is no longer running")
            
            # Restart unhealthy connections
            for program_id_str in unhealthy_connections:
                self.blockchain_logger.info(f"Restarting connection for {program_id_str[:8]}...")
                task = asyncio.create_task(self._listen_to_program(program_id_str))
                self._listen_tasks[program_id_str] = task
                
        except Exception as e:
            self.blockchain_logger.error(f"Error checking connection health: {e}")

    async def add_token_to_monitor(self, mint_address: str, pair_address: str = None, dex_id: str = None):
        """Add a specific token to real-time monitoring."""
        try:
            self.monitored_tokens.add(mint_address)
            
            if pair_address and dex_id:
                # Subscribe to specific pair if we have the details
                await self._subscribe_to_pair(pair_address, dex_id)
                
            self.logger.info(f"🎯 Added token {mint_address[:8]}... to real-time blockchain monitoring")
            
        except Exception as e:
            self.logger.error(f"Error adding token to monitor: {e}")

    async def _subscribe_to_pair(self, pair_address: str, dex_id: str):
        """Subscribe to a specific trading pair for real-time updates."""
        try:
            # This would implement pair-specific subscriptions
            # For now, we rely on the program-level subscriptions
            self.blockchain_logger.info(f"Monitoring pair {pair_address[:8]}... on {dex_id}")
            
        except Exception as e:
            self.blockchain_logger.error(f"Error subscribing to pair {pair_address}: {e}")

    async def subscribe_to_pool_account(self, pool_address: str, dex_id: str) -> bool:
        """
        Subscribe to direct account updates for a pool/AMM address.
        This provides immediate updates when pool state changes (reserves, liquidity, etc.)
        
        Args:
            pool_address: The pool/AMM account address to monitor
            dex_id: The DEX identifier (e.g., 'raydium_v4', 'pumpswap')
            
        Returns:
            bool: True if subscription was successful, False otherwise
        """
        try:
            self.blockchain_logger.info(f"🔗 Attempting account subscription for {dex_id.upper()} pool: {pool_address[:8]}...")
            
            # Get connection through connection manager
            ws = await self.connection_manager.ensure_connection(dex_id)
            if not ws:
                self.blockchain_logger.error(f"Failed to get connection for {dex_id} account subscription")
                return False
            
            request_id = self._next_request_id
            self._next_request_id += 1
            
            # Create accountSubscribe request
            subscription_request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "accountSubscribe",
                "params": [
                    pool_address,
                    {
                        "encoding": "base64",  # Get raw account data for parsing
                        "commitment": "confirmed"
                    }
                ]
            }
            
            # Set up confirmation tracking
            confirmation_event = asyncio.Event()
            confirmation_result = {"subscription_id": None, "success": False}
            self._pending_confirmations[request_id] = (confirmation_event, confirmation_result)
            self._pending_account_subs[request_id] = pool_address
            
            # Send subscription request
            await ws.send(json.dumps(subscription_request))
            self.blockchain_logger.info(f"📡 Sent account subscription request for {pool_address[:8]}... (request_id: {request_id})")
            
            # Wait for confirmation with timeout
            try:
                await asyncio.wait_for(confirmation_event.wait(), timeout=30)
                
                if confirmation_result["success"]:
                    subscription_id = confirmation_result["subscription_id"]
                    
                    # Store subscription tracking
                    self._account_subscriptions[pool_address] = subscription_id
                    self._active_subscriptions[subscription_id] = (pool_address, dex_id, "account")
                    
                    self.blockchain_logger.info(f"✅ Account subscription successful for {dex_id.upper()} pool {pool_address[:8]}... (sub_id: {subscription_id})")
                    return True
                else:
                    self.blockchain_logger.error(f"❌ Account subscription failed for {pool_address[:8]}...")
                    return False
                    
            except asyncio.TimeoutError:
                self.blockchain_logger.error(f"❌ Timeout waiting for account subscription confirmation for {pool_address[:8]}...")
                return False
            finally:
                # Cleanup tracking
                self._pending_confirmations.pop(request_id, None)
                self._pending_account_subs.pop(request_id, None)
                
        except Exception as e:
            self.blockchain_logger.error(f"Error subscribing to pool account {pool_address}: {e}", exc_info=True)
            return False

    async def unsubscribe_from_pool_data(self, pool_address: str) -> bool:
        """
        Unsubscribe from pool account data.
        
        Args:
            pool_address: The pool address to unsubscribe from
            
        Returns:
            bool: True if unsubscription was successful, False otherwise
        """
        try:
            if pool_address not in self._account_subscriptions:
                self.blockchain_logger.warning(f"No active account subscription found for {pool_address[:8]}...")
                return False
                
            subscription_id = self._account_subscriptions[pool_address]
            
            # Find the connection (we need to know which connection this subscription is on)
            ws = None
            for program_id, connection in self.connection_manager.connections.items():
                if connection and self.connection_manager._is_connection_open(connection):
                    ws = connection
                    break
                    
            if not ws:
                self.blockchain_logger.error(f"No active connection found for unsubscribing from {pool_address[:8]}...")
                return False
            
            # Send unsubscribe request
            unsubscribe_request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id,
                "method": "accountUnsubscribe",
                "params": [subscription_id]
            }
            
            await ws.send(json.dumps(unsubscribe_request))
            self._next_request_id += 1
            
            # Clean up tracking
            del self._account_subscriptions[pool_address]
            self._active_subscriptions.pop(subscription_id, None)
            
            self.blockchain_logger.info(f"📡 Unsubscribed from account data for pool {pool_address[:8]}... (sub_id: {subscription_id})")
            return True
            
        except Exception as e:
            self.blockchain_logger.error(f"Error unsubscribing from pool account {pool_address}: {e}", exc_info=True)
            return False
