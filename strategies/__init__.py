# __init__.py for Synthron Crypto Trader strategies package

import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StrategyPackage")

# Remove dynamic imports and __all__ list management to avoid circular dependencies
# Users should import directly from submodules, e.g.:
# from strategies.entry_exit import EntryExitStrategy
# from strategies.strategy_selector import StrategySelector

# __all__ = [] 

# # Try importing each strategy class individually
# try:
#     from .entry_exit import EntryExitStrategy
#     __all__.append("EntryExitStrategy")
#     logger.debug("Successfully imported EntryExitStrategy")
# except ImportError as e:
#     logger.warning(f"Could not import EntryExitStrategy: {e}")
#     # Define placeholder if needed, or just skip export
#     class EntryExitStrategy:
#         pass # Placeholder

# try:
#     from .strategy_selector import StrategySelector
#     __all__.append("StrategySelector")
#     logger.debug("Successfully imported StrategySelector")
# except ImportError as e:
#     logger.warning(f"Could not import StrategySelector: {e}")
#     class StrategySelector:
#         pass # Placeholder

# try:
#     from .position_management import PositionManagement
#     __all__.append("PositionManagement")
#     logger.debug("Successfully imported PositionManagement")
# except ImportError as e:
#     logger.warning(f"Could not import PositionManagement: {e}")
#     class PositionManagement:
#         pass # Placeholder

# try:
#     from .risk_management import RiskManagement
#     __all__.append("RiskManagement")
#     logger.debug("Successfully imported RiskManagement")
# except ImportError as e:
#     logger.warning(f"Could not import RiskManagement: {e}")
#     class RiskManagement:
#         pass # Placeholder

# Optional: Add version information and package description
__version__ = "1.0.0"
__description__ = "SupertradeX Trader based on Synthron Crypto Trader"

# Log package version and description
logger.info(f"{__description__} - Version: {__version__}")

# Logging the successful initialization of the strategies package
# logger.info("Strategies package initialized (submodules should be imported directly).")
# if len(__all__) == len(_strategy_classes):
#     logger.info("Strategies package loaded successfully with all core modules.")
# else:
#     logger.warning(f"Strategies package loaded, but some modules were missing: Imported {len(__all__)}/{len(_strategy_classes)} classes.")

# Custom exception for significant loading failures (optional)
class StrategyModuleError(Exception):
    """Custom exception for significant strategy loading failures"""
    pass

# Example check: Raise error if essential classes are missing
# if "EntryExitStrategy" not in __all__ or "StrategySelector" not in __all__:
#     raise StrategyModuleError("Essential strategy classes (EntryExit, Selector) failed to load.")

from .strategy_evaluator import StrategyEvaluator
from .entry_exit import EntryExitStrategy
from .strategy_selector import StrategySelector

__all__ = [
    "StrategyEvaluator",
    "EntryExitStrategy",
    "StrategySelector",
]
