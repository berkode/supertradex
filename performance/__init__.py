"""
Synthron Crypto Trader - Performance Package

This package includes tools for analyzing and optimizing trading performance:
1. Backtesting: Simulate and evaluate trading strategies using historical data.
2. Reporting: Generate performance reports, visualizations, and logs.
3. Metrics: Calculate key performance indicators (KPIs) like ROI, Sharpe Ratio, and drawdown.
4. DrawdownTracker: Monitor and manage account drawdowns in real-time.

"""

# Import all classes from the performance package
from .backtesting import Backtesting
from .reporting import Reporting
from .metrics import Metrics
from .drawdown_tracker import DrawdownTracker
import logging


# Public API for the performance package
__all__ = [
    "Backtesting",
    "Reporting",
    "Metrics",
    "DrawdownTracker",
]

# Initialize logging for the performance package
logging.basicConfig(
    filename="performance_package.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.info("Performance package initialized successfully.")
