"""
Blockchain-specific logging configuration
Separates blockchain listener logs from main application logs
"""
import logging
import logging.handlers
from pathlib import Path
import os
import time
from typing import Optional

def setup_blockchain_logger(name: str = "BlockchainListener") -> logging.Logger:
    """
    Set up a dedicated logger for blockchain operations with separate log file
    
    Args:
        name: Logger name
        
    Returns:
        Configured logger instance
    """
    
    # Create outputs directory if it doesn't exist
    outputs_dir = Path("outputs")
    outputs_dir.mkdir(exist_ok=True)
    
    # Create dedicated blockchain logger
    blockchain_logger = logging.getLogger(name)
    blockchain_logger.setLevel(logging.INFO)
    
    # Prevent duplicate handlers
    if blockchain_logger.handlers:
        return blockchain_logger
    
    # Create dedicated blockchain log file
    blockchain_log_file = outputs_dir / "blockchain_listener.log"
    
    # File handler for blockchain events
    file_handler = logging.handlers.RotatingFileHandler(
        blockchain_log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # Console handler for critical blockchain events only
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    
    # Detailed formatter for blockchain events
    blockchain_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(blockchain_formatter)
    console_handler.setFormatter(blockchain_formatter)
    
    blockchain_logger.addHandler(file_handler)
    blockchain_logger.addHandler(console_handler)
    
    # Prevent propagation to root logger to avoid duplicate logs
    blockchain_logger.propagate = False
    
    return blockchain_logger

def log_connection_event(logger: logging.Logger, event_type: str, details: str):
    """Log blockchain connection events with standardized format"""
    event_symbols = {
        "CONNECTION": "🔌",
        "ERROR": "❌", 
        "WARNING": "⚠️",
        "SUCCESS": "✅",
        "PRICE": "💰",
        "SWAP": "🔄",
        "FALLBACK": "🔄"
    }
    
    symbol = event_symbols.get(event_type, "📡")
    logger.info(f"{symbol} {event_type}: {details}")

def log_price_event(logger: logging.Logger, symbol: str, price_sol: float, source: str, price_usd: Optional[float] = None):
    """
    Log a price event with SOL as primary and USD as secondary.
    
    Args:
        logger: Logger instance
        symbol: Token symbol
        price_sol: Price in SOL (primary)
        source: Price source identifier
        price_usd: Price in USD (secondary, optional)
    """
    try:
        # Format SOL price
        sol_price_str = f"{price_sol:.8f} SOL"
        
        # Format USD price if available
        usd_price_str = f"(${price_usd:.6f})" if price_usd else ""
        
        # Log with both prices
        logger.info(f"💰 PRICE UPDATE: {symbol} = {sol_price_str} {usd_price_str} (source: {source})")
        
    except Exception as e:
        logger.error(f"Error logging price event: {e}")

def log_swap_event(logger: logging.Logger, symbol: str, amount: float, price_sol: float, dex: str, price_usd: Optional[float] = None):
    """
    Log a swap event with SOL as primary price.
    
    Args:
        logger: Logger instance
        symbol: Token symbol
        amount: Swap amount
        price_sol: Price in SOL (primary)
        dex: DEX name
        price_usd: Price in USD (secondary, optional)
    """
    try:
        # Format SOL price
        sol_price_str = f"{price_sol:.8f} SOL"
        
        # Format USD price if available
        usd_price_str = f"(${price_usd:.6f})" if price_usd else ""
        
        # Log swap with both prices
        logger.info(f"🔄 SWAP: {amount:.4f} {symbol} @ {sol_price_str} {usd_price_str} on {dex}")
        
    except Exception as e:
        logger.error(f"Error logging swap event: {e}")

def setup_price_monitoring_logger(name: str = "PriceMonitoring") -> logging.Logger:
    """
    Set up dedicated logger for price monitoring that writes to outputs/price_updates.log
    
    Args:
        name: Logger name
        
    Returns:
        logging.Logger: Configured logger instance for price events
    """
    
    # Create outputs directory if it doesn't exist
    outputs_dir = Path("outputs")
    outputs_dir.mkdir(exist_ok=True)
    
    # Create dedicated price monitoring logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Create dedicated price updates log file
    price_updates_log_file = outputs_dir / "price_updates.log"
    
    # File handler for price updates
    file_handler = logging.handlers.RotatingFileHandler(
        price_updates_log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # Simple formatter for price updates - clean format every 60s
    price_formatter = logging.Formatter(
        '%(asctime)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    file_handler.setFormatter(price_formatter)
    logger.addHandler(file_handler)
    
    # This logger does NOT propagate to avoid duplicate logs in main log
    logger.propagate = False
    
    return logger

class PriceMonitoringAggregator:
    """
    Aggregates price monitoring data and logs blockchain vs DexScreener price comparison every 60 seconds to dedicated price_monitor.log
    """
    
    def __init__(self, logger: logging.Logger, price_monitor=None):
        self.logger = logger
        self.price_monitor = price_monitor  # Reference to get SOL price
        self.price_data = {}  # mint -> {'blockchain': price, 'dexscreener': price, 'last_update': timestamp}
        self.last_log_time = time.time()
        self.log_interval = 60  # 60 seconds
        
    async def get_sol_price_usd(self) -> float:
        """Get current SOL price in USD"""
        try:
            if self.price_monitor and hasattr(self.price_monitor, 'get_sol_price'):
                sol_price = await self.price_monitor.get_sol_price()
                if sol_price and sol_price > 0:
                    return sol_price
            
            # Fallback: try to get SOL price via token lookup
            if self.price_monitor and hasattr(self.price_monitor, 'get_current_price_usd'):
                sol_mint = "So11111111111111111111111111111111111111112"
                sol_price = await self.price_monitor.get_current_price_usd(sol_mint, max_age_seconds=300)
                if sol_price and sol_price > 0:
                    return sol_price
                    
        except Exception as e:
            self.logger.debug(f"Error getting SOL price: {e}")
        
        # Final fallback
        return 150.0  # Approximate SOL price
        
    def get_sol_price_usd_sync(self) -> float:
        """Get current SOL price in USD (synchronous version)"""
        try:
            # Try to get cached SOL price if available
            if hasattr(self, '_cached_sol_price') and hasattr(self, '_sol_price_cache_time'):
                if time.time() - self._sol_price_cache_time < 300:  # 5 minute cache
                    return self._cached_sol_price
            
            # For now, return fallback price
            # The async version should be called from elsewhere to update the cache
            return getattr(self, '_cached_sol_price', 150.0)
            
        except Exception:
            return 150.0  # Fallback SOL price
    
    async def update_sol_price_cache(self):
        """Update the cached SOL price asynchronously"""
        try:
            sol_price = await self.get_sol_price_usd()
            self._cached_sol_price = sol_price
            self._sol_price_cache_time = time.time()
        except Exception as e:
            self.logger.debug(f"Error updating SOL price cache: {e}")
        
    def record_price_update(self, mint: str, price: float, source: str, dex_id: str = None):
        """Record a price update for blockchain vs API comparison"""
        current_time = time.time()
        
        # Initialize mint entry if not exists
        if mint not in self.price_data:
            self.price_data[mint] = {
                'blockchain': None,
                'dexscreener': None,
                'last_update': current_time,
                'dex_id': dex_id
            }
        
        # Update the appropriate price source
        if source.lower() in ['blockchain', 'blockchain_listener', 'realtime']:
            self.price_data[mint]['blockchain'] = price
        elif source.lower() in ['dexscreener', 'api', 'price_monitor']:
            self.price_data[mint]['dexscreener'] = price
        
        self.price_data[mint]['last_update'] = current_time
        if dex_id:
            self.price_data[mint]['dex_id'] = dex_id
        
        # Check if it's time to log comparison
        if current_time - self.last_log_time >= self.log_interval:
            self._log_price_comparison()
            
    def _log_price_comparison(self):
        """Log blockchain vs DexScreener price comparison to dedicated price_monitor.log with improved table format"""
        current_time = time.time()
        
        if not self.price_data:
            self.logger.info("NO PRICE DATA AVAILABLE")
            self.last_log_time = current_time
            return
        
        # Header for readability
        self.logger.info("="*120)
        self.logger.info("                           PRICE COMPARISON REPORT (60s interval)")
        self.logger.info("="*120)
        
        # Table header
        header = f"{'TOKEN':<8} {'DIFF%':<8} {'BlockchainSOL':<15} {'DexscreenerSOL':<16} {'BlockchainUSD':<14} {'DexscreenerUSD':<15} {'MINT':<44}"
        self.logger.info(header)
        self.logger.info("-" * 120)
        
        active_tokens = 0
        tokens_with_both_prices = 0
        red_entries = 0
        total_entries = 0
        
        for mint, data in list(self.price_data.items()):
            # Only include recent updates (within last 2 intervals)
            if current_time - data.get('last_update', 0) > (self.log_interval * 2):
                continue
                
            active_tokens += 1
            blockchain_price = data.get('blockchain')
            dexscreener_price = data.get('dexscreener')
            
            if blockchain_price and dexscreener_price:
                tokens_with_both_prices += 1
                total_entries += 1
                
                # Get SOL price for conversions
                sol_price_usd = self.get_sol_price_usd_sync()
                
                # Extract actual price values
                bc_price_sol = blockchain_price if isinstance(blockchain_price, (int, float)) else blockchain_price.get('price', 0)
                dx_price_usd = dexscreener_price if isinstance(dexscreener_price, (int, float)) else dexscreener_price.get('price', 0)
                
                # Convert DexScreener USD to SOL for comparison
                dx_price_sol = dx_price_usd / sol_price_usd if sol_price_usd > 0 and dx_price_usd > 0 else 0
                
                # Calculate USD prices
                bc_price_usd = bc_price_sol * sol_price_usd if bc_price_sol > 0 and sol_price_usd > 0 else 0
                
                # Calculate percentage difference (SOL only)
                if dx_price_sol > 0 and bc_price_sol > 0:
                    diff_percent = ((bc_price_sol - dx_price_sol) / dx_price_sol) * 100
                else:
                    diff_percent = 0
                
                # Determine color coding based on absolute difference
                abs_diff = abs(diff_percent)
                if abs_diff > 3:
                    color_code = "🔴"  # Red for >3%
                    red_entries += 1
                elif abs_diff > 1:
                    color_code = "🟡"  # Yellow for >1%
                else:
                    color_code = "✅"  # Green for <=1%
                
                # Get token symbol (first 8 chars of mint if no symbol available)
                token_symbol = mint[:8] + "..."
                
                # Format the row
                row = (f"{color_code} {token_symbol:<6} "
                       f"{diff_percent:>6.2f}% "
                       f"{bc_price_sol:>14.9f} "
                       f"{dx_price_sol:>15.9f} "
                       f"${bc_price_usd:>12.6f} "
                       f"${dx_price_usd:>13.6f} "
                       f"{mint}")
                
                self.logger.info(row)
        
        # Summary footer
        self.logger.info("-" * 120)
        red_percentage = (red_entries / total_entries * 100) if total_entries > 0 else 0
        
        summary = (f"SUMMARY: {active_tokens} active tokens | {tokens_with_both_prices} with both prices | "
                  f"{red_entries}/{total_entries} red entries ({red_percentage:.1f}%)")
        
        if red_percentage > 5:
            summary += " ⚠️  WARNING: >5% red entries - CHECK CODE!"
            
        self.logger.info(summary)
        
        # SOL price info
        sol_price = self.get_sol_price_usd_sync()
        self.logger.info(f"SOL Price: ${sol_price:.2f} USD | Next update in 60s")
        self.logger.info("="*120)
        
        self.last_log_time = current_time 