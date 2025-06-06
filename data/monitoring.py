import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone

from construct import this
from data.market_data import MarketData
from data.token_database import TokenDatabase
from data.price_monitor import PriceMonitor
from data.delta_calculator import DeltaCalculator
from data.blockchain_listener import BlockchainListener
from data.data_fetcher import DataFetcher
from data.data_processing import DataProcessing
from config.settings import Settings
from config.thresholds import Thresholds
from data.indicators import TechnicalIndicators
from data.models import Token
from filters.filter_manager import FilterManager
from solana.rpc.async_api import AsyncClient
from utils.logger import get_logger

logger = get_logger(__name__)

class Monitoring:
    """Manages the continuous monitoring of selected tokens, including data fetching, processing, and analysis."""

    def __init__(self, settings: Settings, db: TokenDatabase, price_monitor: PriceMonitor, solana_client: AsyncClient, thresholds: Thresholds, filter_manager: FilterManager, market_data: MarketData):
        """Initializes the Monitoring component."""
        self.settings = settings
        self.db = db  # This is the TokenDatabase instance
        self.price_monitor = price_monitor
        self.solana_client = solana_client
        self.thresholds = thresholds
        self.filter_manager = filter_manager
        self.market_data = market_data
        self.technical_indicators = TechnicalIndicators(settings, thresholds)
        self.delta_calculator = DeltaCalculator(
            settings=settings, 
            thresholds=thresholds, 
            token_db=db, 
            price_monitor=price_monitor, 
            solana_client=solana_client, 
            filter_manager=filter_manager
        )
        
        self.logger = logger  # Store logger instance
        self.logger.info("Monitoring initialized with DB, PriceMonitor, SolanaClient, MarketData")
        
        self.running = False
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.token_monitoring_data: Dict[str, Any] = {}
        self.data_fetcher = DataFetcher(settings=self.settings)
        self.data_processor = DataProcessing()
        self.last_processed_block = 0
        self.monitoring_active = False
        self.logger.info("Monitoring instance created")
        
        # Define data source mapping for each timeframe
        self.timeframe_data_sources = {
            # Short-term: Use blockchain and real-time DEX data
            '1s': ['blockchain', 'realtime_dex'],
            '5s': ['blockchain', 'realtime_dex'],
            '15s': ['blockchain', 'realtime_dex'],
            '1m': ['blockchain', 'realtime_dex'],
            
            # Medium-term: Use DEX API and blockchain data
            '5m': ['dex_api', 'blockchain'],
            '15m': ['dex_api', 'blockchain'],
            '1h': ['dex_api', 'blockchain'],
            
            # Long-term: Use database and DEX API
            '6h': ['database', 'dex_api'],
            '24h': ['database', 'dex_api']
        }
        
        self.logger.info("Monitoring component initialized.")

    async def initialize(self):
        """Initializes necessary resources like database connections."""
        # Initialization logic for Monitoring, if any (e.g., loading initial state)
        self.logger.info("Monitoring component initialized.")
        await self.delta_calculator.initialize()
        return True

    async def collect_timeframe_data(self, mint: str, timeframe: str, 
                                   data_sources: List[str]) -> Optional[Dict]:
        """Collect data for specific timeframe from appropriate sources."""
        try:
            data = {}
            
            # Collect data from each source
            for source in data_sources:
                if source == 'blockchain':
                    blockchain_data = await self.blockchain_listener.get_transactions(
                        mint, self.delta_calculator.timeframes[timeframe], 
                        include_volume=True
                    )
                    data.update(blockchain_data)
                    
                elif source == 'realtime_dex':
                    dex_data = await self.data_fetcher.get_realtime_dex_data(
                        mint, self.delta_calculator.timeframes[timeframe]
                    )
                    data.update(dex_data)
                    
                elif source == 'dex_api':
                    api_data = await self.data_fetcher.get_dex_api_data(
                        mint, self.delta_calculator.timeframes[timeframe]
                    )
                    data.update(api_data)
                    
                elif source == 'database':
                    db_data = await self.db.get_token_data(
                        mint, self.delta_calculator.timeframes[timeframe]
                    )
                    data.update(db_data)
            
            # Process and clean the collected data
            if data:
                data = self.data_processor.clean_data(data)
                
            return data
            
        except Exception as e:
            self.logger.error(f"Error collecting data for timeframe {timeframe}: {e}")
            return None
            
    async def monitor_token(self, mint: str, interval: int = 1):
        """Monitor a token continuously, collecting data and calculating deltas."""
        while True:
            try:
                # Step 1: Collect data for all timeframes
                timeframe_data = {}
                for timeframe, seconds in self.delta_calculator.timeframes.items():
                    self.logger.info(f"Collecting data for timeframe {timeframe} ({seconds}s)")
                    data = await self.collect_timeframe_data(
                        mint, timeframe, 
                        self.timeframe_data_sources.get(timeframe, [])
                    )
                    if data:
                        timeframe_data[timeframe] = data
                        self.logger.info(f"Successfully collected data for timeframe {timeframe}")
                    else:
                        self.logger.warning(f"Failed to collect data for timeframe {timeframe}")
                
                # Step 2: Calculate deltas if we have data
                if timeframe_data:
                    deltas = await self.delta_calculator.calculate_deltas(mint, timeframe_data)
                    if deltas:
                        self.logger.info(f"Calculated {len(deltas)} deltas for {mint}")
                
                # Wait for next interval
                await asyncio.sleep(interval)
                
            except Exception as e:
                self.logger.error(f"Error in token monitoring: {e}")
                await asyncio.sleep(interval)
                
    async def monitor_tokens(self, mints: List[str], interval: int = 1):
        """Monitor multiple tokens concurrently."""
        tasks = [self.monitor_token(mint, interval) for mint in mints]
        await asyncio.gather(*tasks)

    async def start_monitoring_token(self, token: Token):
        """Starts the monitoring task for a specific token if not already running."""
        mint = token.mint
        if mint not in self.monitoring_tasks or self.monitoring_tasks[mint].done():
            self.logger.info(f"Starting monitoring task for token {mint} ({token.symbol})")
            self.token_monitoring_data[mint] = {
                'token': token,
                'last_update': datetime.now(timezone.utc),
                'data_points': {tf: None for tf in self.settings.MONITORING_TIMEFRAMES}
            }
            self.monitoring_tasks[mint] = asyncio.create_task(self._monitor_token(token))
            self.logger.debug(f"Monitoring task created for {mint}")
        else:
            self.logger.debug(f"Monitoring task for token {mint} is already running.")

    async def stop_monitoring_token(self, mint: str):
        """Stops the monitoring task for a specific token."""
        if mint in self.monitoring_tasks:
            task = self.monitoring_tasks[mint]
            if not task.done():
                self.logger.info(f"Stopping monitoring task for token {mint}...")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    self.logger.info(f"Monitoring task for {mint} cancelled successfully.")
                except Exception as e:
                    self.logger.error(f"Error occurred while stopping monitoring task for {mint}: {e}", exc_info=True)
            del self.monitoring_tasks[mint]
            if mint in self.token_monitoring_data:
                 del self.token_monitoring_data[mint]
            self.logger.info(f"Monitoring stopped for token {mint}.")
        else:
            self.logger.warning(f"No active monitoring task found for token {mint} to stop.")

    async def _monitor_token(self, token: Token):
        """The core monitoring loop for a single token."""
        mint = token.mint
        self.logger.info(f"Monitoring loop started for token {mint} ({token.symbol})")
        try:
            # --- ADD small initial delay --- #
            await asyncio.sleep(1) # Allow PriceMonitor a moment to potentially fetch initial price
            # --- END DELAY --- #
            while self.running:
                self.logger.debug(f"Running monitoring cycle for {mint}")
                
                # --- Corrected: Call get_latest_price synchronously and check result --- 
                latest_price_info = self.price_monitor.get_latest_price(mint) # Synchronous call
                # --- End Correction ---
                
                # Log the result of the price fetch attempt
                self.logger.debug(f"PriceMonitor cache fetch for {mint}: {latest_price_info}")

                if not latest_price_info:
                    # --- Enhanced Log Message --- #
                    self.logger.warning(f"Could not fetch latest price for {mint} from PriceMonitor cache. Skipping cycle.")
                    # --- End Enhanced Log --- #
                    await asyncio.sleep(self.settings.MONITORING_INTERVAL_SECONDS)
                    continue
                
                current_data = self.token_monitoring_data.get(mint, {})
                current_data['last_update'] = datetime.now(timezone.utc)
                current_data['latest_price'] = latest_price_info.get('priceUsd') # Use .get for safety 
                self.token_monitoring_data[mint] = current_data

                try:
                    # Fetch historical data (assuming it's stored/retrieved elsewhere)
                    historical_data = self.market_data.get_historical_data(mint, interval='1m', limit=100)
                    if not historical_data:
                        self.logger.warning(f"No historical data available for {mint} to calculate indicators.")
                        return # Skip calculation if no data

                    # Calculate indicators
                    indicators = await self.technical_indicators.calculate_all(historical_data)
                    self.logger.debug(f"Calculated indicators for {mint}: {indicators}")
                    # Here you would store or use the indicators, e.g., update a cache or trigger strategy evaluation
                    # self.indicator_cache[mint] = indicators
                except Exception as e:
                    self.logger.error(f"Error calculating indicators for {mint}: {e}", exc_info=True)

                try:
                    await self.delta_calculator.calculate_and_store_deltas(mint)
                    self.logger.debug(f"Calculated deltas for {mint}")
                except Exception as e:
                    self.logger.error(f"Error calculating deltas for {mint}: {e}", exc_info=True)
                
                await asyncio.sleep(self.settings.MONITORING_INTERVAL_SECONDS)
                
        except asyncio.CancelledError:
            self.logger.info(f"Monitoring loop for {mint} received cancellation request.")
        except Exception as e:
            self.logger.error(f"Unhandled error in monitoring loop for {mint}: {e}", exc_info=True)
        finally:
            self.logger.warning(f"Monitoring loop for {mint} ({token.symbol}) terminated.")

    async def run(self):
        """Main monitoring loop."""
        self.running = True
        self.logger.info("Starting Monitoring run loop...")
        try:
            while self.running:
                try:
                    # Get tokens that need monitoring
                    tokens_to_monitor = await self.db.get_tokens_ready_for_monitoring()

                    if tokens_to_monitor:
                        self.logger.info(f"Found {len(tokens_to_monitor)} tokens for monitoring")
                        for token in tokens_to_monitor:
                            await self.start_monitoring_token(token)

                    # Use the correct setting for the monitoring service interval
                    await asyncio.sleep(self.settings.MONITORING_INTERVAL_SECONDS)

                except Exception as e:
                    self.logger.error(f"Error in Monitoring run loop: {str(e)}")
                    if hasattr(self.settings, 'DEBUG') and self.settings.DEBUG:
                        self.logger.exception(e)
                    await asyncio.sleep(5)  # Brief pause on error
            
        except asyncio.CancelledError:
            self.logger.info("Monitoring task cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Unhandled exception in Monitoring.run: {str(e)}", exc_info=True)
        finally:
            self.running = False
            self.logger.info("Monitoring run loop ended")

    async def stop(self):
        """Stops all monitoring tasks and cleans up resources."""
        self.logger.warning("Stopping Monitoring service...")
        self.running = False
        
        # Create a list of tasks to cancel
        tasks_to_cancel = list(self.monitoring_tasks.values())
        
        if tasks_to_cancel:
            self.logger.info(f"Cancelling {len(tasks_to_cancel)} active monitoring tasks...")
            for task in tasks_to_cancel:
                task.cancel()
            
            # Wait for all tasks to complete cancellation
            results = await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            for i, result in enumerate(results):
                 if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                      # Log errors that occurred during cancellation, except CancelledError itself
                      task_mint = list(self.monitoring_tasks.keys())[i] # Get corresponding mint (might be fragile)
                      self.logger.error(f"Error during cancellation of task for mint {task_mint}: {result}")
            self.logger.info("All active monitoring tasks have been processed for cancellation.")
        else:
            self.logger.info("No active monitoring tasks to cancel.")

        self.monitoring_tasks.clear()
        self.token_monitoring_data.clear()
        
        # Close DeltaCalculator if it has a close method
        if hasattr(self.delta_calculator, 'close'):
             self.logger.info("Closing DeltaCalculator resources...")
             await self.delta_calculator.close()

        self.logger.warning("Monitoring service stopped.")

