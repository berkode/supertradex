#!/usr/bin/env python3
"""
Controlled SuperTradeX Main Script with Comprehensive Logging
Runs for a specified duration and logs:
- New tokens added to database
- Monitored tokens and their prices (updated every 1 minute)
- Traded tokens, prices, and trades (updated every 1 minute)
"""
import sys
import asyncio
import time
import logging
import json
from pathlib import Path
from datetime import datetime, timezone
import signal
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

# Add project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configuration imports
from config import Settings
from config.logging_config import LoggingConfig

# Core component imports
from data.token_database import TokenDatabase, Token
from data.market_data import MarketData
from data.price_monitor import PriceMonitor
from data.token_scanner import TokenScanner
from strategies.paper_trading import PaperTrading
from strategies.entry_exit import EntryExitStrategy
from utils.logger import get_logger

@dataclass
class TokenPriceLog:
    """Data structure for logging token prices"""
    timestamp: str
    symbol: str
    mint: str
    price_sol: Optional[float]
    price_usd: Optional[float]
    source: str
    volume_24h: Optional[float]
    market_cap: Optional[float]

@dataclass
class TradeLog:
    """Data structure for logging trades"""
    timestamp: str
    symbol: str
    mint: str
    action: str  # 'BUY' or 'SELL'
    amount_sol: float
    price_sol: float
    total_value_sol: float
    pnl_sol: Optional[float]
    strategy: str

