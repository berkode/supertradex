import os
import logging
from logging import getLogger
from pathlib import Path
import sys

# Ensure the project root is in the Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Configure package-level logging
logging.basicConfig(level=logging.INFO)
logger = getLogger('Config')

# Import needed for base setup, keep minimal
from .logging_config import LoggingConfig 

# Import main configuration classes to make them available via 'config' package
from .settings import Settings, EncryptionSettings, BASE_DIR, outputs_dir
from .solana_config import SolanaConfig
from .dexscreener_api import DexScreenerAPI 
from .thresholds import Thresholds
from .filters_config import FiltersConfig

# Config manager not available - removed imports
# Import other config classes as needed...
# from .twitter_config import TwitterConfig
# from .raydium_api import RaydiumAPI

# Remove premature Settings instantiation
# settings = Settings()

logger = logging.getLogger(__name__)
logger.info("Configuration package initialized (imports only).")

# Function to initialize all config objects (kept commented out - handled in main.py)
# def initialize_config(settings: Settings) -> None:
#     """Initializes all necessary configurations."""
#     logger.info("Initializing and validating configurations...")
#     try:
#         # Create instances here if needed, passing settings
#         SolanaConfig(settings)
#         FiltersConfig(settings)
#         TwitterConfig(settings)
#         # ... and so on
#         logger.info("Configurations initialized successfully.")
#     except Exception as e:
#         logger.error(f"Configuration initialization error: {e}")
#         raise

# Removed initialization block to prevent import cycles
# try:
#     logger.info("Initializing and validating configurations...")
# 
#     # Create instances
#     # solana_config = SolanaConfig()
#     # filters_config = FiltersConfig()
#     # thresholds = Thresholds()
#     # dex_screener_config = DexScreenerAPI()
#     # raydium_config = RaydiumAPI()
#     # twitter_config = TwitterConfig(settings)
# 
#     # Validate configurations using instances
#     # thresholds._validate_thresholds()
#     # solana_config.validate_config()
#     # filters_config.validate()
#     # settings.validate_settings() # Removed call to non-existent method
#     # twitter_config.validate_config()
# 
#     # Display configurations for debugging
#     logger.info("Configuration validation successful.")
#     # solana_config.display_config()
#     # thresholds.display_thresholds()
#     # settings.display_settings()
#     # twitter_config.display_config()
# 
#     # Log filter criteria
#     logger.info("Filter Criteria:")
#     # if filters_config.criteria:
#     #     for key, value in filters_config.criteria.items():
#     #         logger.info(f"  {key}: {value}")
#     # else:
#     logger.warning("No filter criteria loaded")
# 
# except Exception as e:
#     logger.error(f"Configuration initialization error: {e}")
#     raise

# Export all necessary classes and instances
__all__ = [
    'Settings',
    'EncryptionSettings',
    'SolanaConfig',
    'FiltersConfig',
    'Thresholds',
    'LoggingConfig',
    'BASE_DIR',
    'outputs_dir'
]
