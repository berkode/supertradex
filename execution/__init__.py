import os
import logging
import asyncio # Import asyncio for async operations
from solana.rpc.async_api import AsyncClient # Import AsyncClient
import httpx # Import httpx for shared client
from typing import Optional, Any, TYPE_CHECKING

# Import the TokenDatabase class and configuration
from data.token_database import TokenDatabase # Keep for type hinting
from config import Settings, SolanaConfig # Assuming Settings holds DB path and SolanaConfig holds RPC
# Import WalletManager for type hinting
from wallet.wallet_manager import WalletManager
# Import BalanceChecker and TradeValidator
from wallet.balance_checker import BalanceChecker
from wallet.trade_validator import TradeValidator

# Import execution components in dependency order
from .trade_queue import TradeQueue, TradeRequest, TradePriority
from .transaction_tracker import TransactionTracker
from .order_manager import OrderManager
from .arb_executor import ArbExecutor
from .dump_checker import DumpChecker
from .slippage_checker import SlippageChecker
from .trade_scheduler import TradeScheduler
from .trade_executor import TradeExecutor # Added import

# Set up centralized logging for the execution package
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("execution.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("Execution")

# Define the public API for the execution package
__all__ = [
    # Classes
    "OrderManager",
    "ArbExecutor",
    "DumpChecker",
    "SlippageChecker",
    "TradeScheduler",
    "TransactionTracker",
    "BalanceChecker",
    "TradeValidator",
    "TradeQueue",
    "TradeRequest",
    "TradePriority",
    "TradeExecutor", # Added class to __all__
    # Initialized Instances (for access from main.py or elsewhere)
    "solana_client",
    "http_client",
    "order_manager",
    "transaction_tracker",
    "balance_checker",
    "trade_validator",
    "entry_exit_strategy",
    "trade_queue",
    # Functions
    "initialize_execution_modules",
    "close_execution_resources",
]

# Centralized initialization of execution modules and shared resources
settings: Optional[Settings] = None
solana_config: Optional[SolanaConfig] = None
rpc_endpoint: Optional[str] = None
solana_client: Optional[AsyncClient] = None # Shared Solana Client
http_client: Optional[httpx.AsyncClient] = None # Shared HTTP Client
# db: Optional[TokenDatabase] = None
# Execution components
order_manager: Optional[OrderManager] = None
arb_executor: Optional[ArbExecutor] = None
dump_checker: Optional[DumpChecker] = None
slippage_checker: Optional[SlippageChecker] = None
trade_scheduler: Optional[TradeScheduler] = None
transaction_tracker: Optional[TransactionTracker] = None
# Wallet utility components (initialized here)
balance_checker: Optional[BalanceChecker] = None
trade_validator: Optional[TradeValidator] = None
# Strategy components (initialized here)
entry_exit_strategy: Optional["EntryExitStrategy"] = None # Using string for forward reference
trade_queue: Optional[TradeQueue] = None

# Use a flag to prevent re-initialization if this module is imported multiple times
_initialized = False

if TYPE_CHECKING:
    from strategies.entry_exit import EntryExitStrategy # For type hinting global var

async def initialize_execution_modules(
    wallet_manager_instance: WalletManager,
    db_instance: TokenDatabase,
    settings: Optional[Settings] = None,
    data_package: Optional[Any] = None,
    filters: Optional[Any] = None
):
    """Initialize all execution modules and shared resources.
    
    Args:
        wallet_manager_instance: An initialized WalletManager instance.
        db_instance: An initialized TokenDatabase instance.
        settings: Optional Settings instance. If not provided, a new one will be created.
        data_package: Optional data package instance containing indicators and price monitor.
        filters: Optional filters package instance containing whitelist and blacklist.
    """
    from strategies.entry_exit import EntryExitStrategy # ACTUAL IMPORT FOR USE
    global _initialized, solana_client, http_client, order_manager, transaction_tracker, trade_queue, entry_exit_strategy, balance_checker, trade_validator
    
    if _initialized:
        logger.debug("Execution modules already initialized.")
        return
    
    # Validate required db_instance
    if not db_instance:
         raise ValueError("A valid TokenDatabase instance is required.")
         
    wallet_pubkey = wallet_manager_instance.get_public_key()
    if not wallet_manager_instance or not wallet_pubkey:
        raise ValueError("Valid WalletManager instance with a public key is required.")

    logger.info("Initializing Execution Modules...")
    try:
        # Load settings if not provided
        if settings is None:
            settings = Settings()
        solana_config = SolanaConfig()
        rpc_endpoint = solana_config.get_rpc_endpoint()

        # Instantiate Shared Solana Client
        if not rpc_endpoint:
            raise ValueError("Solana RPC endpoint not configured.")
        solana_client = AsyncClient(rpc_endpoint)
        logger.info(f"Shared Solana AsyncClient created for endpoint: {rpc_endpoint}")
        
        # Instantiate Shared HTTP Client
        http_client = httpx.AsyncClient()
        logger.info("Shared httpx AsyncClient created.")

        # Initialize Wallet Utility Components
        balance_checker = BalanceChecker(
            solana_client=solana_client,
            wallet_pubkey=wallet_pubkey,
            http_client=http_client, # Pass shared client
            settings=settings
        )
        logger.info("BalanceChecker initialized.")
        
        trade_validator = TradeValidator(
            balance_checker=balance_checker, # Pass balance_checker
            settings=settings # Pass settings
        )
        logger.info("TradeValidator initialized.")

        # Initialize Execution Components needing shared resources and the passed DB
        order_manager = OrderManager(
            solana_client=solana_client,
            http_client=http_client, 
            settings=settings,
            db=db_instance, # Use passed db_instance
            wallet_manager=wallet_manager_instance,
            trade_validator=trade_validator 
        )
        logger.info("OrderManager initialized.")
        
        # Instantiate TradeQueue
        trade_queue = TradeQueue(order_manager=order_manager)
        logger.info("TradeQueue initialized.")

        transaction_tracker = TransactionTracker(solana_client=solana_client, db=db_instance) # Use passed db_instance
        logger.info("TransactionTracker initialized.")

        # Initialize Strategy Components
        entry_exit_strategy = EntryExitStrategy(
            settings=settings,
            db=db_instance, # Use passed db_instance
            indicators=data_package.indicators if data_package else None,
            price_monitor=data_package.price_monitor if data_package else None,
            trade_queue=trade_queue,
            whitelist=filters.whitelist if filters else None,
            blacklist=filters.blacklist if filters else None,
            thresholds=data_package.token_scanner.thresholds if data_package else None,
            wallet_manager=wallet_manager_instance
        )
        
        logger.info("EntryExitStrategy instance created. Preparing to initialize.")

        # --- BEGIN ADDED LOGGING ---
        logger.debug(f"Passing to EntryExitStrategy.initialize:")
        logger.debug(f"  order_manager: {order_manager} (type: {type(order_manager)})")
        logger.debug(f"  transaction_tracker: {transaction_tracker} (type: {type(transaction_tracker)})")
        logger.debug(f"  balance_checker: {balance_checker} (type: {type(balance_checker)})")
        logger.debug(f"  trade_validator: {trade_validator} (type: {type(trade_validator)})")
        # --- END ADDED LOGGING ---

        # Initialize the strategy with order_manager and transaction_tracker
        if not await entry_exit_strategy.initialize(
            order_manager=order_manager,
            transaction_tracker=transaction_tracker,
            balance_checker=balance_checker,
            trade_validator=trade_validator
        ):
            logger.error("Failed to initialize EntryExitStrategy")
            return False # Changed to return False on failure
            
        logger.info("EntryExitStrategy initialized.")
        
        # Pass transaction_tracker to OrderManager
        if order_manager and transaction_tracker:
            order_manager.set_transaction_tracker(transaction_tracker)
            logger.info("TransactionTracker instance passed to OrderManager.")
            
        # Initialize other components (update if they need shared resources)
        arb_executor = ArbExecutor(
            solana_client=solana_client,
            http_client=http_client,
            settings=settings,
            wallet_manager=wallet_manager_instance
        )
        dump_checker = DumpChecker(
            http_client=http_client,
            settings=settings
        )
        slippage_checker = SlippageChecker(
            http_client=http_client,
            settings=settings
        )
        trade_scheduler = TradeScheduler(
            order_manager=order_manager,
            settings=settings
        )
        
        # Mark as initialized
        _initialized = True
        logger.info("All execution modules initialized successfully.")
        return True # Explicitly return True on success
        
    except Exception as e:
        logger.error(f"Error initializing execution modules: {e}", exc_info=True)
        # Clean up any resources that were created
        await close_execution_resources()
        return False

async def close_execution_resources():
    """Closes shared resources like the Solana and HTTP clients."""
    global solana_client, http_client, _initialized
    # Close OrderManager's *internal* client first if it differs from shared
    # (In current design, OrderManager uses the shared one, so no need here)
    
    if http_client:
        logger.info("Closing shared httpx AsyncClient...")
        await http_client.aclose()
        http_client = None
        
    if solana_client:
        logger.info("Closing shared Solana AsyncClient...")
        await solana_client.close()
        solana_client = None
        
    # REMOVE check for removed global 'db'
    # if db:
    #     # Add DB closing logic if necessary
    #     # await db.close()
    #     logger.info("Closing DB connection (placeholder)...") # Add actual close if needed
    #     pass
        
    _initialized = False
    logger.info("Execution resources closed.")

# Note: Initialization should be triggered by calling initialize_execution_modules()
# from an async context (e.g., in main.py).
