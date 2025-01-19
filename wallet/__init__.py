import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

# Configure logging
log_file = os.getenv("LOG_FILE", "wallet.log")
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler() if os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true" else None
    ]
)

# Ensure critical environment variables are set
REQUIRED_ENV_VARS = [
    "SOLANA_RPC_URL",
    "WALLET_ADDRESS",
    "DEX_SCREENER_API_BASE_URL",
    "SOL_PRICE_API"
]

missing_env_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_env_vars:
    logging.critical(f"Missing required environment variables: {', '.join(missing_env_vars)}")
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_env_vars)}")

logging.info("All required environment variables are set.")

# Wallet package imports
try:
    from .balance_checker import BalanceChecker
    from .gas_reserver import GasReserver
    from .gas_manager import GasManager
    from .trade_validator import TradeValidator
    from .wallet_manager import WalletManager
except ImportError as e:
    logging.critical(f"Failed to import wallet package modules: {e}")
    raise ImportError(f"Failed to import wallet package modules: {e}")

# Initialize shared resources or utilities if needed
__all__ = [
    "BalanceChecker",
    "GasReserver",
    "GasManager",
    "TradeValidator",
    "WalletManager"
]

logging.info("Wallet package initialized successfully.")