class ControlledMainLogger:
    """Enhanced logging system for controlled main execution"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create timestamped log files
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.new_tokens_log = self.log_dir / f"new_tokens_{timestamp}.json"
        self.price_monitor_log = self.log_dir / f"price_monitor_{timestamp}.json"
        self.trades_log = self.log_dir / f"trades_{timestamp}.json"
        self.main_log = self.log_dir / f"main_execution_{timestamp}.log"
        
        # Initialize log files
        self._init_log_files()
        
        # Setup main logger
        self.logger = self._setup_main_logger()
        
        # Tracking sets
        self.known_tokens = set()
        self.last_price_update = {}
        self.trade_count = 0
        
    def _init_log_files(self):
        """Initialize JSON log files with empty arrays"""
        for log_file in [self.new_tokens_log, self.price_monitor_log, self.trades_log]:
            with open(log_file, 'w') as f:
                json.dump([], f)
    
    def _setup_main_logger(self):
        """Setup main execution logger"""
        logger = logging.getLogger("ControlledMain")
        logger.setLevel(logging.INFO)
        
        # File handler
        file_handler = logging.FileHandler(self.main_log)
        file_handler.setLevel(logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(name)s | %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def log_new_token(self, token: Token):
        """Log a new token discovered in the database"""
        if token.mint not in self.known_tokens:
            self.known_tokens.add(token.mint)
            
            token_data = {
                "timestamp": datetime.now().isoformat(),
                "symbol": token.symbol,
                "mint": token.mint,
                "name": token.name,
                "dex_id": token.dex_id,
                "pair_address": token.pair_address,
                "volume_24h": token.volume_24h,
                "market_cap": token.market_cap,
                "liquidity": token.liquidity,
                "rugcheck_score": token.rugcheck_score,
                "status": token.status
            }
            
            # Append to new tokens log
            self._append_to_json_log(self.new_tokens_log, token_data)
            
            self.logger.info(f"🆕 NEW TOKEN: {token.symbol} ({token.mint[:8]}...) | "
                           f"Vol: ${token.volume_24h:,.0f} | "
                           f"MC: ${token.market_cap:,.0f} | "
                           f"Liq: ${token.liquidity:,.0f} | "
                           f"RCS: {token.rugcheck_score}")
    
    def log_price_update(self, token_price: TokenPriceLog):
        """Log a price update for a monitored token"""
        # Append to price monitor log
        self._append_to_json_log(self.price_monitor_log, asdict(token_price))
        
        self.logger.info(f"💰 PRICE: {token_price.symbol} | "
                        f"{token_price.price_sol:.8f} SOL | "
                        f"${token_price.price_usd:.6f} USD | "
                        f"Source: {token_price.source}")
    
    def log_trade(self, trade: TradeLog):
        """Log a trade execution"""
        self.trade_count += 1
        
        # Append to trades log
        self._append_to_json_log(self.trades_log, asdict(trade))
        
        pnl_str = f"PnL: {trade.pnl_sol:.4f} SOL" if trade.pnl_sol is not None else "PnL: N/A"
        
        self.logger.info(f"📈 TRADE #{self.trade_count}: {trade.action} {trade.symbol} | "
                        f"{trade.amount_sol:.4f} SOL @ {trade.price_sol:.8f} | "
                        f"Total: {trade.total_value_sol:.4f} SOL | {pnl_str}")
    
    def _append_to_json_log(self, log_file: Path, data: dict):
        """Append data to a JSON log file"""
        try:
            # Read existing data
            with open(log_file, 'r') as f:
                existing_data = json.load(f)
            
            # Append new data
            existing_data.append(data)
            
            # Write back
            with open(log_file, 'w') as f:
                json.dump(existing_data, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Failed to append to {log_file}: {e}")
    
    def print_summary(self):
        """Print execution summary"""
        self.logger.info("=" * 80)
        self.logger.info("EXECUTION SUMMARY")
        self.logger.info("=" * 80)
        self.logger.info(f"📊 New tokens discovered: {len(self.known_tokens)}")
        self.logger.info(f"📈 Total trades executed: {self.trade_count}")
        self.logger.info(f"📁 Log files created:")
        self.logger.info(f"   - New tokens: {self.new_tokens_log}")
        self.logger.info(f"   - Price monitor: {self.price_monitor_log}")
        self.logger.info(f"   - Trades: {self.trades_log}")
        self.logger.info(f"   - Main execution: {self.main_log}")
        self.logger.info("=" * 80)

async def initialize_components(settings: Settings) -> dict:
    """Initialize all required components"""
    logger = get_logger(__name__)
    components = {}
    
    try:
        # Initialize database
        logger.info("Initializing TokenDatabase...")
        db_path = settings.DATABASE_FILE_PATH
        db = TokenDatabase(db_path, settings)
        await db.initialize()
        components['db'] = db
        
        # Initialize DexScreener API first
        logger.info("Initializing DexScreenerAPI...")
        from config.dexscreener_api import DexScreenerAPI
        dexscreener_api = DexScreenerAPI(settings)
        
        # Initialize market data
        logger.info("Initializing MarketData...")
        market_data = MarketData(settings, dexscreener_api, db)
        await market_data.initialize()
        components['market_data'] = market_data
        
        # Initialize HTTP client for PriceMonitor
        logger.info("Initializing HTTP client...")
        import httpx
        http_client = httpx.AsyncClient(timeout=30.0)
        
        # Initialize price monitor
        logger.info("Initializing PriceMonitor...")
        price_monitor = PriceMonitor(settings, dexscreener_api, http_client, db)
        await price_monitor.initialize()
        components['price_monitor'] = price_monitor
        components['http_client'] = http_client
        
        # Initialize token scanner
        logger.info("Initializing TokenScanner...")
        token_scanner = TokenScanner(settings, db)
        components['token_scanner'] = token_scanner
        
        # Initialize paper trading
        logger.info("Initializing PaperTrading...")
        paper_trading = PaperTrading(settings)
        components['paper_trading'] = paper_trading
        
        # Initialize entry/exit strategy
        logger.info("Initializing EntryExitStrategy...")
        entry_exit = EntryExitStrategy(settings)
        components['entry_exit'] = entry_exit
        
        logger.info("✅ All components initialized successfully")
        return components
        
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        raise

async def monitor_new_tokens_task(db: TokenDatabase, controlled_logger: ControlledMainLogger, shutdown_event: asyncio.Event):
    """Task to monitor for new tokens in the database"""
    logger = controlled_logger.logger
    logger.info("🔍 Starting new token monitoring task...")
    
    while not shutdown_event.is_set():
        try:
            # Get all active tokens
            tokens = await db.get_tokens_with_status('active')
            
            # Check for new tokens
            for token in tokens:
                controlled_logger.log_new_token(token)
            
            await asyncio.sleep(30)  # Check every 30 seconds
            
        except asyncio.CancelledError:
            logger.info("New token monitoring task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in new token monitoring: {e}")
            await asyncio.sleep(30)

async def price_monitoring_task(db: TokenDatabase, price_monitor: PriceMonitor, 
                              controlled_logger: ControlledMainLogger, shutdown_event: asyncio.Event):
    """Task to monitor prices of active tokens every 1 minute"""
    logger = controlled_logger.logger
    logger.info("💰 Starting price monitoring task...")
    
    while not shutdown_event.is_set():
        try:
            # Get active tokens
            tokens = await db.get_tokens_with_status('active')
            
            for token in tokens[:10]:  # Limit to top 10 to avoid rate limits
                try:
                    # Get current price from price monitor
                    price_sol = await price_monitor.get_current_price_sol(token.mint)
                    price_usd = await price_monitor.get_current_price_usd(token.mint)
                    
                    # Create price log entry
                    price_log = TokenPriceLog(
                        timestamp=datetime.now().isoformat(),
                        symbol=token.symbol,
                        mint=token.mint,
                        price_sol=price_sol,
                        price_usd=price_usd,
                        source="price_monitor",
                        volume_24h=token.volume_24h,
                        market_cap=token.market_cap
                    )
                    
                    controlled_logger.log_price_update(price_log)
                    
                except Exception as e:
                    logger.error(f"Failed to get price for {token.symbol}: {e}")
            
            await asyncio.sleep(60)  # Update every 1 minute
            
        except asyncio.CancelledError:
            logger.info("Price monitoring task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in price monitoring: {e}")
            await asyncio.sleep(60)

async def paper_trading_task(db: TokenDatabase, paper_trading: PaperTrading, 
                           entry_exit: EntryExitStrategy, controlled_logger: ControlledMainLogger, 
                           shutdown_event: asyncio.Event):
    """Task to execute paper trades and log them"""
    logger = controlled_logger.logger
    logger.info("📈 Starting paper trading task...")
    
    while not shutdown_event.is_set():
        try:
            # Get active tokens for trading
            tokens = await db.get_tokens_with_status('active')
            
            for token in tokens[:5]:  # Limit to top 5 tokens
                try:
                    # Simulate trade decision (simplified)
                    import random
                    if random.random() < 0.1:  # 10% chance of trade per token per cycle
                        action = random.choice(['BUY', 'SELL'])
                        amount_sol = random.uniform(0.1, 1.0)
                        price_sol = random.uniform(0.000001, 0.001)  # Realistic meme coin prices
                        
                        # Create trade log
                        trade_log = TradeLog(
                            timestamp=datetime.now().isoformat(),
                            symbol=token.symbol,
                            mint=token.mint,
                            action=action,
                            amount_sol=amount_sol,
                            price_sol=price_sol,
                            total_value_sol=amount_sol * price_sol,
                            pnl_sol=random.uniform(-0.1, 0.2) if action == 'SELL' else None,
                            strategy="paper_trading_demo"
                        )
                        
                        controlled_logger.log_trade(trade_log)
                        
                except Exception as e:
                    logger.error(f"Failed to process trade for {token.symbol}: {e}")
            
            await asyncio.sleep(60)  # Check for trades every 1 minute
            
        except asyncio.CancelledError:
            logger.info("Paper trading task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in paper trading: {e}")
            await asyncio.sleep(60)

async def main():
    """Main execution function"""
    # Initialize settings and logging
    settings = Settings()
    logging_config = LoggingConfig()
    
    # Initialize controlled logger
    controlled_logger = ControlledMainLogger()
    logger = controlled_logger.logger
    
    # Execution parameters
    EXECUTION_DURATION = 300  # Run for 5 minutes (300 seconds)
    
    logger.info("🚀 Starting Controlled SuperTradeX Main Script")
    logger.info(f"⏱️  Execution duration: {EXECUTION_DURATION} seconds")
    
    # Create shutdown event
    shutdown_event = asyncio.Event()
    
    # Setup signal handlers
    def signal_handler():
        logger.info("🛑 Shutdown signal received")
        shutdown_event.set()
    
    signal.signal(signal.SIGINT, lambda s, f: signal_handler())
    signal.signal(signal.SIGTERM, lambda s, f: signal_handler())
    
    try:
        # Initialize components
        logger.info("🔧 Initializing components...")
        components = await initialize_components(settings)
        
        db = components['db']
        price_monitor = components['price_monitor']
        paper_trading = components['paper_trading']
        entry_exit = components['entry_exit']
        
        # Start background tasks
        background_tasks = []
        
        # New token monitoring task
        new_token_task = asyncio.create_task(
            monitor_new_tokens_task(db, controlled_logger, shutdown_event)
        )
        background_tasks.append(new_token_task)
        
        # Price monitoring task
        price_task = asyncio.create_task(
            price_monitoring_task(db, price_monitor, controlled_logger, shutdown_event)
        )
        background_tasks.append(price_task)
        
        # Paper trading task
        trading_task = asyncio.create_task(
            paper_trading_task(db, paper_trading, entry_exit, controlled_logger, shutdown_event)
        )
        background_tasks.append(trading_task)
        
        logger.info(f"✅ Started {len(background_tasks)} background tasks")
        
        # Run for specified duration or until shutdown
        start_time = time.time()
        while not shutdown_event.is_set():
            elapsed = time.time() - start_time
            if elapsed >= EXECUTION_DURATION:
                logger.info(f"⏰ Execution duration ({EXECUTION_DURATION}s) reached")
                break
            
            # Log progress every 30 seconds
            if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                remaining = EXECUTION_DURATION - elapsed
                logger.info(f"⏱️  Running... {elapsed:.0f}s elapsed, {remaining:.0f}s remaining")
            
            await asyncio.sleep(1)
        
        # Set shutdown event
        shutdown_event.set()
        
        # Wait for tasks to complete
        logger.info("🛑 Shutting down background tasks...")
        for task in background_tasks:
            task.cancel()
        
        await asyncio.gather(*background_tasks, return_exceptions=True)
        
        # Print summary
        controlled_logger.print_summary()
        
    except Exception as e:
        logger.error(f"Critical error in main execution: {e}", exc_info=True)
        return 1
    
    finally:
        # Cleanup components
        if 'components' in locals():
            logger.info("🧹 Cleaning up components...")
            for name, component in components.items():
                try:
                    if hasattr(component, 'close'):
                        await component.close()
                    elif hasattr(component, 'cleanup'):
                        await component.cleanup()
                except Exception as e:
                    logger.error(f"Error closing {name}: {e}")
    
    logger.info("✅ Controlled execution completed successfully")
    return 0

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("Execution interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1) 