import logging
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Configure package-level logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("Config")

# Import all configuration modules to make them accessible from the package
from .raydium_api import RaydiumAPIConfig
from .dexscreener_api import DexScreenerAPIConfig
from .solana_config import SolanaConfig
from .logging_config import LoggingConfig
from .thresholds import Thresholds
from .settings import Settings
from .filters_config import FiltersConfig

# Initialize logging configuration
LoggingConfig.setup_logging()

# Validate and log all configurations
try:
    logger.info("Initializing and validating configurations...")

    # Validate individual configurations
    RaydiumAPIConfig.validate_config()
    DexScreenerAPIConfig.validate_config()
    SolanaConfig.validate_config()
    Thresholds.validate_thresholds()
    Settings.validate_settings()
    FiltersConfig()  # Load and validate filter criteria on initialization

    # Display configurations for debugging
    logger.info("Configuration validation successful.")
    RaydiumAPIConfig.display_config()
    DexScreenerAPIConfig.display_config()
    SolanaConfig.display_config()
    Thresholds.display_thresholds()
    Settings.display_settings()

    # Display filter criteria
    filters = FiltersConfig()
    logger.info("Filter Criteria:")
    for key, value in filters.criteria.items():
        logger.info(f"{key}: {value}")

except Exception as e:
    logger.error(f"Configuration initialization error: {e}")
    raise
