# __init__.py for Synthron Crypto Trader strategies package

import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StrategyPackage")

# Import all the strategy classes
try:
    from .entry_exit_strategy import EntryExitStrategy
    from .position_management import PositionManagement
    from .risk_management import RiskManagement
    from .strategy_selector import StrategySelector
    from .trade_execution import TradeExecution
    from .trade_validator import TradeValidator
    from .trade_manager import TradeManager
    from .performance_metrics import PerformanceMetrics
    from .order_management import OrderManagement
except ImportError as e:
    logger.error(f"Error importing strategy modules: {e}")
    raise ImportError("Failed to import all necessary strategy classes.")

# Exporting the classes for easy access and structured organization
__all__ = [
    "EntryExitStrategy",
    "PositionManagement",
    "RiskManagement",
    "StrategySelector",
    "TradeExecution",
    "TradeValidator",
    "TradeManager",
    "PerformanceMetrics",
    "OrderManagement",
]

# Optional: Add version information and package description
__version__ = "1.0.0"
__description__ = "Synthron Crypto Trader - Comprehensive Trading Strategies Package"

# Log package version and description
logger.info(f"{__description__} - Version: {__version__}")

# Logging the successful initialization of the strategies package
logger.info("Strategies package loaded successfully with all modules.")

# You can also create custom exception handling for missing strategy classes
class StrategyModuleError(Exception):
    """Custom exception for missing strategy classes"""
    pass
