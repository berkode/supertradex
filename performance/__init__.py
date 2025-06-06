"""
Synthron Crypto Trader - Performance Package

This package includes tools for analyzing and optimizing trading performance:
1. Backtesting: Simulate and evaluate trading strategies using historical data.
2. Reporting: Generate performance reports, visualizations, and logs.
3. Metrics: Calculate key performance indicators (KPIs) like ROI, Sharpe Ratio, and drawdown.
4. DrawdownTracker: Monitor and manage account drawdowns in real-time.
5. SystemMonitor: Real-time system performance monitoring and health tracking.
6. Decorators: Performance monitoring decorators for trading operations.

"""

# Import all classes from the performance package
from .backtesting import Backtesting
from .reporting import Reporting
from .metrics import Metrics
from .drawdown_tracker import DrawdownTracker
from .system_monitor import SystemMonitor, get_system_monitor, initialize_system_monitor
from .decorators import (
    SystemMonitoringMixin, performance_timer, async_performance_timer,
    monitor_trade_execution, monitor_strategy_evaluation, monitor_price_operation,
    record_trade_success, record_trade_failure, record_strategy_decision,
    record_portfolio_update
)
import logging


# Public API for the performance package
__all__ = [
    "Backtesting",
    "Reporting", 
    "Metrics",
    "DrawdownTracker",
    "SystemMonitor",
    "get_system_monitor",
    "initialize_system_monitor",
    "SystemMonitoringMixin",
    "performance_timer",
    "async_performance_timer",
    "monitor_trade_execution",
    "monitor_strategy_evaluation",
    "monitor_price_operation",
    "record_trade_success",
    "record_trade_failure",
    "record_strategy_decision",
    "record_portfolio_update",
]

# Initialize logging for the performance package
logging.basicConfig(
    filename="performance_package.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.info("Performance package initialized successfully.")
