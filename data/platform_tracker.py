"""
Platform Tracking Module
"""
import logging
from typing import Dict, Optional, List, Any, Set, Tuple, TYPE_CHECKING
from datetime import datetime, timezone, timedelta
import asyncio

from construct import this
from config.dexscreener_api import DexScreenerAPI
from data.token_database import TokenDatabase
from data.monitoring import VolumeMonitor
from utils.logger import get_logger
from solana.rpc.async_api import AsyncClient
from filters.bonding_curve import BondingCurveCalculator
from decimal import Decimal
import numpy as np
import pandas as pd
import httpx
import json
import time
from enum import Enum, auto
from collections import deque
from config.thresholds import Thresholds
from data.price_monitor import PriceMonitor

# Use TYPE_CHECKING block for imports needed *only* for type hints
if TYPE_CHECKING:
    from data.token_database import TokenDatabase # Keep existing necessary hints
    from config.settings import Settings
    from config.thresholds import Thresholds
    from solana.rpc.async_api import AsyncClient
    # Remove the 'pass' if imports are added

# Get logger for this module
logger = get_logger(__name__)

# Constants for analysis
ANALYSIS_INTERVAL = timedelta(minutes=5) # How often to run platform analysis
RECENT_ACTIVITY_WINDOW = timedelta(hours=1) # Window for 'recent' activity
VOLUME_SPIKE_FACTOR = 2.0 # Threshold for detecting volume spikes
PRICE_SPIKE_FACTOR = 1.5 # Threshold for detecting price spikes

