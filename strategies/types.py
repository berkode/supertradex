"""
Type definitions for strategy components to avoid circular imports.
"""
from typing import TYPE_CHECKING, Optional, Dict, List, Any

if TYPE_CHECKING:
    from execution.trade_queue import TradeQueue, TradePriority
    from execution.order_manager import OrderManager
    from execution.transaction_tracker import TransactionTracker
    from execution.balance_checker import BalanceChecker
    from wallet.trade_validator import TradeValidator
    from data.market_data import MarketData
    from data.token_database import TokenDatabase
    from data.price_monitor import PriceMonitor
    from config.thresholds import Thresholds
    from wallet.wallet_manager import WalletManager 