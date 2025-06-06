"""
Wallet package initialization.
All wallet-related functionality should be imported through this module.
"""
from config.settings import Settings

# Import wallet components
from .wallet_manager import WalletManager
from .trading_manager import TradingManager
from .gas_reserver import GasReserver

__all__ = ['WalletManager', 'TradingManager', 'GasReserver']
