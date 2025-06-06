import os
import logging
import pandas as pd
import asyncio
from typing import List, Dict, Optional, Any, Set, TYPE_CHECKING
from datetime import datetime, timedelta, timezone
import json
import httpx

from data.price_monitor import PriceMonitor
from data.indicators import TechnicalIndicators
from data.data_processing import DataProcessing
from data.delta_calculator import DeltaCalculator
from filters.whitelist import Whitelist
from data.token_database import TokenDatabase
from config.thresholds import Thresholds
from data.platform_tracker import PlatformTracker
from data.monitoring import Monitoring, VolumeMonitor
from config.logging_config import LoggingConfig
from solana.rpc.async_api import AsyncClient
from utils.logger import get_logger
from filters.filter_manager import FilterManager
from strategies.strategy_selector import StrategySelector

# Configure logging using centralized config - REMOVE
# LoggingConfig.setup_logging()
logger = get_logger(__name__)

if TYPE_CHECKING:
    from config.settings import Settings
    from data.token_database import TokenDatabase
    from data.price_monitor import PriceMonitor
    from data.indicators import TechnicalIndicators
    from filters.whitelist import Whitelist
    from config.thresholds import Thresholds
    from data.platform_tracker import PlatformTracker
    from filters.filter_manager import FilterManager
    from data.monitoring import Monitoring, VolumeMonitor
    from solana.rpc.async_api import AsyncClient
    import httpx # Keep if used by injected components or directly

# Define indicator periods (consider moving to config/thresholds)
RSI_PERIOD = 14
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9
BB_PERIOD = 20
BB_STD_DEV = 2.0
SMA_SHORT_PERIOD = 20
SMA_LONG_PERIOD = 50
MIN_HISTORY_FOR_INDICATORS = max(RSI_PERIOD, MACD_SLOW_PERIOD, BB_PERIOD, SMA_LONG_PERIOD) # Minimum data points needed