class VolumeMonitor:
    """Monitors trading volume for specific tokens."""
    def __init__(self, db: TokenDatabase, settings: Settings, thresholds: Thresholds):
        self.db = db
        self.thresholds = thresholds
        self.logger = get_logger("VolumeMonitor")
        self.token_volumes: Dict[str, Dict[str, float]] = {}
        
    async def initialize(self) -> bool:
        """Initialize the VolumeMonitor.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            self.logger.info("Initializing VolumeMonitor")
            # Nothing special to initialize here, but keeping the pattern consistent
            self.logger.info("VolumeMonitor initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error initializing VolumeMonitor: {e}")
            # Still return True to allow application to continue
            return True
            
    async def close(self):
        """Close resources used by VolumeMonitor."""
        # No resources to close, but keeping the pattern consistent
        pass
        
    async def check_volume_spikes(self, mint: str) -> Dict:
        """Check for volume spikes across different timeframes."""
        try:
            # Get volume data for different timeframes
            volume_data = await self._get_volume_data(mint)
            
            # Analyze for spikes
            spikes = self._analyze_volume_spikes(volume_data)
            
            # Get historical context
            context = await self._get_historical_context(mint)
            
            return {
                'spikes': spikes,
                'context': context,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error checking volume spikes for {mint}: {e}")
            return {}
            
    async def _get_volume_data(self, mint: str) -> Dict:
        """Get volume data for different timeframes."""
        try:
            # Get volume deltas for different timeframes
            timeframes = ['5m', '15m', '1h', '6h', '24h']
            volume_data = {}
            
            for timeframe in timeframes:
                deltas = await self.db.get_token_deltas(
                    mint,
                    timeframe=f'{timeframe}_volume',
                    metric_type='volume'
                )
                
                if deltas:
                    volume_data[timeframe] = {
                        'current': deltas[0]['delta_value'],
                        'change': deltas[0]['delta_percentage'],
                        'timestamp': deltas[0]['timestamp']
                    }
                    
            return volume_data
            
        except Exception as e:
            self.logger.error(f"Error getting volume data: {e}")
            return {}
            
    def _analyze_volume_spikes(self, volume_data: Dict) -> List[Dict]:
        """Analyze volume data for spikes."""
        try:
            spikes = []
            
            for timeframe, data in volume_data.items():
                # Get threshold for this timeframe
                threshold = self._get_spike_threshold(timeframe)
                
                # Check if volume change exceeds threshold
                if abs(data['change']) > threshold:
                    spikes.append({
                        'timeframe': timeframe,
                        'change': data['change'],
                        'threshold': threshold,
                        'timestamp': data['timestamp']
                    })
                    
            return spikes
            
        except Exception as e:
            self.logger.error(f"Error analyzing volume spikes: {e}")
            return []
            
    def _get_spike_threshold(self, timeframe: str) -> float:
        """Get volume spike threshold for timeframe."""
        thresholds = {
            '5m': 200,  # 200% change
            '15m': 150,  # 150% change
            '1h': 100,   # 100% change
            '6h': 75,    # 75% change
            '24h': 50    # 50% change
        }
        return thresholds.get(timeframe, 100)
        
    async def _get_historical_context(self, mint: str) -> Dict:
        """Get historical context for volume analysis."""
        try:
            # Get last 24 hours of volume data
            historical_data = await self.db.get_token_deltas(
                mint,
                timeframe='24h_volume',
                metric_type='volume',
                limit=24
            )
            
            if not historical_data:
                return {}
                
            # Calculate average volume
            volumes = [d['delta_value'] for d in historical_data]
            avg_volume = sum(volumes) / len(volumes)
            
            # Calculate volume trend
            if len(volumes) >= 2:
                trend = (volumes[0] - volumes[-1]) / volumes[-1] * 100
            else:
                trend = 0
                
            return {
                'average_volume': avg_volume,
                'volume_trend': trend,
                'data_points': len(historical_data)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting historical context: {e}")
            return {}
            
    async def monitor_volume_trends(self, mint: str) -> Dict:
        """Monitor volume trends over time."""
        try:
            # Get volume data for different timeframes
            volume_data = await self._get_volume_data(mint)
            
            # Get historical context
            context = await self._get_historical_context(mint)
            
            # Analyze trends
            trends = self._analyze_volume_trends(volume_data, context)
            
            return {
                'trends': trends,
                'context': context,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error monitoring volume trends for {mint}: {e}")
            return {}
            
    def _analyze_volume_trends(self, volume_data: Dict, context: Dict) -> List[Dict]:
        """Analyze volume trends."""
        try:
            trends = []
            
            for timeframe, data in volume_data.items():
                # Get trend direction
                direction = 'increasing' if data['change'] > 0 else 'decreasing'
                
                # Get trend strength
                strength = self._calculate_trend_strength(data['change'], timeframe)
                
                trends.append({
                    'timeframe': timeframe,
                    'direction': direction,
                    'strength': strength,
                    'change': data['change'],
                    'timestamp': data['timestamp']
                })
                
            return trends
            
        except Exception as e:
            self.logger.error(f"Error analyzing volume trends: {e}")
            return []
            
    def _calculate_trend_strength(self, change: float, timeframe: str) -> str:
        """Calculate trend strength based on percentage change."""
        thresholds = {
            '5m': {'weak': 50, 'moderate': 100, 'strong': 200},
            '15m': {'weak': 30, 'moderate': 75, 'strong': 150},
            '1h': {'weak': 20, 'moderate': 50, 'strong': 100},
            '6h': {'weak': 15, 'moderate': 40, 'strong': 75},
            '24h': {'weak': 10, 'moderate': 25, 'strong': 50}
        }
        
        tf_thresholds = thresholds.get(timeframe, thresholds['1h'])
        abs_change = abs(change)
        
        if abs_change >= tf_thresholds['strong']:
            return 'strong'
        elif abs_change >= tf_thresholds['moderate']:
            return 'moderate'
        else:
            return 'weak' 