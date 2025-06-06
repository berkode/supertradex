import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import asyncio
from data.token_database import TokenDatabase
from data.price_monitor import PriceMonitor
from filters.filter_manager import FilterManager
from data.analytics import Analytics
from utils.logger import get_logger
from config.thresholds import Thresholds
from config.settings import Settings
from solana.rpc.async_api import AsyncClient
from data.models import Token # Assuming Token model is defined here

logger = get_logger(__name__)

class DeltaCalculator:
    """Handles calculation of delta changes in token metrics across different timeframes.
    
    The process involves calculating changes between neighboring timeframes using pre-collected data.
    
    Timeframes are organized into three categories:
    1. Short-term (1s to 1m):
       - 1s: 1 second data
       - 5s: 5 seconds data
       - 15s: 15 seconds data
       - 1m: 1 minute data
    
    2. Medium-term (1m to 1h):
       - 5m: 5 minutes data
       - 15m: 15 minutes data
       - 1h: 1 hour data
    
    3. Long-term (1h to 24h):
       - 6h: 6 hours data
       - 24h: 24 hours data
    """
    
    def __init__(self, settings: Settings, thresholds: Thresholds, token_db: TokenDatabase, price_monitor: PriceMonitor, solana_client: AsyncClient, filter_manager: FilterManager):
        """
        Initialize DeltaCalculator.
        
        Args:
            settings: The application settings instance.
            thresholds: The thresholds instance.
            token_db: Instance of TokenDatabase.
            price_monitor: Instance of PriceMonitor.
            solana_client: Instance of AsyncClient for Solana RPC calls.
            filter_manager: Instance of FilterManager.
        """
        self.settings = settings
        self.thresholds = thresholds
        self.token_db = token_db
        self.price_monitor = price_monitor
        self.solana_client = solana_client
        self.filter_manager = filter_manager
        self.analytics = Analytics(settings=self.settings)
        
        # Define individual timeframes for data collection
        self.timeframes = {
            # Short-term (1s to 1m)
            '1s': 1,      # 1 second data
            '5s': 5,      # 5 seconds data
            '15s': 15,    # 15 seconds data
            '1m': 60,     # 1 minute data
            
            # Medium-term (1m to 1h)
            '5m': 300,    # 5 minutes data
            '15m': 900,   # 15 minutes data
            '1h': 3600,   # 1 hour data
            
            # Long-term (1h to 24h)
            '6h': 21600,  # 6 hours data
            '24h': 86400  # 24 hours data
        }
        
        # Define delta calculation pairs
        self.delta_pairs = {
            # Short-term deltas
            '1s_5s': ('1s', '5s'),    # Delta between 1s and 5s data
            '5s_15s': ('5s', '15s'),  # Delta between 5s and 15s data
            '15s_1m': ('15s', '1m'),  # Delta between 15s and 1m data
            
            # Medium-term deltas
            '1m_5m': ('1m', '5m'),    # Delta between 1m and 5m data
            '5m_15m': ('5m', '15m'),  # Delta between 5m and 15m data
            '15m_1h': ('15m', '1h'),  # Delta between 15m and 1h data
            
            # Long-term deltas
            '1h_6h': ('1h', '6h'),    # Delta between 1h and 6h data
            '6h_24h': ('6h', '24h')   # Delta between 6h and 24h data
        }
        
        # Define metric types including transaction metrics
        self.metric_types = [
            'price', 'volume', 'liquidity', 'mcap',
            'txn_buys', 'txn_sells', 'txn_total',
            'txn_buy_volume', 'txn_sell_volume', 'txn_total_volume'
        ]
        
        # Define timeframes in seconds for easier calculation
        self.timeframes = {
            "1s": 1,
            "5s": 5,
            "15s": 15,
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "6h": 21600,
            "24h": 86400
        }
        
        # Ordered list of timeframes for sequential processing
        self.ordered_timeframes = [
            "1s", "5s", "15s", "1m", "5m", "15m", "1h", "6h", "24h"
        ]
        
        self.delta_metrics = {}
        logger.info("DeltaCalculator initialized.")
        
    async def initialize(self) -> bool:
        """
        Initialize the DeltaCalculator and its dependencies.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            logger.info("Initializing DeltaCalculator")
            
            # Initialize Analytics if it has initialize method
            if hasattr(self.analytics, 'initialize'):
                if not await self.analytics.initialize():
                    logger.error("Failed to initialize Analytics")
                    return False
                    
            # Initialize DataFilter if it has initialize method
            if hasattr(self.filter_manager, 'initialize'):
                if not await self.filter_manager.initialize():
                    logger.error("Failed to initialize DataFilter")
                    return False
                    
            logger.info("DeltaCalculator initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing DeltaCalculator: {e}")
            # Still return True to allow application to continue
            return True
            
    async def close(self):
        """
        Close resources used by DeltaCalculator.
        """
        try:
            # Close Analytics if it has close method
            if hasattr(self.analytics, 'close'):
                await self.analytics.close()
                
            # Close DataFilter if it has close method
            if hasattr(self.filter_manager, 'close'):
                await self.filter_manager.close()
                
            logger.info("DeltaCalculator resources closed")
        except Exception as e:
            logger.error(f"Error closing DeltaCalculator resources: {e}")

    async def calculate_deltas(self, mint: str, timeframe_data: Dict[str, Dict]) -> List[Dict]:
        """Calculate delta changes for all metrics and timeframes using pre-collected data."""
        deltas = []
        
        try:
            # Calculate deltas between neighboring timeframes
            for delta_name, (short_tf, long_tf) in self.delta_pairs.items():
                logger.info(f"Calculating delta for pair {delta_name} ({short_tf} -> {long_tf})")
                
                short_data = timeframe_data.get(short_tf)
                long_data = timeframe_data.get(long_tf)
                
                if not short_data or not long_data:
                    logger.warning(f"Missing data for {mint} at timeframe {delta_name}")
                    continue
                
                # Validate data before processing
                if not self._validate_data(short_data) or not self._validate_data(long_data):
                    logger.warning(f"Invalid data for {mint} at timeframe {delta_name}")
                    continue
                
                # Calculate deltas for each metric
                for metric_type in self.metric_types:
                    delta = self._calculate_single_delta(
                        short_data, long_data, metric_type, delta_name, mint
                    )
                    if delta:
                        # Add analytics data
                        delta = self._add_analytics(delta, short_data, long_data)
                        deltas.append(delta)
                        logger.info(f"Calculated delta for {metric_type} at {delta_name}")
            
            # Store calculated deltas
            if deltas:
                await self.token_db.store_token_deltas(mint, deltas)
                logger.info(f"Stored {len(deltas)} deltas for token {mint}")
                
            return deltas
            
        except Exception as e:
            logger.error(f"Error calculating deltas for token {mint}: {e}")
            return deltas
            
    def _validate_data(self, data: Dict) -> bool:
        """Validate data format and completeness."""
        try:
            # Basic validation
            if not data or not isinstance(data, dict):
                logger.warning("Invalid data format")
                return False
                
            # Check required fields
            required_fields = ['mint', 'timestamp'] + self.metric_types
            if not all(field in data for field in required_fields):
                logger.warning("Missing required fields in data")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error validating data: {e}")
            return False
            
    def _add_analytics(self, delta: Dict, short_data: Dict, long_data: Dict) -> Dict:
        """Add analytics data to delta calculation."""
        try:
            # Calculate volatility
            volatility = self.analytics.calculate_volatility(
                short_data.get('price', 0),
                long_data.get('price', 0)
            )
            
            # Calculate volume profile
            volume_profile = self.analytics.calculate_volume_profile(
                short_data.get('volume', 0),
                long_data.get('volume', 0),
                short_data.get('txn_total', 0),
                long_data.get('txn_total', 0)
            )
            
            # Calculate liquidity metrics
            liquidity_metrics = self.analytics.calculate_liquidity_metrics(
                short_data.get('liquidity', 0),
                long_data.get('liquidity', 0),
                short_data.get('volume', 0),
                long_data.get('volume', 0)
            )
            
            # Add analytics data to delta
            delta.update({
                'volatility': volatility,
                'volume_profile': volume_profile,
                'liquidity_metrics': liquidity_metrics,
                'timestamp': datetime.now().timestamp()
            })
            
            return delta
            
        except Exception as e:
            logger.error(f"Error adding analytics to delta: {e}")
            return delta
            
    def _calculate_single_delta(self, short_data: Dict, long_data: Dict, 
                              metric_type: str, timeframe: str, mint: str) -> Optional[Dict]:
        """Calculate delta for a single metric between two timeframes."""
        try:
            short_value = short_data.get(metric_type, 0)
            long_value = long_data.get(metric_type, 0)
            
            # Calculate percentage change
            if long_value != 0:
                percentage_change = ((short_value - long_value) / long_value) * 100
            else:
                percentage_change = 0
                
            return {
                'mint': mint,
                'timeframe': timeframe,
                'metric_type': metric_type,
                'short_value': short_value,
                'long_value': long_value,
                'absolute_change': short_value - long_value,
                'percentage_change': percentage_change,
                'short_timestamp': short_data.get('timestamp'),
                'long_timestamp': long_data.get('timestamp')
            }
            
        except Exception as e:
            logger.error(f"Error calculating delta for {metric_type}: {e}")
            return None 