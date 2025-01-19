import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configure logging
LOG_FILE = os.getenv("LOG_FILE", "data.log")
ENABLE_CONSOLE_LOGGING = os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler() if ENABLE_CONSOLE_LOGGING else None
    ]
)

# Ensure critical environment variables are set
REQUIRED_ENV_VARS = [
    "DEX_SCREENER_API_BASE_URL",
    "RAYDIUM_API_BASE_URL",
    "SUSPICIOUS_THRESHOLD",
    "WHALE_THRESHOLD",
    "CLUSTER_COUNT",
    "MIN_LIQUIDITY"
]

missing_env_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_env_vars:
    logging.critical(f"Missing required environment variables: {', '.join(missing_env_vars)}")
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_env_vars)}")

# Import all modules from the data package with enhanced error handling
MODULES = [
    "data_processing",
    "data_fetcher",
    "analytics",
    "price_monitor",
    "filtering",
    "blockchain_listener",
    "token_metrics",
    "indicators"  # Added the indicators module
]

loaded_modules = {}
for module in MODULES:
    try:
        loaded_modules[module] = __import__(f".{module}", globals(), locals(), [module], 1)
    except ImportError as e:
        logging.error(f"Error importing module '{module}': {e}")
        raise ImportError(f"Error importing module '{module}': {e}")

# Assign imported modules to specific names for easy access
DataProcessing = loaded_modules["data_processing"].DataProcessing
DataFetcher = loaded_modules["data_fetcher"].DataFetcher
Analytics = loaded_modules["analytics"].Analytics
PriceMonitor = loaded_modules["price_monitor"].PriceMonitor
Filtering = loaded_modules["filtering"].Filtering
BlockchainListener = loaded_modules["blockchain_listener"].BlockchainListener
TokenMetrics = loaded_modules["token_metrics"].TokenMetrics
Indicators = loaded_modules["indicators"].Indicators  # Added Indicators

# Log successful initialization of the package
logging.info("Data package initialized successfully. All modules imported and validated.")

# Define the public API for the package
__all__ = [
    "DataProcessing",
    "DataFetcher",
    "Analytics",
    "PriceMonitor",
    "Filtering",
    "BlockchainListener",
    "TokenMetrics",
    "Indicators"  # Added Indicators to the public API
]
