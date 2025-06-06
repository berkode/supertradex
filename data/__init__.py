"""
Data package for token scanning and processing.
"""

import logging
import inspect
from typing import Optional, Any, Dict, Type, Callable, Awaitable, Union
from flask import Flask
import os
import sqlite3
import getpass
from sqlalchemy import create_engine
import asyncio  # Ensure asyncio is imported if needed for close_all

# Import Settings related items needed for explicit path
from config.settings import Settings, outputs_dir
# ADD import for Thresholds
from config.thresholds import Thresholds

# --- MOVED IMPORTS START ---
from .token_database import TokenDatabase
from .token_scanner import TokenScanner
from .price_monitor import PriceMonitor
from .indicators import Indicators
from .blockchain_listener import BlockchainListener
from .platform_tracker import PlatformTracker
from .token_metrics import TokenMetrics
from .data_fetcher import DataFetcher
from .analytics import Analytics
from .monitoring import Monitoring
from .delta_calculator import DeltaCalculator
# Ensure DataProcessor is exported
from .data_processing import DataProcessing
# Parser imports (moved from parsers subdirectory)
from .base_parser import DexParser
from .raydium_v4_parser import RaydiumV4Parser
from .pumpswap_parser import PumpSwapParser
from .raydium_clmm_parser import RaydiumClmmParser
# Price parser imports (new REST API parsers)
from .raydium_price_parser import RaydiumPriceParser
from .jupiter_price_parser import JupiterPriceParser
# --- MOVED IMPORTS END ---

# Import base classes/types for components if needed for hints
# from data.token_database import TokenDatabase # Example
# from data.price_monitor import PriceMonitor # Example
# from solana.rpc.async_api import AsyncClient # Example
# import httpx # Example

logger = logging.getLogger(__name__)

