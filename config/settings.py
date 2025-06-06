import os
import logging
from pathlib import Path
from typing import List, Optional, Any, Union, Dict
from utils.logger import get_logger
from pydantic import Field, field_validator, ValidationInfo, model_validator, PrivateAttr
import json
from pydantic import AliasChoices
from pydantic_settings import BaseSettings
from pydantic import SecretStr

# Get logger for this module
logger = get_logger(__name__)

# Define BASE_DIR relative to this file's location (config/settings.py -> project root)
BASE_DIR = Path(__file__).parent.parent

# Create outputs directory relative to BASE_DIR if it doesn't exist
outputs_dir = BASE_DIR / "outputs"
try:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Ensured outputs directory exists: {outputs_dir}")
except Exception as e:
    logger.error(f"Failed to create outputs directory {outputs_dir}: {e}")

# Add EncryptionSettings for retrieving the encryption key path from .env
class EncryptionSettings(BaseSettings):
    """Loads only the ENCRYPTION_KEY_PATH from the environment."""
    ENCRYPTION_KEY_PATH: str

    class Config:
        env_file = BASE_DIR / "config" / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

class Settings(BaseSettings):
    """
    Manages application settings and configuration using Pydantic BaseSettings.
    Reads variables from .env file automatically.
    """
    # Use PrivateAttr for derived values not directly from env
    _database_file_path: Optional[str] = PrivateAttr(None)
    # _helius_wss_url_base: Optional[str] = PrivateAttr(None)  # Store the base WebSocket URL # REMOVED

    # === Environment Variables ===
    # Define all settings as class attributes with type hints.
    # Pydantic will load these from the environment/.env file.
    # Add default=... ONLY if a default is truly acceptable (violates rule otherwise)
    # Per rule, NO DEFAULTS should be added here. Pydantic will raise error if missing.

    # --- Logging ---
    LOG_LEVEL: str
    LOG_FILE: str # Assuming LOG_FILE is also needed from env
    ENABLE_CONSOLE_LOGGING: bool = True # Assuming True is the desired default if not in env

    # --- Database ---
    DATABASE_URL_ENV: str = Field(alias='DATABASE_URL') # Use alias to avoid clash with property

    # --- File Paths ---
    WHITELIST_FILE: str
    BLACKLIST_FILE: str
    TRANSACTION_CSV_PATH: str
    PRICE_HISTORY_PATH: str
    ENCRYPTION_KEY_PATH: str

    # --- API Endpoints ---
    JUPITER_API_ENDPOINT: str
    SOLANA_MAINNET_RPC: str
    SOLANA_TESTNET_RPC: str
    SOLANA_RPC_URL: Optional[str] = None # Derived from HELIUS_RPC_URL or specific SOLANA_MAINNET/TESTNET_RPC
    HELIUS_RPC_URL: str
    HELIUS_WSS_URL: str  # This now stores the base URL without the API key
    SOLANA_MAINNET_WSS: str  # Added WebSocket endpoint for Solana mainnet
    SOLANA_TESTNET_WSS: str # ADDED WebSocket endpoint for Solana testnet
    RAYDIUM_API_URL: str  # Use RAYDIUM_API_URL instead of RAYDIUM_API_BASE_URL
    BIRDEYE_API_URL: str
    DEXSCREENER_API_URL: str
    DEXSCREENER_API_LATEST: str
    DEXSCREENER_API_DETAILS: str
    RUGCHECK_API_URL: str
    SOLANATRACKER_API_URL: str
    SOLSNIFFER_API_URL: str
    SOL_PRICE_API: str
    SOL_PRICE_API_BACKUP: str

    # --- Solana Config ---
    SOLANA_CLUSTER: str
    SOLANA_COMMITMENT: str = "confirmed" # Defaulting, confirm if this should be from env
    SOL_MINT: str = "So11111111111111111111111111111111111111112" # Added SOL mint address
    SOLANA_WSS_URL: Optional[str] = None # Derived from HELIUS_WSS_URL or specific SOLANA_MAINNET/TESTNET_WSS

    # --- API Keys ---
    HELIUS_API_KEY: Optional[SecretStr] = None
    SOLSNIFFER_API_KEY: Optional[str] = None
    TWITTER_API_KEY: Optional[str] = None # Optional if not always needed
    TWITTER_API_KEY_SECRET: Optional[str] = None # Optional
    TWITTER_USER: Optional[str] = None # Optional: For credential-based login fallback (stores username)
    TWITTER_EMAIL: Optional[str] = None    # Optional: For credential-based login fallback
    TWITTER_PASSWORD: Optional[SecretStr] = None # Optional: For credential-based login fallback
    BONDING_CURVE_INITIAL_REAL_RESERVES: Optional[float] = None # For pump.fun style tokens
    
    # --- Filter-specific Settings (using correct env variable names) ---
    MIN_LIQUIDITY_THRESHOLD: float = Field(alias='MIN_LIQUIDITY')  # Alias to existing MIN_LIQUIDITY
    MIN_PRICE_CHANGE_24H: float = Field(alias='MIN_PRICE_CHANGE_5M')  # Alias to existing MIN_PRICE_CHANGE_5M for now
    MIN_VOLUME_CHANGE_24H: float = Field(alias='MIN_PRICE_CHANGE_5M')  # Use same as price change for now - no separate volume change threshold in env
    SOLANATRACKER_API_KEY: Optional[str] = None # Optional
    ALCHEMY_API_KEY: Optional[SecretStr] = None
    # RUGCHECK_API_KEY: SecretStr # REMOVED - Not used by RugcheckAPI class

    # --- DEX Configuration ---
    # Loaded via validators below
    MONITORED_PROGRAMS: str
    DEX_PROGRAM_IDS_STR: str = Field(alias='DEX_PROGRAM_IDS')
    PUMPFUN_PROGRAM_ID: str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"  # Correct ID for pump.fun
    PUMPSWAP_PROGRAM_ID: str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"  # Correct ID for PumpSwap AMM
    RAYDIUM_V4_PROGRAM_ID: str = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8" # This is the Raydium V4 AMM Program ID
    RAYDIUM_CLMM_PROGRAM_ID: str = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK" # This is the Raydium CLMM Program ID

    # --- Filter Enablement Flags ---
    FILTER_LIQUIDITY_ENABLED: bool = False
    FILTER_VOLUME_ENABLED: bool = False
    FILTER_RUGCHECK_ENABLED: bool = False
    FILTER_SOLSNIFFER_ENABLED: bool = False
    FILTER_SOCIAL_ENABLED: bool = False
    FILTER_SCAM_ENABLED: bool = False
    FILTER_DUMP_ENABLED: bool = False
    FILTER_WHALE_ENABLED: bool = False
    FILTER_MOONSHOT_ENABLED: bool = False
    FILTER_WHITELIST_ENABLED: bool = False
    FILTER_BLACKLIST_ENABLED: bool = False
    FILTER_BONDING_CURVE_ENABLED: bool = False

    # --- General Numeric Settings ---
    SOLSNIFFER_BATCH_SIZE: int
    MARKETDATA_INTERVAL: int # ADDED: Interval for MarketData loop
    PRICEMONITOR_INTERVAL: int # ADDED: Interval for PriceMonitor loop
    ERROR_RETRY_INTERVAL: int
    TOKEN_SCAN_INTERVAL: int
    HTTP_TIMEOUT: int
    MAX_PRICE_HISTORY: int
    MAX_TOKENS_PER_REQUEST: int
    DEXSCREENER_TOKEN_QTY: int
    MIN_PRICE_HISTORY_LEN: int
    MAX_PRICE_HISTORY_LEN: int
    MIN_PRICE_CHANGE_5M: float
    MAX_RUGCHECK_SCORE: float
    MAX_POSITION_SIZE_PCT: float
    POSITION_SIZE_DECIMALS: int
    STOP_LOSS_PCT: float
    TAKE_PROFIT_PCT: float
    TRAILING_STOP_PCT: float
    SLTP_CHECK_PERIOD: int
    INDICATORS_PERIOD: int
    MAX_SLIPPAGE_PCT: float # Assuming this is needed from env
    API_CONCURRENCY_LIMIT: int  # Controls concurrent API calls in filters/rugcheck_api
    TRADE_SCHEDULER_INTERVAL: int # Interval for trade execution scheduler in seconds

    # --- Token Category Thresholds - FRESH ---
    FRESH_AGE_MIN: int
    FRESH_AGE_MAX: int
    FRESH_MCAP_MAX: float
    FRESH_MCAP_MIN: float
    FRESH_LIQUIDITY_MIN: float
    FRESH_VOLUME_5M_MIN: float
    FRESH_LIQUIDITY_RATIO: float
    FRESH_MIN_HOLDERS: int
    FRESH_RSI_PERIOD: int
    FRESH_RSI_OVERBOUGHT: float
    FRESH_RSI_OVERSOLD: float
    FRESH_PRICE_MA_PERIOD: int
    FRESH_VOLUME_MA_PERIOD: int
    FRESH_STOP_LOSS_PCT: float
    FRESH_TAKE_PROFIT_PCT: float
    FRESH_TIGHT_STOP_LOSS: float
    FRESH_WIDE_STOP_LOSS: float
    FRESH_DEFAULT_TAKE_PROFIT: float
    FRESH_CONSERVATIVE_TAKE_PROFIT: float
    FRESH_AGGRESSIVE_TAKE_PROFIT: float
    FRESH_TWITTER_ACCOUNT_AGE_DAYS: int
    FRESH_TWITTER_MIN_FOLLOWERS: int

    # --- Token Category Thresholds - NEW ---
    NEW_AGE_MIN: int
    NEW_AGE_MAX: int
    NEW_MCAP_MIN: float
    NEW_MCAP_BC_MIN: float
    NEW_MCAP_BC_MAX: float
    NEW_LIQUIDITY_MIN: float
    NEW_VOLUME_5M_MIN: float
    NEW_LIQUIDITY_RATIO: float
    NEW_MIN_HOLDERS: int
    NEW_RSI_PERIOD: int
    NEW_RSI_OVERBOUGHT: float
    NEW_RSI_OVERSOLD: float
    NEW_PRICE_MA_PERIOD: int
    NEW_VOLUME_MA_PERIOD: int
    NEW_STOP_LOSS_PCT: float
    NEW_TAKE_PROFIT_PCT: float
    NEW_TIGHT_STOP_LOSS: float
    NEW_WIDE_STOP_LOSS: float
    NEW_DEFAULT_TAKE_PROFIT: float
    NEW_CONSERVATIVE_TAKE_PROFIT: float
    NEW_AGGRESSIVE_TAKE_PROFIT: float
    NEW_TWITTER_ACCOUNT_AGE_DAYS: int
    NEW_TWITTER_MIN_FOLLOWERS: int

    # --- Token Category Thresholds - OLD ---
    OLD_AGE_MIN: int
    OLD_MCAP_BC_MIN: float
    OLD_MCAP_MIN: float
    OLD_LIQUIDITY_MIN: float
    OLD_VOLUME_5M_MIN: float
    OLD_LIQUIDITY_RATIO: float
    OLD_MIN_HOLDERS: int
    OLD_RSI_PERIOD: int
    OLD_RSI_OVERBOUGHT: float
    OLD_RSI_OVERSOLD: float
    OLD_PRICE_MA_PERIOD: int
    OLD_VOLUME_MA_PERIOD: int
    OLD_STOP_LOSS_PCT: float
    OLD_TAKE_PROFIT_PCT: float
    OLD_TIGHT_STOP_LOSS: float
    OLD_WIDE_STOP_LOSS: float
    OLD_DEFAULT_TAKE_PROFIT: float
    OLD_CONSERVATIVE_TAKE_PROFIT: float
    OLD_AGGRESSIVE_TAKE_PROFIT: float
    OLD_TWITTER_ACCOUNT_AGE_DAYS: int
    OLD_TWITTER_MIN_FOLLOWERS: int

    # --- Token Category Thresholds - MIGRATED ---
    MIGRATED_AGE_MAX: int
    MIGRATED_MCAP_BC_MIN: float
    MIGRATED_MCAP_MIN: float
    MIGRATED_LIQUIDITY_MIN: float
    MIGRATED_VOLUME_5M_MIN: float
    MIGRATED_LIQUIDITY_RATIO: float
    MIGRATED_MIN_HOLDERS: int
    MIGRATED_RSI_PERIOD: int
    MIGRATED_RSI_OVERBOUGHT: float
    MIGRATED_RSI_OVERSOLD: float
    MIGRATED_PRICE_MA_PERIOD: int
    MIGRATED_VOLUME_MA_PERIOD: int
    MIGRATED_STOP_LOSS_PCT: float
    MIGRATED_TAKE_PROFIT_PCT: float
    MIGRATED_TIGHT_STOP_LOSS: float
    MIGRATED_WIDE_STOP_LOSS: float
    MIGRATED_DEFAULT_TAKE_PROFIT: float
    MIGRATED_CONSERVATIVE_TAKE_PROFIT: float
    MIGRATED_AGGRESSIVE_TAKE_PROFIT: float
    MIGRATED_TWITTER_ACCOUNT_AGE_DAYS: int
    MIGRATED_TWITTER_MIN_FOLLOWERS: int

    # --- Token Category Thresholds - FINAL ---
    FINAL_AGE_MIN: int
    FINAL_AGE_MAX: int
    FINAL_MCAP_MIN: float
    FINAL_MCAP_BC_MIN: float
    FINAL_MCAP_BC_MAX: float
    FINAL_LIQUIDITY_MIN: float
    FINAL_VOLUME_5M_MIN: float
    FINAL_LIQUIDITY_RATIO: float
    FINAL_MIN_HOLDERS: int
    FINAL_RSI_PERIOD: int
    FINAL_RSI_OVERBOUGHT: float
    FINAL_RSI_OVERSOLD: float
    FINAL_PRICE_MA_PERIOD: int
    FINAL_VOLUME_MA_PERIOD: int
    FINAL_STOP_LOSS_PCT: float
    FINAL_TAKE_PROFIT_PCT: float
    FINAL_TIGHT_STOP_LOSS: float
    FINAL_WIDE_STOP_LOSS: float
    FINAL_DEFAULT_TAKE_PROFIT: float
    FINAL_CONSERVATIVE_TAKE_PROFIT: float
    FINAL_AGGRESSIVE_TAKE_PROFIT: float
    FINAL_TWITTER_MIN_FOLLOWERS: int
    FINAL_TWITTER_ACCOUNT_AGE_DAYS: int

    # --- Circuit Breaker ---
    COMPONENT_CB_MAX_FAILURES: int
    CIRCUIT_BREAKER_RESET_MINUTES: int

    # --- Thresholds / Analytics ---
    MIN_LIQUIDITY_RATIO: float
    SUSPICIOUS_THRESHOLD: float
    WHALE_THRESHOLD: float
    MIN_PRICE: float
    MAX_PRICE: float
    # MIN_VOLUME_ENTRY: float # REMOVED - Not used
    # MIN_PRICE_CHANGE_ENTRY: float # REMOVED - Not used

    # --- Analytics Specific ? ---
    CLUSTER_COUNT: int # Check if needed

    # --- Backtesting / Simulation ---
    TRADE_SIZE: float

    # --- Risk Management ---
    RISK_PER_TRADE: float
    MIN_POSITION_SIZE_USD: float
    MAX_POSITION_SIZE_USD: float
    VOLUME_EXIT_RATIO: float # From .get() usage

    # --- Monitoring ---
    SOL_PRICE_CACHE_DURATION: int
    MONITORING_TIMEFRAMES: str # Assuming comma-separated string like others
    MONITORING_INTERVAL_SECONDS: int
    SOL_PRICE_UPDATE_INTERVAL: int  # Interval in seconds for price parser updates

    # --- Execution / Solana ---
    COMPUTE_UNIT_PRICE_MICRO_LAMPORTS: int
    COMPUTE_UNIT_LIMIT: int

    # --- Blockchain Listener Settings ---
    WS_RECONNECT_DELAY: int = 5 # Default reconnect delay in seconds
    WS_ENABLE_MULTI_CONNECTION: bool = True # Enable separate connections per program/pool if True
    WS_INITIAL_PROGRAM_IDS_FROM_DEX_NAMES: List[str] = ["raydium_v4", "raydium", "pumpswap", "pumpfun"] # DEX names to auto-subscribe programs for
    # Example: WS_INITIAL_POOL_ADDRESSES_TO_SUBSCRIBE: List[str] = ["pool_addr1", "pool_addr2"]
    WS_INITIAL_POOL_ADDRESSES_TO_SUBSCRIBE: List[str] = Field(default_factory=list)
    WS_PING_INTERVAL: int = 30 # Seconds between keepalive pings
    WS_PING_TIMEOUT: int = 60 # Seconds to wait for pong response

    # --- Token Scanner Settings ---
    POLL_INTERVAL: int = 60 # Interval in seconds for token scanner (if used)

    # --- Price Monitor Settings ---
    PRICE_POLL_INTERVAL: int = 15 # Interval in seconds for polling price data
    PRICE_HISTORY_LENGTH: int = 100 # Max number of price points to store

    # --- Paper Trading ---
    PAPER_TRADING_ENABLED: bool = Field(description="Enable paper trading mode")
    MAX_SLIPPAGE_PERCENT: float = Field(default=1.0, description="Maximum slippage percentage for trades") # e.g., 1.0 for 1%
    TRANSACTION_MAX_RETRIES: int = Field(default=3, description="Maximum number of retries for a transaction")
    TRANSACTION_RETRY_DELAY_SECONDS: float = Field(default=1.0, description="Base delay in seconds between transaction retries (can be exponential backoff)")
    PRIORITY_FEE_MICRO_LAMPORTS: int = Field(default=50000, description="Priority fee in micro-lamports per compute unit") # e.g. 50,000 for 0.00005 SOL/CU
    AUTO_SETTLE_USDC: bool = Field(default=True, description="Automatically settle USDC balance after trades if needed")

    # --- Strategy Evaluation ---
    STRATEGY_EVALUATION_INTERVAL: int = Field(default=30, description="Interval in seconds for strategy evaluation")
    DEFAULT_TRADE_AMOUNT_USD: float = Field(default=10.0, description="Default trade amount in USD")
    FRESH_TRADE_AMOUNT_USD: float = Field(default=5.0, description="Trade amount for FRESH tokens in USD")
    ESTABLISHED_TRADE_AMOUNT_USD: float = Field(default=15.0, description="Trade amount for ESTABLISHED tokens in USD")
    TRENDING_TRADE_AMOUNT_USD: float = Field(default=20.0, description="Trade amount for TRENDING tokens in USD")

    # --- Scheduler Settings ---
    SCHEDULER_INTERVAL: int = 15  # Default: 15 seconds for general scheduler
    TOKEN_SCANNER_INTERVAL: int = 240 # Default: 240 seconds (4 minutes)
    MONITORING_SERVICE_INTERVAL: int = 60 # Interval for the general monitoring service
    BALANCE_CHECK_INTERVAL: int = 300 # Interval in seconds to check wallet balance (5 minutes)
    DB_CLEANUP_INTERVAL: int = 3600 # Interval for cleaning up old DB entries (1 hour)
    TOP_TOKEN_SELECTION_INTERVAL_SECONDS: int = 300 # Interval for selecting the top token to trade (5 minutes)

    # --- Gas Manager Settings ---
    DEFAULT_GAS_FEE: float = Field(alias='DEFAULT_GAS_FEE')
    MAX_GAS_FEE: float = Field(alias='MAX_GAS_FEE')
    MIN_GAS_FEE: float = Field(alias='MIN_GAS_FEE')
    NETWORK_POLL_INTERVAL: int = Field(alias='MONITORING_INTERVAL_SECONDS')

    # --- Wallet Settings ---
    # WALLET_PRIVATE_KEY: SecretStr # REMOVED - Loaded directly via os.getenv in WalletManager

    # --- WebSocket/Blockchain Listener Configuration ---
    WEBSOCKET_DEFAULT_RECONNECT_DELAY: int
    WEBSOCKET_MAX_RECONNECT_DELAY: int
    WEBSOCKET_PING_INTERVAL: int = 20  # Interval in seconds for sending pings
    WEBSOCKET_PING_TIMEOUT: int = 20   # Timeout in seconds for ping responses
    WEBSOCKET_CONNECT_TIMEOUT: int = 10 # Timeout for initial ws connection
    WEBSOCKET_SUBSCRIPTION_TIMEOUT: int = 60 # Timeout for subscription confirmation (renamed from CONFIRMATION_TIMEOUT)
    WEBSOCKET_MAX_RETRIES_PER_ENDPOINT: int = 3
    WEBSOCKET_RETRY_DELAY_SECONDS: int = 5
    MAX_LISTEN_RETRIES: int = 10 # Max retries for the listen method's backoff
    WEBSOCKET_MAX_MESSAGE_SIZE: Optional[int] = 10 * 1024 * 1024 # Max message size in bytes (10MB)

    # --- Test/Debug Settings ---
    TEST_WEBSOCKET_ALL_FILTER_FOR_RAYDIUM: bool = Field(default=True, description="DIAGNOSTIC: Use 'all' filter for Raydium V4 in BlockchainListener instead of mentions.")

    # --- Runtime Derived/Helper Properties (not loaded from .env) ---
    _db_url_override: Optional[str] = PrivateAttr(None) # For testing or specific runtime needs

    # --- Proxy Settings ---
    USE_PROXIES: bool
    PROXY_FILE_PATH: Optional[str] = None

    # --- Feature Flags & Main Loop Control ---
    USE_BLOCKCHAIN_LISTENER: bool
    ANALYSIS_INTERVAL: int
    MAIN_LOOP_SLEEP_INTERVAL_S: float = 1.0 # Added main loop sleep interval

    # --- Swapping & Error Handling ---
    SWAP_RETRIES: int
    MAX_SWAP_TIME_SECONDS: int
    ENABLE_ADVANCED_ERROR_HANDLING: bool

    # --- Dexscreener API Settings ---

    # === Validators and Derived Properties ===

    @field_validator('LOG_LEVEL', mode='before')
    def validate_log_level(cls, value: Optional[str]) -> str:
        """Validate LOG_LEVEL."""
        if not value:
            # Pydantic BaseSettings should raise error if missing and no default,
            # but good practice to check.
            raise ValueError("LOG_LEVEL must be set in the environment.")
        valid_levels = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET']
        if value.upper() not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL '{value}'. Must be one of {valid_levels}")
        return value.upper()

    @model_validator(mode='after')
    def derive_and_validate_paths(self) -> 'Settings':
        """Derive database file path and ensure parent directory exists."""
        db_url_env = self.DATABASE_URL_ENV
        db_file_path_str = db_url_env

        # Strip prefixes
        if db_file_path_str.startswith("sqlite+aiosqlite:///"):
            db_file_path_str = db_file_path_str[20:]
        elif db_file_path_str.startswith("sqlite:///"):
            db_file_path_str = db_file_path_str[10:]
        elif db_file_path_str.startswith("file://"):
            db_file_path_str = db_file_path_str[7:]

        # Ensure absolute path
        db_file_path = Path(db_file_path_str)
        if not db_file_path.is_absolute():
            db_file_path = (BASE_DIR / db_file_path).resolve()
        else:
            db_file_path = db_file_path.resolve()

        # Ensure parent directory exists
        try:
            db_file_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create database parent directory {db_file_path.parent}: {e}")
        # Consider raising an error here if db is critical

        # Store the derived path in the private attribute
        self._database_file_path = str(db_file_path)
        logger.info(f"Derived Database File Path: {self._database_file_path}")

        # Store the Helius WebSocket base URL
        # self._helius_wss_url_base = self.HELIUS_WSS_URL # REMOVED
        # logger.debug(f"Stored Helius WebSocket base URL: {self._helius_wss_url_base}") # REMOVED

        # Perform other post-initialization logic or validation here if needed
        # e.g., ensure required API keys are present if certain features are enabled

        return self

    @property
    def DATABASE_FILE_PATH(self) -> str:
        """Returns the derived absolute database file path."""
        if self._database_file_path is None:
            # This should not happen if model_validator ran successfully after init
            logger.error("DATABASE_FILE_PATH accessed before Settings validation completed.")
            raise ValueError("Settings not fully initialized or validation failed.")
        return self._database_file_path

    @property
    def DATABASE_URL(self) -> str:
        """Returns the full SQLAlchemy DB URL using the derived absolute path."""
        # Ensure the file path is ready before constructing the URL
        _ = self.DATABASE_FILE_PATH # Access property to trigger validation check
        return f"sqlite+aiosqlite:///{self._database_file_path}"

    @property
    def DEX_PROGRAM_IDS(self) -> Dict[str, str]:
        """Returns DEX_PROGRAM_IDS_STR parsed as a dictionary."""
        program_ids = {}
        value = self.DEX_PROGRAM_IDS_STR
        if not isinstance(value, str) or not value:
            return program_ids # Return empty dict if env var is empty or not a string
        try:
            pairs = value.split(',')
            for pair in pairs:
                if ':' in pair:
                    key, val = pair.split(':', 1)
                    program_ids[key.strip()] = val.strip()
                else:
                    logger.warning(f"Malformed entry in DEX_PROGRAM_IDS string: {pair}")
            return program_ids
        except Exception as e:
            logger.error(f"Error parsing DEX_PROGRAM_IDS string '{value}' in property: {e}")
            return {} # Return empty dict on error

    @property
    def MONITORED_PROGRAMS_LIST(self) -> List[str]:
        """Returns MONITORED_PROGRAMS parsed as a list of strings."""
        value = self.MONITORED_PROGRAMS
        if not value:
            return []
        return [item.strip() for item in value.split(',') if item.strip()]
    
    def display_settings(self):
        """Displays the loaded settings, masking sensitive information."""
        logger.info("--- Current Application Settings ---")
        sensitive_keys = {'API_KEY', 'SECRET'} # Set of substrings indicating sensitive keys
        settings_dict = self.model_dump(exclude={'DATABASE_URL_ENV'}) # Exclude raw env vars

        for key, value in settings_dict.items():
            # Check if the key itself contains sensitive substrings
            is_sensitive_key = any(sub in key.upper() for sub in sensitive_keys)
            # Also check if the *original env variable name* was sensitive (for aliased fields)
            original_key_name = key
            field_info = self.model_fields.get(key)
            if field_info and field_info.alias:
                original_key_name = field_info.alias

            is_sensitive_alias = any(sub in original_key_name.upper() for sub in sensitive_keys)

            is_sensitive = is_sensitive_key or is_sensitive_alias

            display_value = '***' if is_sensitive and value else value
            logger.info(f"{key}: {display_value}")

        # Explicitly display derived/property values, masking the WSS URL
        logger.info(f"DATABASE_FILE_PATH: {self.DATABASE_FILE_PATH}")
        logger.info(f"DATABASE_URL: {self.DATABASE_URL}") # DB URL doesn't usually contain secrets
        # logger.info(f"HELIUS_WSS_URL: {self._mask_url(self.HELIUS_WSS_URL)}") # Use masking helper # REMOVED direct logging of this property as it's gone
        # SOLANA_WSS_URL will be logged if needed, or individual components can log the URL they use.
        # Helius_WSS_URL (the field from .env) will be logged like other settings.

        logger.info("--- End Application Settings ---")

    def _mask_url(self, url: str) -> str:
        """Helper to mask api-key in URLs (copied from BlockchainListener)."""
        try:
            from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            if 'api-key' in query_params:
                query_params['api-key'] = ['***'] # Mask the key

            new_query = urlencode(query_params, doseq=True)
            masked_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
            return masked_url
        except Exception as e:
            logger.warning(f"Failed to parse and mask URL for display: {e}")
            return url # Return original URL on error

    API_MAX_RETRIES: int
    MIN_VOLUME_24H: float
    MIN_VOLUME_5M: float  # Needed by VolumeFilter
    API_RETRY_DELAY: int
    MIN_LIQUIDITY: float
    MIN_SOLSNIFFER_SCORE: float
    MAX_TOP_HOLDER_PERCENTAGE: float  # Needed by WhaleFilter
    MAX_WHALE_HOLDINGS: float  # Needed by WhaleFilter  
    MAX_MARKET_CAP: float = Field(alias='MAX_PRICE')  # Alias to existing MAX_PRICE for market cap limit
    DUMP_SCORE_THRESHOLD: float  # Needed by DumpFilter
    DEV_WALLET_ACTIVITY_THRESHOLD: float  # Needed by DumpFilter
    BASE_DELAY: int
    # TWITTER_USER: str # This seems to be replaced by TWITTER_USERNAME, TWITTER_EMAIL, TWITTER_PASSWORD if used for login

    @model_validator(mode='after')
    def validate_settings(self) -> 'Settings':
        """
        Validator to check all settings together after individual validations.
        This ensures that related settings are compatible with each other.
        """
        # Validate max price history settings
        if self.MAX_PRICE_HISTORY <= 0:
            raise ValueError(f"MAX_PRICE_HISTORY must be positive: {self.MAX_PRICE_HISTORY}")
            
        # Validate min/max price history length
        if self.MIN_PRICE_HISTORY_LEN > self.MAX_PRICE_HISTORY_LEN:
            raise ValueError(f"MIN_PRICE_HISTORY_LEN ({self.MIN_PRICE_HISTORY_LEN}) cannot be greater than "
                           f"MAX_PRICE_HISTORY_LEN ({self.MAX_PRICE_HISTORY_LEN})")
            
        # Validate database path if set
        if hasattr(self, '_database_file_path') and self._database_file_path:
            Path(self._database_file_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Validate API concurrency limit
        if self.API_CONCURRENCY_LIMIT <= 0:
            logger.warning(f"API_CONCURRENCY_LIMIT must be positive, found: {self.API_CONCURRENCY_LIMIT}. Using default of 5.")
            # Don't directly assign, as we'd be overriding a non-defaulted pydantic settings value
        
        # Ensure scan intervals are reasonable
        if self.TOKEN_SCAN_INTERVAL < 60:  # Less than 1 minute
            logger.warning(f"TOKEN_SCAN_INTERVAL is very low: {self.TOKEN_SCAN_INTERVAL}s. This may cause API rate limiting.")
            
        return self

    @field_validator('HELIUS_WSS_URL', 'SOLANA_MAINNET_WSS')
    def validate_websocket_urls(cls, v: str, info: ValidationInfo) -> str:
        """Validates that WebSocket URLs start with 'wss://'"""
        if not v.startswith('wss://'):
            field_name = info.field_name
            logger.warning(f"{field_name} should start with 'wss://'. Got: {v}")
            # Consider fixing the URL by prepending 'wss://' if it's missing but not empty
            if v and not v.startswith(('http://', 'https://')):
                logger.warning(f"Attempting to fix {field_name} by prepending 'wss://'")
                return f"wss://{v}"
            elif v.startswith(('http://', 'https://')):
                logger.warning(f"Converting {field_name} from HTTP(S) to WSS")
                return v.replace('http://', 'wss://').replace('https://', 'wss://')
        return v

    @model_validator(mode='after')
    def derive_solana_urls(cls, values: 'Settings') -> 'Settings':
        # Ensure HELIUS_API_KEY is treated as optional and check its value safely
        helius_api_key_value = values.HELIUS_API_KEY.get_secret_value() if values.HELIUS_API_KEY else None

        # Derive SOLANA_RPC_URL
        if helius_api_key_value and values.HELIUS_RPC_URL:
            if "?api-key=" not in values.HELIUS_RPC_URL and not values.HELIUS_RPC_URL.endswith(helius_api_key_value):
                values.SOLANA_RPC_URL = f"{values.HELIUS_RPC_URL}?api-key={helius_api_key_value}"
            else:  # If full URL already, or if API key is somehow already in the base
                values.SOLANA_RPC_URL = values.HELIUS_RPC_URL
            logger.info(f"Derived SOLANA_RPC_URL using Helius settings: {values.SOLANA_RPC_URL}")
        
        if not values.SOLANA_RPC_URL: # Fallback if not derived from Helius
            if values.SOLANA_CLUSTER == "mainnet-beta" or values.SOLANA_CLUSTER == "mainnet":
                values.SOLANA_RPC_URL = values.SOLANA_MAINNET_RPC
            elif values.SOLANA_CLUSTER == "testnet":
                values.SOLANA_RPC_URL = values.SOLANA_TESTNET_RPC
            logger.info(f"Derived SOLANA_RPC_URL using cluster settings: {values.SOLANA_RPC_URL} (Cluster: {values.SOLANA_CLUSTER})")

        if not values.SOLANA_RPC_URL:
            logger.error("CRITICAL: SOLANA_RPC_URL could not be determined. Application might not function.")
            # raise ValueError("SOLANA_RPC_URL could not be determined.")


        # Derive SOLANA_WSS_URL
        # values.HELIUS_WSS_URL now directly contains the value from .env
        if values.HELIUS_WSS_URL:
            if helius_api_key_value and "?api-key=" not in values.HELIUS_WSS_URL and not values.HELIUS_WSS_URL.endswith(helius_api_key_value):
                # HELIUS_WSS_URL (from env) is a base URL, and we have a key, so append it
                values.SOLANA_WSS_URL = f"{values.HELIUS_WSS_URL}?api-key={helius_api_key_value}"
            else:
                # HELIUS_WSS_URL (from env) is already a full URL (e.g. includes key) or no Helius key to append, use as is
                values.SOLANA_WSS_URL = values.HELIUS_WSS_URL
            logger.info(f"Derived SOLANA_WSS_URL using Helius settings: {values.SOLANA_WSS_URL}")

        if not values.SOLANA_WSS_URL: # Fallback if not derived from Helius
            if values.SOLANA_CLUSTER == "mainnet-beta" or values.SOLANA_CLUSTER == "mainnet":
                values.SOLANA_WSS_URL = values.SOLANA_MAINNET_WSS
            elif values.SOLANA_CLUSTER == "testnet":
                values.SOLANA_WSS_URL = values.SOLANA_TESTNET_WSS
            logger.info(f"Derived SOLANA_WSS_URL using cluster settings: {values.SOLANA_WSS_URL} (Cluster: {values.SOLANA_CLUSTER})")
        
        if not values.SOLANA_WSS_URL:
            logger.warning("SOLANA_WSS_URL could not be determined. Real-time features via BlockchainListener might be affected.")
            # Depending on criticality, could raise ValueError here.
            # raise ValueError("SOLANA_WSS_URL could not be determined.")
            
        return values

    class Config:
        env_file = BASE_DIR / 'config' / '.env' # Use Path object for robustness
        env_file_encoding = 'utf-8'
        extra = 'ignore' # Ignore extra fields from .env not defined in the model
        # case_sensitive = False # Uncomment if your .env uses lowercase keys

# Optional: Create a single instance for easy import elsewhere.
# Ensure this happens *after* the class definition.
# settings = Settings()
# logger.info("Settings instance created and validated.")