class PlatformTracker:
    """Tracks token platforms and detects migrations between DEXes."""
    
    def __init__(self, db: 'TokenDatabase', settings: 'Settings', thresholds: 'Thresholds', solana_client: 'AsyncClient'):
        """Initialize the PlatformTracker."""
        self.db = db
        self.settings = settings
        self.thresholds = thresholds
        self.solana_client = solana_client
        self.logger = get_logger("PlatformTracker")
        
        # Initialize sub-components needed by PlatformTracker
        # self.price_monitor = PriceMonitor(settings=self.settings, db=self.db) # Removed - PlatformTracker likely doesn't need its own PriceMonitor
        # Pass thresholds when creating VolumeMonitor
        self.volume_monitor = VolumeMonitor(self.db, settings=self.settings, thresholds=self.thresholds)
        self.dexscreener = DexScreenerAPI(settings=self.settings)
        self.bonding_curve_calculator = None
        
        # Platform identifiers
        self.PUMPFUN_DEX_ID = "pump"
        self.PUMPSWAP_DEX_ID = "pumpswap"
        self.RAYDIUM_DEX_ID = "raydium"
        
        # Bonding curve thresholds - get from settings
        self.BONDING_CURVE_THRESHOLD = getattr(self.settings, 'MIN_LIQUIDITY', 1000)  # Use MIN_LIQUIDITY from env
        self.MIGRATION_CHECK_INTERVAL = 300  # 5 minutes
        
        # Use settings for intervals if available, otherwise use constants
        self.analysis_interval_seconds = getattr(self.settings, 'ANALYSIS_INTERVAL', ANALYSIS_INTERVAL.total_seconds()) if self.settings else ANALYSIS_INTERVAL.total_seconds()
        self.recent_activity_window = RECENT_ACTIVITY_WINDOW
        self.volume_spike_factor = getattr(self.settings, 'VOLUME_SPIKE_THRESHOLD', VOLUME_SPIKE_FACTOR) if self.settings else VOLUME_SPIKE_FACTOR
        self.price_spike_factor = getattr(self.settings, 'PRICE_SPIKE_THRESHOLD', PRICE_SPIKE_FACTOR) if self.settings else PRICE_SPIKE_FACTOR

        self.last_analysis_time: Optional[datetime] = None
        self.platform_metrics: Dict[str, Any] = {}
        self.recent_trends: Deque[Dict[str, Any]] = deque(maxlen=12) # Store last hour (12 * 5 mins)
        self.sol_price_usd: Optional[float] = None
        
        logger.info("PlatformTracker initialized")
        
    async def initialize(self) -> bool:
        """
        Initialize platform tracker and its dependencies.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            logger.info("Initializing PlatformTracker")
            
            # Initialize DexScreener API
            if not await self.dexscreener.initialize():
                logger.error("Failed to initialize DexScreener API")
                return False
            
            # Initialize the bonding curve calculator if we have a Solana client
            if self.solana_client:
                self.bonding_curve_calculator = BondingCurveCalculator(self.solana_client, self.settings)
                logger.info("Initialized BondingCurveCalculator")
                
            # Initialize VolumeMonitor if it has initialize method
            if hasattr(self.volume_monitor, 'initialize'):
                if not await self.volume_monitor.initialize():
                    logger.error("Failed to initialize VolumeMonitor")
                    return False
                    
            logger.info("PlatformTracker initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing PlatformTracker: {e}")
            # Still return True to allow application to continue
            return True
            
    async def close(self):
        """
        Close resources used by PlatformTracker.
        """
        try:
            await self.dexscreener.close()
            
            # Close VolumeMonitor if it has close method
            if hasattr(self.volume_monitor, 'close'):
                await self.volume_monitor.close()
                
            logger.info("PlatformTracker resources closed")
        except Exception as e:
            logger.error(f"Error closing PlatformTracker resources: {e}")
    
    async def track_platform_status(self, token_data: Dict) -> Dict:
        """
        Track the current platform status of a token and detect any migrations.
        
        Args:
            token_data: Dictionary containing token information including mint address
            
        Returns:
            Dict containing platform status and migration information
        """
        try:
            mint = token_data.get("mint")
            if not mint:
                self.logger.error("No mint address provided for platform tracking")
                return {}
                
            # Get current platform data from DexScreener
            pairs_data = await self.dexscreener.get_token_details(mint)
            
            # Handle case where pairs_data is a list
            if isinstance(pairs_data, list):
                pairs = pairs_data
            else:
                pairs = pairs_data.get("pairs", []) if pairs_data else []
                
            if not pairs:
                return {}
                
            # Analyze current platform status
            current_platforms = self._analyze_platforms(pairs)
            
            # Check for migrations if token meets bonding curve threshold
            if self._meets_bonding_curve_threshold(token_data):
                migrations = await self._check_for_migrations(mint, current_platforms)
            else:
                migrations = []
                
            # Update database with platform status
            await self._update_platform_status(mint, current_platforms, migrations)
            
            return {
                "current_platforms": current_platforms,
                "migrations": migrations,
                "last_checked": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error tracking platform status for token {mint}: {e}")
            return {}
            
    def _analyze_platforms(self, pairs: List[Dict]) -> List[Dict]:
        """
        Analyze pairs data to determine current platform status.
        
        Args:
            pairs: List of pairs data from DexScreener
            
        Returns:
            List of platform status dictionaries
        """
        platforms = []
        
        for pair in pairs:
            dex_id = pair.get("dexId")
            if not dex_id:
                continue
                
            platform_data = {
                "dex_id": dex_id,
                "pair_address": pair.get("pairAddress"),
                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                "price_usd": float(pair.get("priceUsd", 0)),
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            platforms.append(platform_data)
            
        return platforms
        
    def _meets_bonding_curve_threshold(self, token_data: Dict) -> bool:
        """
        Check if token meets the bonding curve threshold for migration checks.
        
        Args:
            token_data: Token data including liquidity information
            
        Returns:
            bool indicating if threshold is met
        """
        try:
            liquidity = float(token_data.get("liquidityUsd", 0))
            return liquidity >= self.BONDING_CURVE_THRESHOLD
        except (ValueError, TypeError):
            return False
            
    async def _check_for_migrations(self, mint: str, current_platforms: List[Dict]) -> List[Dict]:
        """
        Check for platform migrations when bonding curve threshold is met.
        
        Args:
            mint: Token mint address
            current_platforms: Current platform status
            
        Returns:
            List of detected migrations
        """
        migrations = []
        
        # Get historical platform data from database
        historical_data = await self.db.get_token_platform_history(mint)
        if not historical_data:
            return migrations
            
        # Check for migrations from PumpFun to other platforms
        for platform in current_platforms:
            if platform["dex_id"] in [self.PUMPSWAP_DEX_ID, self.RAYDIUM_DEX_ID]:
                # Verify this is a new platform for the token
                if not any(h["dex_id"] == platform["dex_id"] for h in historical_data):
                    migration = {
                        "from_dex": self.PUMPFUN_DEX_ID,
                        "to_dex": platform["dex_id"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "liquidity_usd": platform["liquidity_usd"],
                        "volume_24h": platform["volume_24h"]
                    }
                    migrations.append(migration)
                    
        return migrations
        
    async def _update_platform_status(self, mint: str, current_platforms: List[Dict], migrations: List[Dict]):
        """
        Update platform status in database.
        
        Args:
            mint: Token mint address
            current_platforms: Current platform status
            migrations: Detected migrations
        """
        try:
            # Update current platform status
            await self.db.update_token_platforms(mint, current_platforms)
            
            # Record migrations if any
            if migrations:
                await self.db.record_platform_migrations(mint, migrations)
                
        except Exception as e:
            self.logger.error(f"Error updating platform status for token {mint}: {e}")
            
    async def monitor_platform_changes(self, token_data: Dict):
        """
        Continuously monitor platform changes for a token.
        
        Args:
            token_data: Token data to monitor
        """
        while True:
            try:
                # Track current platform status
                status = await self.track_platform_status(token_data)
                
                # Log any migrations
                if status.get("migrations"):
                    for migration in status["migrations"]:
                        self.logger.info(
                            f"Platform migration detected for token {token_data.get('mint')}: "
                            f"{migration['from_dex']} -> {migration['to_dex']}"
                        )
                        
                # Wait before next check
                await asyncio.sleep(self.MIGRATION_CHECK_INTERVAL)
                
            except Exception as e:
                self.logger.error(f"Error in platform monitoring: {e}")
                await asyncio.sleep(self.MIGRATION_CHECK_INTERVAL)

    async def get_platform_data(self, mint: str) -> List[Dict]:
        """Get data from each DEX for a token."""
        try:
            # Get platform data from database
            platforms = await self.db.get_token_platform_history(mint)
            
            # Get current data from each DEX
            current_data = await self._fetch_current_dex_data(mint)
            
            # Update database with new data
            await self.db.update_token_platforms(mint, current_data)
            
            # Check for platform migrations
            migrations = self._detect_platform_migrations(platforms, current_data)
            if migrations:
                await self.db.record_platform_migrations(mint, migrations)
                
            return current_data
            
        except Exception as e:
            logger.error(f"Error getting platform data for {mint}: {e}")
            return []
            
    async def _fetch_current_dex_data(self, mint: str) -> List[Dict]:
        """Fetch current data from each DEX."""
        try:
            # Get data from each supported DEX
            dex_data = []
            
            # Raydium
            raydium_data = await self._get_raydium_data(mint)
            if raydium_data:
                dex_data.append(raydium_data)
                
            # Orca
            orca_data = await self._get_orca_data(mint)
            if orca_data:
                dex_data.append(orca_data)
                
            # Jupiter
            jupiter_data = await self._get_jupiter_data(mint)
            if jupiter_data:
                dex_data.append(jupiter_data)
                
            return dex_data
            
        except Exception as e:
            logger.error(f"Error fetching DEX data: {e}")
            return []
            
    async def _get_raydium_data(self, mint: str) -> Optional[Dict]:
        """Get token data from Raydium."""
        try:
            # Use Raydium API to get data
            # This is a placeholder - implement actual API call
            return {
                'dex_id': 'raydium',
                'pair_address': f'raydium_{mint}',
                'liquidity_usd': 0,
                'volume_24h': 0,
                'price_usd': 0
            }
        except Exception as e:
            logger.error(f"Error getting Raydium data: {e}")
            return None
            
    async def _get_orca_data(self, mint: str) -> Optional[Dict]:
        """Get token data from Orca."""
        try:
            # Use Orca API to get data
            # This is a placeholder - implement actual API call
            return {
                'dex_id': 'orca',
                'pair_address': f'orca_{mint}',
                'liquidity_usd': 0,
                'volume_24h': 0,
                'price_usd': 0
            }
        except Exception as e:
            logger.error(f"Error getting Orca data: {e}")
            return None
            
    async def _get_jupiter_data(self, mint: str) -> Optional[Dict]:
        """Get token data from Jupiter."""
        try:
            # Use Jupiter API to get data
            # This is a placeholder - implement actual API call
            return {
                'dex_id': 'jupiter',
                'pair_address': f'jupiter_{mint}',
                'liquidity_usd': 0,
                'volume_24h': 0,
                'price_usd': 0
            }
        except Exception as e:
            logger.error(f"Error getting Jupiter data: {e}")
            return None
            
    def _detect_platform_migrations(self, historical_data: List[Dict], current_data: List[Dict]) -> List[Dict]:
        """Detect if token has migrated between platforms."""
        try:
            migrations = []
            
            # Get historical and current DEX IDs
            historical_dexes = {p['dex_id'] for p in historical_data}
            current_dexes = {p['dex_id'] for p in current_data}
            
            # Find new DEXes (migrations to)
            new_dexes = current_dexes - historical_dexes
            
            # Find old DEXes (migrations from)
            old_dexes = historical_dexes - current_dexes
            
            # Record migrations
            for old_dex in old_dexes:
                for new_dex in new_dexes:
                    # Get liquidity and volume data
                    old_data = next(p for p in historical_data if p['dex_id'] == old_dex)
                    new_data = next(p for p in current_data if p['dex_id'] == new_dex)
                    
                    migrations.append({
                        'from_dex': old_dex,
                        'to_dex': new_dex,
                        'liquidity_usd': new_data['liquidity_usd'],
                        'volume_24h': new_data['volume_24h']
                    })
                    
            return migrations
            
        except Exception as e:
            logger.error(f"Error detecting platform migrations: {e}")
            return []
            
    async def monitor_platform_changes(self, mint: str) -> Dict:
        """Monitor for significant changes in platform distribution."""
        try:
            # Get current platform data
            current_data = await self.get_platform_data(mint)
            
            # Calculate distribution
            distribution = self._calculate_platform_distribution(current_data)
            
            # Check for significant changes
            changes = await this._check_distribution_changes(mint, distribution)
            
            return {
                'distribution': distribution,
                'changes': changes
            }
            
        except Exception as e:
            logger.error(f"Error monitoring platform changes: {e}")
            return {}
            
    def _calculate_platform_distribution(self, platform_data: List[Dict]) -> Dict:
        """Calculate token's distribution across platforms."""
        try:
            distribution = {}
            total_liquidity = sum(p.get('liquidity_usd', 0) for p in platform_data)
            
            if total_liquidity == 0:
                return {}
                
            for platform in platform_data:
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
            
    async def _check_distribution_changes(self, mint: str, current_distribution: Dict) -> List[Dict]:
        """Check for significant changes in platform distribution."""
        try:
            changes = []
            
            # Get historical distribution
            historical_data = await this.db.get_token_platform_history(mint)
            historical_distribution = this._calculate_platform_distribution(historical_data)
            
            # Compare distributions
            for dex_id, current_data in current_distribution.items():
                if dex_id in historical_distribution:
                    historical_data = historical_distribution[dex_id]
                    
                    # Check for significant changes
                    if abs(current_data['percentage'] - historical_data['percentage']) > 20:  # 20% threshold
                        changes.append({
                            'dex_id': dex_id,
                            'old_percentage': historical_data['percentage'],
                            'new_percentage': current_data['percentage'],
                            'change': current_data['percentage'] - historical_data['percentage']
                        })
                        
            return changes
            
        except Exception as e:
            logger.error(f"Error checking distribution changes: {e}")
            return []
            
    async def get_bonding_curve_metrics(self, mint_address: str, sol_price_usd: float = 0) -> Dict:
        """
        Get bonding curve metrics for a token including progress percentage and migration prediction.
        
        Args:
            mint_address: Token mint address
            sol_price_usd: Current SOL price in USD (optional, will be fetched if not provided)
            
        Returns:
            Dict: Bonding curve metrics
        """
        try:
            # Ensure we have a bonding curve calculator
            if not self.bonding_curve_calculator:
                if not self.solana_client:
                    self.logger.error("Cannot get bonding curve metrics: No Solana client available")
                    return {"status": "error", "message": "No Solana client available"}
                self.bonding_curve_calculator = BondingCurveCalculator(self.solana_client, self.settings)
            
            # Fetch SOL price if not provided
            if sol_price_usd <= 0:
                # Try to get SOL price from DexScreener
                sol_price_data = await self.dexscreener.get_token_details("So11111111111111111111111111111111111111112")
                if sol_price_data and isinstance(sol_price_data, dict) and "pairs" in sol_price_data:
                    sol_pairs = sol_price_data.get("pairs", [])
                    if sol_pairs:
                        sol_price_usd = float(sol_pairs[0].get("priceUsd", 0))
                        self.logger.info(f"Fetched SOL price: ${sol_price_usd}")
                
                # Use default price if fetch failed
                if sol_price_usd <= 0:
                    sol_price_usd = 150.0  # Default SOL price as fallback
                    self.logger.warning(f"Using default SOL price: ${sol_price_usd}")
            
            # Get bonding curve metrics
            metrics = await self.bonding_curve_calculator.get_bonding_curve_metrics(mint_address, sol_price_usd)
            
            # Log important metrics
            if metrics.get("status") == "success":
                self.logger.info(
                    f"Bonding curve metrics for {mint_address}: "
                    f"Progress {metrics.get('progress_percent', 0):.2f}%, "
                    f"Migration likelihood: {metrics.get('migration_likelihood', 'UNKNOWN')}, "
                    f"Time to migration: {metrics.get('time_to_migration', 'UNKNOWN')}"
                )
                
            return metrics
                
        except Exception as e:
            self.logger.error(f"Error getting bonding curve metrics for {mint_address}: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
            
    async def is_migration_imminent(self, mint_address: str) -> bool:
        """
        Check if token migration is imminent (>95% progress).
        
        Args:
            mint_address: Token mint address
            
        Returns:
            bool: True if migration is imminent, False otherwise
        """
        try:
            metrics = await self.get_bonding_curve_metrics(mint_address)
            if metrics.get("status") == "success":
                progress = metrics.get("progress_percent", 0)
                return progress >= 95
            return False
        except Exception as e:
            self.logger.error(f"Error checking if migration is imminent: {e}")
            return False

    async def update_platform_metrics(self):
        """Periodically fetch and analyze platform-wide data."""
        now = datetime.now(timezone.utc)
        if self.last_analysis_time and now - self.last_analysis_time < timedelta(seconds=self.analysis_interval_seconds):
            # logger.debug("Skipping platform analysis, interval not reached.")
            return

        logger.info("Updating platform metrics...")
        self.last_analysis_time = now

        try:
            # Example metrics: total volume, liquidity, new pairs, transaction count
            # These would typically involve querying the database or external APIs
            # Placeholder values for now
            total_volume_24h = await self.db.get_total_volume_24h() if self.db else 1000000
            total_liquidity = await self.db.get_total_liquidity() if self.db else 5000000
            new_pairs_1h = await self.db.get_new_pairs_count(window=timedelta(hours=1)) if self.db else 10
            active_pairs = await self.db.get_active_pairs_count() if self.db else 100

            # Calculate trends or anomalies
            current_metrics = {
                "timestamp": now.isoformat(),
                "total_volume_24h": total_volume_24h,
                "total_liquidity": total_liquidity,
                "new_pairs_1h": new_pairs_1h,
                "active_pairs": active_pairs
            }
            self.platform_metrics = current_metrics
            self.recent_trends.append(current_metrics)

            self._analyze_trends()
            logger.info(f"Platform metrics updated: {self.platform_metrics}")

        except Exception as e:
            logger.error(f"Error updating platform metrics: {e}", exc_info=True)

    def _analyze_trends(self):
        """Analyze recent trends in platform metrics."""
        if len(self.recent_trends) < 2:
            return # Not enough data to analyze trends

        # Example: Check for significant drops or spikes
        latest = self.recent_trends[-1]
        previous = self.recent_trends[-2]

        # Volume spike/drop
        if previous['total_volume_24h'] > 0:
            volume_change = latest['total_volume_24h'] / previous['total_volume_24h']
            if volume_change > self.volume_spike_factor:
                logger.warning(f"Significant platform volume spike detected! Factor: {volume_change:.2f}")
            elif volume_change < (1 / self.volume_spike_factor):
                 logger.warning(f"Significant platform volume drop detected! Factor: {volume_change:.2f}")

        # Add more trend analysis (e.g., liquidity changes, rate of new pairs)

    def get_platform_status(self) -> Dict[str, Any]:
        """Return the latest platform metrics and status."""
        # Can add more status flags based on analysis (e.g., 'high_volatility')
        return {
            "status": "operational", # Basic status
            "last_updated": self.last_analysis_time.isoformat() if self.last_analysis_time else None,
            "metrics": self.platform_metrics
        } 

    async def close(self):
        self.logger.info("Closing PlatformTracker resources...")
        if hasattr(self, 'dexscreener') and self.dexscreener:
            await self.dexscreener.close()
            self.logger.info("DexScreenerAPI closed in PlatformTracker.")
        # Add other cleanup if necessary (e.g., VolumeMonitor if it has a close method)
        if hasattr(self, 'volume_monitor') and self.volume_monitor and hasattr(self.volume_monitor, 'close') and callable(self.volume_monitor.close):
            try:
                await self.volume_monitor.close() # Assuming VolumeMonitor might have an async close
                self.logger.info("VolumeMonitor closed in PlatformTracker.")
            except Exception as e:
                self.logger.error(f"Error closing VolumeMonitor in PlatformTracker: {e}")
        self.logger.info("PlatformTracker closed.") 