class DataPackage:
    """Main class for managing all data-related components."""
    
    def __init__(self, settings: Settings):
        self.settings = settings  # Store settings
        # Initialize internal component attributes to None
        self.token_database = None
        self.token_scanner = None
        self.blockchain_listener = None
        self.token_metrics = None
        self.data_fetcher = None
        self.analytics = None
        self.monitoring = None
        self.delta_calculator = None
        self.proxy_manager = None
        
        # Attributes to store externally initialized components
        self.http_client = None
        self.solana_client = None
        self.dex_api_client = None
        self.thresholds = None
        self.filter_manager = None
        self.indicators = None
        self.whitelist = None
        self.volume_monitor = None
        self.platform_tracker = None
        self.rugcheck_api = None
        self.solsniffer_api = None
        self.solana_tracker_api = None
        self.price_monitor = None
        self.twitter_check = None
        self.market_data = None
        self.balance_checker = None
        self.trade_validator = None
        self.wallet_manager = None
        self.strategy_selector = None

    async def initialize(self, **kwargs):
        """Initialize data components defined *within* the data package."""
        logger.info("Initializing DataPackage internal components...")

        # Store ALL passed-in external components/clients onto self
        self.http_client = kwargs.get('http_client', self.http_client)
        self.solana_client = kwargs.get('solana_client', self.solana_client)
        self.dex_api_client = kwargs.get('dex_api_client', self.dex_api_client)
        self.db = kwargs.get('db', self.token_database) # Use 'db' kwarg if passed
        self.thresholds = kwargs.get('thresholds', self.thresholds)
        self.filter_manager = kwargs.get('filter_manager', self.filter_manager)
        self.indicators = kwargs.get('indicators', self.indicators)
        self.whitelist = kwargs.get('whitelist', self.whitelist)
        self.volume_monitor = kwargs.get('volume_monitor', self.volume_monitor)
        self.platform_tracker = kwargs.get('platform_tracker', self.platform_tracker)
        self.rugcheck_api = kwargs.get('rugcheck_api', self.rugcheck_api)
        self.solsniffer_api = kwargs.get('solsniffer_api', self.solsniffer_api)
        self.solana_tracker_api = kwargs.get('solana_tracker_api', self.solana_tracker_api)
        self.price_monitor = kwargs.get('price_monitor', self.price_monitor)
        self.twitter_check = kwargs.get('twitter_check', self.twitter_check)
        self.market_data = kwargs.get('market_data', self.market_data)
        self.balance_checker = kwargs.get('balance_checker', self.balance_checker)
        self.trade_validator = kwargs.get('trade_validator', self.trade_validator)
        self.wallet_manager = kwargs.get('wallet_manager', self.wallet_manager)
        self.strategy_selector = kwargs.get('strategy_selector', self.strategy_selector)

        # Ensure self.token_database is also set if 'db' was passed
        if self.db and not self.token_database:
            self.token_database = self.db
            logger.debug("Set self.token_database from passed 'db' kwarg.")

        # Define the order of INTERNAL component initialization
        # Ensure Monitoring is initialized before TokenMetrics
        component_order = [
            # 'ProxyManager',      # Assuming external now
            'TokenDatabase',     # Fundamental, initialize first if managed internally
            'BlockchainListener', # Needs settings, db
            'DataFetcher',       # Needs settings, http_client, db
            'Analytics',         # Needs settings, thresholds, db, price_monitor, solana_client
            'Monitoring',        # Needs settings, db, price_monitor, solana_client, thresholds, filter_manager
            #'TokenScanner',      # Initialize TokenMetrics first
            'TokenMetrics',      # Needs monitoring, indicators, platform_tracker, volume_monitor, etc.
            'TokenScanner',      # Needs many external deps + indicators + token_metrics
            'DeltaCalculator'    # Needs monitoring (or analytics? Check deps)
        ]

        component_classes = {
            name: globals()[name] for name in component_order if name in globals()
        }

        for name in component_order:
            if name not in component_classes:
                logger.warning(f"Component class '{name}' not found in data package globals. Skipping initialization.")
                continue

            attr_name = self._get_attribute_name(name)
            
            # --- ADDED CHECK for BlockchainListener ---
            # If market_data was passed externally, it contains the already initialized listener.
            # Do NOT attempt to create BlockchainListener internally in this case.
            if name == 'BlockchainListener' and self.market_data:
                logger.debug("BlockchainListener instance assumed to be within externally provided market_data. Skipping internal creation.")
                # Optionally, try to assign the listener from market_data to self if needed
                # if hasattr(self.market_data, 'blockchain_listener'):
                #     setattr(self, attr_name, self.market_data.blockchain_listener)
                #     logger.debug("Assigned listener from external market_data to self.blockchain_listener")
                continue # Skip to the next component in the order
            # --- END ADDED CHECK ---

            if getattr(self, attr_name, None) is None:
                # Special case: Don't re-initialize DB if it was passed in
                if name == 'TokenDatabase' and self.db:
                     logger.debug("TokenDatabase instance provided externally, skipping internal creation.")
                     setattr(self, attr_name, self.db)
                     continue # Skip to next component

                logger.debug(f"Initializing {name} internally...")
                # Pass self to create_component_instance to access all stored dependencies
                instance = self.create_component_instance(component_classes[name])
                if instance:
                    setattr(self, attr_name, instance)

                    # Special handling after instantiation (only for internally created ones)
                    if name == 'TokenDatabase' and hasattr(instance, 'initialize') and asyncio.iscoroutinefunction(instance.initialize):
                         # Only await initialize if DB was created *here*
                         await instance.initialize()
                         logger.info(f"{name} initialized successfully.")

                    # Async initialize for other internally created components
                    elif hasattr(instance, 'initialize') and asyncio.iscoroutinefunction(instance.initialize):
                        try:
                            await instance.initialize()
                            logger.info(f"{name} initialized successfully.")
                        except Exception as e:
                            logger.error(f"Error async initializing component {name}: {e}", exc_info=True)
                    # Sync initialize for internally created components
                    elif hasattr(instance, 'initialize'):
                         try:
                            instance.initialize()
                            logger.info(f"{name} initialized successfully (sync).")
                         except Exception as e:
                            logger.error(f"Error sync initializing component {name}: {e}", exc_info=True)
                    else:
                         logger.info(f"{name} instance created (no initialize method needed/found)." if instance else f"Failed to create {name} instance.")
                else:
                    logger.error(f"Failed to create instance for {name}.")
            else:
                 logger.debug(f"Component {name} already initialized (likely passed externally), skipping.")

        logger.info("DataPackage internal component initialization sequence complete.")

    def _get_attribute_name(self, class_name: str) -> str:
        """Converts CamelCase class name to snake_case attribute name."""
        return ''.join(['_' + i.lower() if i.isupper() else i for i in class_name]).lstrip('_')

    def create_component_instance(self, component_class: Type[Any]) -> Optional[Any]:
        """Creates an instance of a component, injecting dependencies from self."""
        if not hasattr(self, 'settings') or self.settings is None:
            logger.critical("CRITICAL: Cannot create component instance, self.settings is not available in DataPackage!")
            return None

        # --- ADDED CHECK: Skip internal TokenMetrics creation if provided externally ---
        if component_class is TokenMetrics and getattr(self, 'token_metrics', None) is not None:
            logger.debug("TokenMetrics instance was provided externally. Skipping internal creation attempt.")
            return getattr(self, 'token_metrics') # Return the existing one
        # --- END ADDED CHECK ---

        logger.debug(f"Attempting to create instance for {component_class.__name__}")

        # Define common dependencies accessible via self (now includes externally passed ones)
        component_args = {
            # Core
            'settings': self.settings,
            'db': self.token_database,
            'db_instance': self.token_database, # Alias for TokenScanner
            'token_db': self.token_database, # Alias for Analytics/DeltaCalculator
            'http_client': self.http_client,
            'solana_client': self.solana_client,
            'dex_api_client': self.dex_api_client,
            'dexscreener_api': self.dex_api_client, # Alias for TokenScanner
            # Config
            'thresholds': self.thresholds, # Assume Thresholds is always passed via self.thresholds
            # Managers / External Components (Use stored instances from self)
            'filter_manager': self.filter_manager,
            'price_monitor': self.price_monitor,
            'indicators': self.indicators,
            'whitelist': self.whitelist,
            'volume_monitor': self.volume_monitor,
            'platform_tracker': self.platform_tracker,
            'analytics': self.analytics, # This is initialized internally, ensure correct order
            'monitoring': self.monitoring, # This is initialized internally, ensure correct order
            'token_metrics': self.token_metrics,
            'market_data': self.market_data,
            # API Clients (Use stored instances from self)
            'rugcheck_api': self.rugcheck_api,
            'solsniffer_api': self.solsniffer_api,
            'solana_tracker_api': self.solana_tracker_api,
            'dex_api_config': self.dex_api_client, # Alias for TokenScanner compatibility
            # Other
            'twitter_check': self.twitter_check,
            'balance_checker': self.balance_checker, # Use passed BalanceChecker
            'trade_validator': self.trade_validator, # Use passed TradeValidator
            'wallet_manager': self.wallet_manager, # Use passed WalletManager
            'strategy_selector': self.strategy_selector,
            # Add other potential dependencies stored on self
        }

        # Define specific dependencies or overrides (e.g., DB path for TokenDatabase)
        specific_dependencies = {
            'TokenDatabase': {'database_url': self.settings.DATABASE_FILE_PATH},
            # No specific overrides needed for others if component_args covers them
        }

        try:
            # Get constructor parameters
            sig = inspect.signature(component_class.__init__)
            params = sig.parameters

            # Build kwargs for this specific component
            kwargs = {}
            for name, param in params.items():
                if name == 'self':
                    continue

                # Check specific dependencies first
                if component_class.__name__ in specific_dependencies and name in specific_dependencies[component_class.__name__]:
                    kwargs[name] = specific_dependencies[component_class.__name__][name]
                # Then check common dependencies
                elif name in component_args:
                    kwargs[name] = component_args[name]
                # Handle required params that we don't have
                elif param.default == inspect.Parameter.empty:
                    logger.error(f"Missing required parameter '{name}' for {component_class.__name__}")
                    return None

            # Create instance with collected kwargs
            instance = component_class(**kwargs)
            return instance

        except Exception as e:
            logger.error(f"Error creating instance of {component_class.__name__}: {e}", exc_info=True)
            return None

    async def close_all(self):
        """Close all internally managed components and cleanup resources."""
        logger.info("Starting DataPackage cleanup sequence for internal components...")
        
        # Define only the components INITIALIZED INTERNALLY by DataPackage
        # The attribute name must match how it's stored on `self`
        internal_components_to_close = [
            # List internal components and their standard close method name
            ('token_scanner', 'close'),
            ('monitoring', 'close'),      # Check if Monitoring has a close method
            ('analytics', 'close'),       # Check if Analytics has a close method
            ('data_fetcher', 'close'),
            ('token_metrics', 'close'),   # Check if TokenMetrics has a close method
            ('delta_calculator', 'close') # Check if DeltaCalculator has a close method
            # Add others if DataPackage initializes them internally
        ]

        # --- Removed attempts to close externally managed components like http_client, solana_client, db, etc. ---

        for attr_name, close_method_name in internal_components_to_close:
            component = getattr(self, attr_name, None)
            if component is not None:
                # Check if the component was indeed initialized internally (optional but safer)
                # This assumes internal components aren't replaced by external ones later
                # if getattr(self, f"_was_{attr_name}_initialized_internally", False): # Requires tracking during init
                try:
                    close_func = getattr(component, close_method_name, None)
                    if close_func and callable(close_func):
                        logger.debug(f"Closing internal component: {attr_name}...")
                        if asyncio.iscoroutinefunction(close_func):
                            await close_func()
                        else:
                            close_func()
                        logger.info(f"Successfully closed internal component: {attr_name}")
                    elif hasattr(component, 'close'): # Fallback check for generic 'close'
                        logger.warning(f"Internal component {attr_name} has a 'close' method, but expected '{close_method_name}'. Attempting generic close...")
                        try:
                            if asyncio.iscoroutinefunction(component.close):
                                await component.close()
                            else:
                                component.close()
                            logger.info(f"Successfully closed internal component {attr_name} using generic close().")
                        except Exception as e_generic:
                             logger.error(f"Error closing {attr_name} using generic close(): {e_generic}", exc_info=True)
                    else:
                        logger.debug(f"No standard close method ('{close_method_name}' or 'close') found for internal component: {attr_name}")
                except Exception as e:
                    logger.error(f"Error closing internal component {attr_name}: {e}", exc_info=True)
            # else: Component was not initialized or already cleared.

        # Clear internal component references (optional, helps GC)
        logger.debug("Clearing references to internal DataPackage components.")
        for attr_name, _ in internal_components_to_close:
            setattr(self, attr_name, None)
            # Also clear tracking flag if used: setattr(self, f"_was_{attr_name}_initialized_internally", False)

        logger.info("DataPackage internal component cleanup sequence complete")