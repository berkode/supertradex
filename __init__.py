"""
Synthron Crypto Trader Initialization Module
By Magna Opus Technologies
"""

import os
import logging
from dotenv import load_dotenv
from config import (
    Settings,
    LoggingConfig,
    SolanaConfig,
    FiltersConfig,
    Thresholds,
    DexScreenerAPIConfig,
    RaydiumAPIConfig,
)
from utils.logger import get_logger

# Load environment variables from .env file
load_dotenv()

# Global logger setup
logger = get_logger("SynthronCryptoTrader")

# Package Metadata
__version__ = "1.0.0"
__author__ = "Magna Opus Technologies"
__email__ = "support@magnaopustechnologies.com"
__license__ = "MIT"
__status__ = "Production"

# Constants for Configuration Validation
REQUIRED_ENV_VARS = [
    "SOLANA_RPC_ENDPOINT",
    "RAYDIUM_API_KEY",
    "DEXSCREENER_API_URL",
    "TRADING_PAIR",
    "PRIVATE_KEY_PATH",
]

def validate_environment_variables():
    """Ensure all required environment variables are set."""
    logger.info("Validating environment variables...")
    missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing_vars:
        error_message = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_message)
        raise EnvironmentError(error_message)
    logger.info("All required environment variables are set.")

def initialize_configurations():
    """Load and validate configurations."""
    logger.info("Initializing configurations...")
    try:
        # Load configurations
        settings = Settings()
        solana_config = SolanaConfig()
        filters_config = FiltersConfig()
        thresholds = Thresholds()
        dex_screener_config = DexScreenerAPIConfig()
        raydium_config = RaydiumAPIConfig()
        LoggingConfig()  # Apply logging configuration globally

        # Log configuration details (sanitized where necessary)
        logger.debug(f"Settings: {settings}")
        logger.debug(f"SolanaConfig: {solana_config}")
        logger.debug(f"FiltersConfig: {filters_config}")
        logger.debug(f"Thresholds: {thresholds}")
        logger.info("Configurations initialized successfully.")
        return {
            "settings": settings,
            "solana_config": solana_config,
            "filters_config": filters_config,
            "thresholds": thresholds,
            "dex_screener_config": dex_screener_config,
            "raydium_config": raydium_config,
        }
    except Exception as e:
        logger.error(f"Failed to initialize configurations: {e}")
        raise

def initialize_package():
    """Initialize the Synthron Crypto Trader package."""
    logger.info("Initializing Synthron Crypto Trader package...")
    try:
        # Validate environment variables
        validate_environment_variables()

        # Initialize configurations
        configs = initialize_configurations()

        logger.info("Package initialized successfully.")
        return configs
    except Exception as e:
        logger.critical(f"Package initialization failed: {e}")
        raise

# Initialize the package when the module is imported
try:
    CONFIGS = initialize_package()
except Exception as e:
    logger.critical("Failed to initialize the package. Exiting...")
    raise SystemExit(e)
