import logging
from .order_manager import OrderManager
from .arb_executor import ArbExecutor
from .rug_checker import RugChecker
from .slippage_checker import SlippageChecker
from .trade_scheduler import TradeScheduler
from .transaction_tracker import TransactionTracker

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
    "OrderManager",
    "ArbExecutor",
    "RugChecker",
    "SlippageChecker",
    "TradeScheduler",
    "TransactionTracker"
]

# Centralized initialization of execution modules
try:
    logger.info("Initializing Execution Modules...")

    # Initialize all components
    order_manager = OrderManager()
    arb_executor = ArbExecutor()
    rug_checker = RugChecker()
    slippage_checker = SlippageChecker()
    trade_scheduler = TradeScheduler()
    transaction_tracker = TransactionTracker()

    logger.info("Execution Modules Initialized Successfully.")
except Exception as e:
    logger.error("Error initializing execution modules: %s", str(e))
    raise