class TokenMetrics:
    """
    Orchestrates token data collection, analysis, filtering, and strategy application.
    Starts and manages continuous monitoring for selected tokens.
    Stores results in the database for use by the trading system.
    """
    
    def __init__(self, 
                 settings: 'Settings',
                 db: 'TokenDatabase',
                 price_monitor: 'PriceMonitor',
                 thresholds: 'Thresholds',
                 filter_manager: 'FilterManager',
                 whitelist: 'Whitelist',
                 monitoring: 'Monitoring',
                 indicators: 'TechnicalIndicators',
                 platform_tracker: 'PlatformTracker',
                 volume_monitor: 'VolumeMonitor',
                 strategy_selector: 'StrategySelector',
                 solana_client: Optional['AsyncClient'] = None):
        """
        Initialize components for token metrics processing.
        
        Args:
            settings: The global application settings object.
            db: Initialized TokenDatabase instance.
            price_monitor: Initialized PriceMonitor instance.
            thresholds: Initialized Thresholds instance.
            filter_manager: Initialized FilterManager instance.
            whitelist: Initialized Whitelist instance.
            monitoring: Initialized Monitoring instance.
            indicators: Initialized TechnicalIndicators instance.
            platform_tracker: Initialized PlatformTracker instance.
            volume_monitor: Initialized VolumeMonitor instance.
            strategy_selector: Initialized StrategySelector instance.
            solana_client: Optional initialized AsyncClient instance.
        """
        # Validate mandatory dependencies
        if not all([settings, db, price_monitor, thresholds, filter_manager, whitelist,
                    monitoring, indicators, platform_tracker, volume_monitor, strategy_selector]):
            logger.error("TokenMetrics initialized with missing mandatory dependencies.")
            raise ValueError("TokenMetrics requires all specified component instances.")

        self.settings = settings
        self.db = db
        self.solana_client = solana_client
        self.price_monitor = price_monitor
        self.thresholds = thresholds
        self.filter_manager = filter_manager
        self.whitelist = whitelist
        self.monitoring = monitoring
        self.indicators = indicators
        self.platform_tracker = platform_tracker
        self.volume_monitor = volume_monitor
        
        self.strategy_selector = strategy_selector
        
        self.min_price_history = int(getattr(self.settings, "MIN_PRICE_HISTORY", 30))
        
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        
        self._price_history_cache = {}
        self._cache_ttl = timedelta(minutes=5)
        self._last_cache_clear = datetime.now(timezone.utc)
        
        logger.info("TokenMetrics initialized")
    
    def calculate_bonding_curve_ratio(self, market_cap: float, liquidity: float) -> float:
        """
        Calculate the ratio between market cap and bonding curve value.
        
        Args:
            market_cap: Current market cap of the token
            liquidity: Current liquidity of the token
            
        Returns:
            float: Ratio of market cap to bonding curve
        """
        try:
            if liquidity <= 0:
                return 0.0
                
            # Ensure market_cap is also treated as float
            if isinstance(market_cap, (int, float)) and market_cap > 0:
                 market_cap = float(market_cap)
            else:
                 # Handle cases where market_cap might be None or invalid
                 logger.warning(f"Invalid market cap value encountered: {market_cap}")
                 return 0.0

            # Ensure liquidity is float
            liquidity = float(liquidity)
                
            return market_cap / liquidity
            
        except TypeError as e:
            logger.error(f"Type error calculating bonding curve ratio (MCap: {market_cap}, Liq: {liquidity}): {e}")
            return 0.0
        except Exception as e:
            logger.error(f"Error calculating bonding curve ratio: {e}")
            return 0.0

    def determine_token_category(self, token_metrics: Dict) -> str:
        """
        Determine token category based on metrics.
        Categories are used for initial filtering and context, not trading strategy.
        """
        try:
            age_minutes = token_metrics.get('age_minutes', 0)
            market_cap = token_metrics.get('market_cap', 0)
            liquidity = token_metrics.get('liquidity_usd', 0)
            volume_5m = token_metrics.get('volume_5m', 0)

            # Ensure metrics are numeric, default to 0 if not
            age_minutes = float(age_minutes) if age_minutes is not None else 0
            market_cap = float(market_cap) if market_cap is not None else 0
            liquidity = float(liquidity) if liquidity is not None else 0
            volume_5m = float(volume_5m) if volume_5m is not None else 0

            bonding_curve_ratio = self.calculate_bonding_curve_ratio(market_cap, liquidity)
            liquidity_ratio = liquidity / market_cap if market_cap > 0 else 0
            
            # FRESH category (0-15 minutes)
            if (0 <= age_minutes <= self.thresholds.FRESH_AGE_MAX and 
                self.thresholds.FRESH_MCAP_MIN <= market_cap <= self.thresholds.FRESH_MCAP_MAX and
                volume_5m >= self.thresholds.FRESH_VOLUME_5M_MIN and
                liquidity >= self.thresholds.FRESH_LIQUIDITY_MIN and
                liquidity_ratio >= self.thresholds.FRESH_LIQUIDITY_RATIO):
                return 'FRESH'
                
            # NEW category (1-45 minutes)
            if (self.thresholds.NEW_AGE_MIN <= age_minutes <= self.thresholds.NEW_AGE_MAX and
                market_cap >= self.thresholds.NEW_MCAP_MIN and
                self.thresholds.NEW_MCAP_BC_MIN <= bonding_curve_ratio <= self.thresholds.NEW_MCAP_BC_MAX and
                volume_5m >= self.thresholds.NEW_VOLUME_5M_MIN and
                liquidity >= self.thresholds.NEW_LIQUIDITY_MIN and
                liquidity_ratio >= self.thresholds.NEW_LIQUIDITY_RATIO):
                return 'NEW'
                
            # FINAL category (3-120 minutes)
            if (self.thresholds.FINAL_AGE_MIN <= age_minutes <= self.thresholds.FINAL_AGE_MAX and
                market_cap >= self.thresholds.FINAL_MCAP_MIN and
                self.thresholds.FINAL_MCAP_BC_MIN <= bonding_curve_ratio <= self.thresholds.FINAL_MCAP_BC_MAX and
                volume_5m >= self.thresholds.FINAL_VOLUME_5M_MIN and
                liquidity >= self.thresholds.FINAL_LIQUIDITY_MIN and
                liquidity_ratio >= self.thresholds.FINAL_LIQUIDITY_RATIO):
                return 'FINAL'
                
            # MIGRATED category (5+ minutes) - Check if MIGRATED_AGE_MIN exists
            migrated_age_min = getattr(self.thresholds, 'MIGRATED_AGE_MIN', 5) # Default to 5 if not defined
            if (age_minutes >= migrated_age_min and
                bonding_curve_ratio >= self.thresholds.MIGRATED_MCAP_BC_MIN and
                volume_5m >= self.thresholds.MIGRATED_VOLUME_5M_MIN and
                liquidity >= self.thresholds.MIGRATED_LIQUIDITY_MIN and
                liquidity_ratio >= self.thresholds.MIGRATED_LIQUIDITY_RATIO):
                return 'MIGRATED'
                
            # OLD category (120+ minutes)
            if (age_minutes >= self.thresholds.OLD_AGE_MIN and
                bonding_curve_ratio >= self.thresholds.OLD_MCAP_BC_MIN and
                volume_5m >= self.thresholds.OLD_VOLUME_5M_MIN and
                liquidity_ratio >= self.thresholds.OLD_LIQUIDITY_RATIO):
                return 'OLD'
                
            return 'NONE'
            
        except Exception as e:
            logger.error(f"Error determining token category: {e}", exc_info=True)
            return 'NONE'

    async def process_token(self, mint: str) -> Dict:
        """Process a single token with unified trading logic."""
        logger.info(f"Processing token: {mint}")
        try:
            # Step 1: Collect price data (using existing PriceMonitor logic)
            # Ensure PriceMonitor is ready and has the necessary methods
            if not self.price_monitor:
                 logger.error(f"PriceMonitor not available for processing {mint}")
                 return {"mint": mint, "status": "failed", "reason": "PriceMonitor unavailable"}
            
            # Assuming set_tokens and start are still relevant methods on PriceMonitor
            # If PriceMonitor manages its own tokens, these might not be needed here.
            if hasattr(self.price_monitor, 'set_tokens'):
                 self.price_monitor.set_tokens([mint])
            if hasattr(self.price_monitor, 'start'):
                 self.price_monitor.start([mint]) # Or maybe start monitoring if needed

            # Wait for sufficient price history
            timeout = 60  # seconds
            start_time = datetime.now()
            price_history = []
            min_history_points = getattr(self.settings, 'MIN_PRICE_HISTORY_POINTS', 10) # Example: Get required points from settings
            
            while True:
                # Assuming get_price_history is the correct method
                current_history = self.price_monitor.get_price_history(mint)
                if current_history is not None:
                    price_history = current_history # Update with the latest list
                
                if len(price_history) >= min_history_points:
                    logger.info(f"Collected {len(price_history)} price points for {mint}")
                    break
                if (datetime.now() - start_time).total_seconds() > timeout:
                    logger.warning(f"Timeout collecting price data for {mint}. Only got {len(price_history)} points.")
                    if not price_history:
                         if hasattr(self.price_monitor, 'stop'): self.price_monitor.stop()
                         return {"mint": mint, "status": "failed", "reason": "No price data available after timeout"}
                    break # Proceed with limited data if timeout reached but some data exists
                await asyncio.sleep(5)

            # Stop monitoring if it was started here
            if hasattr(self.price_monitor, 'stop'):
                self.price_monitor.stop() 

            latest_data = price_history[-1] if price_history else None
            if not latest_data:
                 logger.error(f"No latest price data obtained for {mint}")
                 return {"mint": mint, "status": "failed", "reason": "Could not get latest price data"}

            # Step 2: Calculate core metrics
            market_cap = latest_data.get('market_cap', 0)
            liquidity = latest_data.get('liquidity_usd', 0)
            
            metrics = {
                'age_minutes': latest_data.get('age_minutes', 0),
                'market_cap': market_cap,
                'liquidity_usd': liquidity,
                'volume_5m': latest_data.get('volume', {}).get('m5', 0), # Check DexScreener format
                'bonding_curve_ratio': self.calculate_bonding_curve_ratio(market_cap, liquidity),
                'price_usd': latest_data.get('priceUsd', 0) # Ensure price is captured
            }
            
            # Step 3: Determine category (for context only)
            category = self.determine_token_category(metrics)
            metrics['category'] = category
            logger.info(f"Determined category for {mint}: {category}")
            
            # Step 4: Calculate universal indicators
            # Assuming indicators calculation uses price_history
            indicators = {}
            if self.indicators: # Check if indicators component exists
                 indicators_result = await self.indicators.calculate_all(mint, price_history) # Adjust method call based on TechnicalIndicators class
                 if not indicators_result:
                      logger.warning(f"Could not calculate indicators for {mint}")
                 else:
                      indicators = indicators_result
            else:
                 logger.warning(f"Indicators component not available for {mint}")
            
            logger.info(f"Calculated indicators for {mint}: {list(indicators.keys())}")

            # Step 5: Get category-specific thresholds
            thresholds = self.get_category_thresholds(category)
            logger.debug(f"Using thresholds for category {category}: {thresholds}")
            
            # Step 6: Apply unified trading rules with category context
            trading_signal = await self.generate_trading_signal(
                token_data=latest_data,
                metrics=metrics,
                indicators=indicators,
                thresholds=thresholds
            )
            logger.info(f"Generated trading signal for {mint}: Entry={trading_signal['entry']}, Exit={trading_signal['exit']}")

            # Step 7: Combine and Store results
            combined_data = {
                **metrics,
                **indicators,
                'trading_signal': trading_signal,
                'latest_price_data': latest_data, # Store raw latest data for reference
                'timestamp': datetime.now(timezone.utc).isoformat() # Use UTC timestamp
            }
            
            if self.db and hasattr(self.db, 'store_token_metrics'): # Check db and method exist
                 await self.db.store_token_metrics(mint, combined_data)
                 logger.info(f"Stored metrics and signal for {mint}")
            else:
                 logger.warning(f"Database not available or lacks store_token_metrics method. Cannot store results for {mint}.")

            return {
                "status": "success",
                "mint": mint,
                "category": category,
                "metrics": metrics,
                "indicators": indicators,
                "trading_signal": trading_signal
            }
            
        except Exception as e:
            logger.error(f"Error processing token {mint}: {e}", exc_info=True)
            # Ensure price monitor is stopped if an error occurs mid-process
            if hasattr(self, 'price_monitor') and self.price_monitor and hasattr(self.price_monitor, 'stop'):
                 try: self.price_monitor.stop()
                 except Exception as stop_err: logger.error(f"Error stopping price monitor during exception handling: {stop_err}")
            return {"mint": mint, "status": "failed", "reason": str(e)}
    
    async def process_whitelist(self):
        """Process all tokens in the whitelist."""
        tokens = self.whitelist.get_all_tokens()
        if not tokens:
            logger.warning("Whitelist is empty. No tokens to process.")
            return []
            
        logger.info(f"Processing {len(tokens)} whitelisted tokens")
        
        # Process tokens in parallel
        tasks = [self.process_token(token) for token in tokens]
        results = await asyncio.gather(*tasks)
        
        return results
    
    async def apply_strategies(self):
        """Apply strategies to analyzed tokens."""
        logger.info("Applying strategies to analyzed tokens")
        
        try:
            # Get tokens that passed filters from database
            tokens = self.db.get_filtered_tokens()
            
            if not tokens:
                logger.warning("No tokens passed filters. Cannot apply strategies.")
                return
                
            # Convert to DataFrame for strategy selector
            tokens_df = pd.DataFrame(tokens)
            
            # Run strategy selector
            self.strategy_selector.run(tokens_df)
            logger.info(f"Applied strategies to {len(tokens)} tokens")
            
            # Store strategy assignments in database
            for token in tokens:
                # Determine strategies that apply to this token
                strategies = []
                if token.get('is_breakout_candidate', False):
                    strategies.append('breakout')
                if token.get('is_trend_candidate', False):
                    strategies.append('trend_following')
                if token.get('is_mean_reversion_candidate', False):
                    strategies.append('mean_reversion')
                if not strategies:
                    strategies.append('default')
                    
                # Update token record with strategies
                self.db.update_token_strategies(token.get('mint'), strategies)
                
        except Exception as e:
            logger.error(f"Error applying strategies: {e}")
    
    async def start_monitoring_for_token(self, mint: str):
        """Starts a continuous monitoring task for a given token mint."""
        if mint in self.monitoring_tasks and not self.monitoring_tasks[mint].done():
            logger.debug(f"Monitoring task for {mint} already running.")
            return
            
        logger.info(f"Starting monitoring task for {mint}...")
        try:
            # Create and store the task
            task = asyncio.create_task(self.monitoring.monitor_token(mint))
            self.monitoring_tasks[mint] = task
            
            # Add a callback to remove the task from the dict if it finishes/errors
            task.add_done_callback(lambda t: self.monitoring_tasks.pop(mint, None))
            
            logger.info(f"Successfully started monitoring for {mint}.")
        except Exception as e:
            logger.error(f"Failed to start monitoring task for {mint}: {e}", exc_info=True)
            # Clean up if task creation failed but somehow added to dict
            if mint in self.monitoring_tasks:
                 del self.monitoring_tasks[mint]

    async def stop_monitoring_for_token(self, mint: str):
        """Stops the monitoring task for a given token mint."""
        task = self.monitoring_tasks.get(mint)
        if task and not task.done():
            logger.info(f"Stopping monitoring task for {mint}...")
            try:
                task.cancel()
                # Allow task to process cancellation
                await asyncio.sleep(0) 
                # Remove immediately, the done callback will handle if it wasn't removed yet
                if mint in self.monitoring_tasks:
                    del self.monitoring_tasks[mint]
                logger.info(f"Successfully requested stop for monitoring task {mint}.")
            except asyncio.CancelledError:
                 logger.info(f"Monitoring task {mint} was cancelled.")
                 if mint in self.monitoring_tasks:
                     del self.monitoring_tasks[mint]
            except Exception as e:
                logger.error(f"Error stopping monitoring task for {mint}: {e}", exc_info=True)
                # Ensure removal even if cancellation had issues
                if mint in self.monitoring_tasks:
                     del self.monitoring_tasks[mint]
        elif task and task.done():
             logger.debug(f"Monitoring task for {mint} already finished.")
             if mint in self.monitoring_tasks:
                  del self.monitoring_tasks[mint] # Clean up reference
        else:
            logger.debug(f"No active monitoring task found for {mint} to stop.")

    async def stop_all_monitoring(self):
        """Stops all active monitoring tasks."""
        logger.info(f"Stopping all active monitoring tasks ({len(self.monitoring_tasks)})...")
        mints_to_stop = list(self.monitoring_tasks.keys())
        tasks_to_await = []
        for mint in mints_to_stop:
             task = self.monitoring_tasks.get(mint)
             if task and not task.done():
                 logger.info(f"Requesting cancellation for monitoring task {mint}...")
                 task.cancel()
                 tasks_to_await.append(task)
                 # Remove immediately from dict
                 del self.monitoring_tasks[mint]
             elif task: # Task exists but is done
                  if mint in self.monitoring_tasks:
                       del self.monitoring_tasks[mint] # Clean up reference
        
        # Wait briefly for tasks to handle cancellation if needed
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
            logger.info("Finished awaiting cancellation for monitoring tasks.")
        else:
            logger.info("No active tasks needed cancellation.")
        
        self.monitoring_tasks.clear() # Ensure dict is empty
        logger.info("All monitoring tasks stopped.")

    async def _get_rugcheck_report(self, mint: str) -> Dict:
        """Get detailed RugCheck report and insiders graph data."""
        try:
            # Use DumpChecker to get detailed report
            report = await self.dump_checker.get_detailed_report(mint)
            insiders_data = await self.dump_checker.get_insiders_graph(mint)
            
            return {
                'rugcheckScore': report.get('score'),
                'highRiskCount': report.get('highRiskCount'),
                'moderateRiskCount': report.get('moderateRiskCount'),
                'lowRiskCount': report.get('lowRiskCount'),
                'specificRiskCount': report.get('specificRiskCount'),
                'insiders_graph': insiders_data
            }
        except Exception as e:
            logger.error(f"Error getting RugCheck report: {e}")
            return {}
            
    async def _get_platform_data(self, mint: str) -> Dict:
        """Get platform-specific data and calculate distribution."""
        try:
            # Use PlatformTracker to get data from each DEX
            platforms = await self.platform_tracker.get_platform_data(mint)
            
            # Calculate platform distribution
            distribution = self._calculate_platform_distribution(platforms)
            
            return {
                'platform_distribution': distribution,
                'platforms': platforms
            }
        except Exception as e:
            logger.error(f"Error getting platform data: {e}")
            return {}
            
    def _calculate_platform_distribution(self, platforms: List[Dict]) -> Dict:
        """Calculate token's distribution across different DEXes."""
        try:
            distribution = {}
            total_liquidity = sum(p.get('liquidity_usd', 0) for p in platforms)
            
            if total_liquidity == 0:
                return {}
                
            for platform in platforms:
                dex_id = platform.get('dex_id')
                liquidity = platform.get('liquidity_usd', 0)
                distribution[dex_id] = {
                    'percentage': (liquidity / total_liquidity) * 100,
                    'liquidity_usd': liquidity,
                    'volume_24h': platform.get('volume_24h', 0)
                }
                
            return distribution
        except Exception as e:
            logger.error(f"Error calculating platform distribution: {e}")
            return {}

    async def _calculate_metrics(self, basic_info: Dict, rug_report: Dict, platform_data: Dict) -> Dict:
        """Calculate additional metrics including volume/liquidity ratio and price stability."""
        try:
            # Calculate volume/liquidity ratio
            volume_liquidity_ratio = self._calculate_volume_liquidity_ratio(
                basic_info.get('volume_5m', 0),
                basic_info.get('liquidity_usd', 0)
            )
            
            # Calculate price stability score
            price_stability = await self._calculate_price_stability(basic_info['mint'])
            
            # Calculate bonding curve ratio
            bonding_curve_ratio = self.calculate_bonding_curve_ratio(
                basic_info.get('market_cap', 0),
                basic_info.get('liquidity_usd', 0)
            )
            
            # Determine token category
            token_category = self._determine_token_category(
                basic_info,
                rug_report,
                platform_data
            )
            
            return {
                'volume_liquidity_ratio': volume_liquidity_ratio,
                'price_stability_score': price_stability,
                'bonding_curve_ratio': bonding_curve_ratio,
                'token_category': token_category
            }
        except Exception as e:
            logger.error(f"Error calculating metrics: {e}")
            return {}
            
    async def _monitor_patterns(self, mint: str) -> Dict:
        """Monitor for trading patterns and volume spikes."""
        try:
            # Use VolumeMonitor to check for spikes
            volume_spikes = await self.volume_monitor.check_volume_spikes(mint)
            
            # Get technical indicators
            indicators = await self.indicators.get_indicators(mint)
            
            return {
                'volume_spikes': volume_spikes,
                'technical_indicators': indicators
            }
        except Exception as e:
            logger.error(f"Error monitoring patterns: {e}")
            return {}
            
    def _calculate_volume_liquidity_ratio(self, volume: float, liquidity: float) -> float:
        """Calculate the ratio between 24h volume and liquidity."""
        if not liquidity or liquidity == 0:
            return 0
        return volume / liquidity
        
    async def _calculate_price_stability(self, mint: str) -> float:
        """Calculate price stability score based on historical data."""
        try:
            # Get historical price data
            price_history = await self.db.get_token_deltas(mint, metric_type='price')
            
            if not price_history:
                return 0
                
            # Calculate price volatility
            prices = [delta['delta_value'] for delta in price_history]
            volatility = self._calculate_volatility(prices)
            
            # Convert to stability score (0-1, higher is more stable)
            stability = 1 - min(volatility, 1)
            
            return stability
        except Exception as e:
            logger.error(f"Error calculating price stability: {e}")
            return 0
            
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate price volatility."""
        if not prices or len(prices) < 2:
            return 0
            
        # Calculate standard deviation of price changes
        price_changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if not price_changes:
            return 0
            
        mean = sum(price_changes) / len(price_changes)
        squared_diff_sum = sum((x - mean) ** 2 for x in price_changes)
        variance = squared_diff_sum / len(price_changes)
        
        return variance ** 0.5
        
    def _determine_token_category(self, basic_info: Dict, rug_report: Dict, platform_data: Dict) -> str:
        """Determine token category based on various metrics."""
        try:
            # Get key metrics
            age = basic_info.get('age_minutes', 0)
            market_cap = basic_info.get('market_cap', 0)
            liquidity = basic_info.get('liquidity_usd', 0)
            bonding_ratio = self.calculate_bonding_curve_ratio(market_cap, liquidity)
            
            # Define thresholds
            thresholds = self.thresholds.get_token_category_thresholds()
            
            # Determine category based on metrics
            if age < thresholds['FRESH']['max_age'] and market_cap < thresholds['FRESH']['max_mcap']:
                return 'FRESH'
            elif age < thresholds['NEW']['max_age'] and market_cap < thresholds['NEW']['max_mcap']:
                return 'NEW'
            elif bonding_ratio < thresholds['FINAL']['max_bonding_ratio']:
                return 'FINAL'
            elif len(platform_data.get('platforms', [])) > 1:
                return 'MIGRATED'
            else:
                return 'OLD'
                
        except Exception as e:
            logger.error(f"Error determining token category: {e}")
            return 'UNKNOWN'

    async def generate_trading_signal(self, token_data: Dict, metrics: Dict, 
                                    indicators: Dict, thresholds: Dict) -> Dict:
        """Generate trading signals using unified logic with category context."""
        try:
            # Universal signal components
            signal = {
                'entry': False,
                'exit': False,
                'confidence': 0.0,
                'risk_level': 'high', # Default risk level
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Basic validation
            if not all([token_data, metrics, indicators, thresholds]):
                 logger.warning("Missing data for signal generation")
                 return signal

            # Ensure necessary indicators are present
            rsi = indicators.get('RSI')
            volume_trend = indicators.get('volume_trend', 'neutral') # Add default if missing

            # Use defaults from base_thresholds if specific keys missing
            rsi_oversold = thresholds.get('rsi_oversold', 30)
            rsi_overbought = thresholds.get('rsi_overbought', 70)
            min_liquidity = thresholds.get('min_liquidity', self.thresholds.MIN_LIQUIDITY)
            min_volume = thresholds.get('min_volume', self.thresholds.MIN_VOLUME_5M) # Use 5m volume threshold as default

            # Universal entry conditions
            entry_conditions = [
                rsi is not None and rsi < rsi_oversold,
                volume_trend == 'increasing', # Assuming volume_trend indicator exists
                metrics.get('liquidity_usd', 0) >= min_liquidity,
                metrics.get('volume_5m', 0) >= min_volume
            ]
            
            # Universal exit conditions
            exit_conditions = [
                rsi is not None and rsi > rsi_overbought,
                volume_trend == 'decreasing',
                metrics.get('liquidity_usd', 0) < min_liquidity * 0.8 # Exit if liquidity drops significantly
            ]
            
            # Calculate signal confidence based on how many entry conditions are met
            valid_entry_conditions = [c for c in entry_conditions if c is not None] # Filter out None results if indicators failed
            confidence = sum(valid_entry_conditions) / len(valid_entry_conditions) if valid_entry_conditions else 0.0
            
            # Determine risk level (example logic)
            risk_level = 'low' if confidence > 0.75 else 'medium' if confidence > 0.5 else 'high'

            # Update signal
            signal.update({
                'entry': all(valid_entry_conditions) and len(valid_entry_conditions) == len(entry_conditions), # All conditions must be met and valid
                'exit': any(c for c in exit_conditions if c is not None), # Any valid exit condition triggers exit
                'confidence': confidence,
                'risk_level': risk_level
            })
            
            return signal
            
        except Exception as e:
            logger.error(f"Error generating trading signal: {e}", exc_info=True)
            # Return default signal on error
            return {
                'entry': False,
                'exit': False,
                'confidence': 0.0,
                'risk_level': 'error',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

    def get_category_thresholds(self, category: str) -> Dict:
        """Get thresholds for a category, with defaults if category is NONE."""
        # Base thresholds applicable if no specific category matches or for 'NONE'
        base_thresholds = {
            'rsi_oversold': 30,
            'rsi_overbought': 70,
            'min_liquidity': self.thresholds.MIN_LIQUIDITY,
            'min_volume': self.thresholds.MIN_VOLUME_5M, # Using 5M as a general fallback
            # Add other common base thresholds if needed
        }
        
        # Define category-specific overrides
        category_thresholds = {
            'FRESH': {
                'rsi_oversold': self.thresholds.FRESH_RSI_OVERSOLD if hasattr(self.thresholds, 'FRESH_RSI_OVERSOLD') else 35,
                'rsi_overbought': self.thresholds.FRESH_RSI_OVERBOUGHT if hasattr(self.thresholds, 'FRESH_RSI_OVERBOUGHT') else 65,
                'min_liquidity': self.thresholds.FRESH_LIQUIDITY_MIN,
                'min_volume': self.thresholds.FRESH_VOLUME_5M_MIN
            },
            'NEW': {
                'rsi_oversold': self.thresholds.NEW_RSI_OVERSOLD if hasattr(self.thresholds, 'NEW_RSI_OVERSOLD') else 30,
                'rsi_overbought': self.thresholds.NEW_RSI_OVERBOUGHT if hasattr(self.thresholds, 'NEW_RSI_OVERBOUGHT') else 70,
                'min_liquidity': self.thresholds.NEW_LIQUIDITY_MIN,
                'min_volume': self.thresholds.NEW_VOLUME_5M_MIN
            },
            'FINAL': {
                'rsi_oversold': self.thresholds.FINAL_RSI_OVERSOLD if hasattr(self.thresholds, 'FINAL_RSI_OVERSOLD') else 25,
                'rsi_overbought': self.thresholds.FINAL_RSI_OVERBOUGHT if hasattr(self.thresholds, 'FINAL_RSI_OVERBOUGHT') else 75,
                'min_liquidity': self.thresholds.FINAL_LIQUIDITY_MIN,
                'min_volume': self.thresholds.FINAL_VOLUME_5M_MIN
            },
            'MIGRATED': {
                 'rsi_oversold': self.thresholds.MIGRATED_RSI_OVERSOLD if hasattr(self.thresholds, 'MIGRATED_RSI_OVERSOLD') else 20,
                 'rsi_overbought': self.thresholds.MIGRATED_RSI_OVERBOUGHT if hasattr(self.thresholds, 'MIGRATED_RSI_OVERBOUGHT') else 80,
                'min_liquidity': self.thresholds.MIGRATED_LIQUIDITY_MIN,
                'min_volume': self.thresholds.MIGRATED_VOLUME_5M_MIN
            },
            'OLD': {
                 'rsi_oversold': self.thresholds.OLD_RSI_OVERSOLD if hasattr(self.thresholds, 'OLD_RSI_OVERSOLD') else 20,
                 'rsi_overbought': self.thresholds.OLD_RSI_OVERBOUGHT if hasattr(self.thresholds, 'OLD_RSI_OVERBOUGHT') else 80,
                'min_liquidity': self.thresholds.OLD_LIQUIDITY_MIN,
                'min_volume': self.thresholds.OLD_VOLUME_5M_MIN
            }
        }
        
        # Return specific category thresholds if available, otherwise return base thresholds
        return category_thresholds.get(category, base_thresholds)

    # Add helper for risk level calculation if needed
    def calculate_risk_level(self, metrics: Dict, indicators: Dict) -> str:
         # Example risk calculation based on volatility, liquidity, etc.
         volatility = indicators.get('volatility', 0.5) # Default high volatility
         liquidity = metrics.get('liquidity_usd', 0)
         
         if volatility < 0.1 and liquidity > self.thresholds.MIN_LIQUIDITY * 50:
             return 'low'
         elif volatility < 0.3 and liquidity > self.thresholds.MIN_LIQUIDITY * 10:
             return 'medium'
         else:
             return 'high'

# Usage example
async def main():
    token_metrics = TokenMetrics()
    await token_metrics.start_monitoring()

if __name__ == "__main__":
    asyncio.run(main())

