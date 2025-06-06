#!/usr/bin/env python3
"""
Live Paper Trading with Real Market Data
Uses the existing MarketData and PriceMonitor components to get real-time price data
"""
import asyncio
import sys
from pathlib import Path
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from data.token_database import TokenDatabase
from data.market_data import MarketData
from strategies.entry_exit import EntryExitStrategy
from config.thresholds import Thresholds
from config.dexscreener_api import DexScreenerAPI
from strategies.paper_trading import PaperTrading
from wallet.wallet_manager import WalletManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('live_paper_trading_real.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class LiveTradingPosition:
    """Represents a live paper trading position"""
    mint: str
    symbol: str
    entry_price_sol: float
    entry_price_usd: float
    amount: float
    entry_time: datetime
    stop_loss_pct: float = 0.05  # 5% stop loss
    take_profit_pct: float = 0.10  # 10% take profit
    current_price_sol: Optional[float] = None
    current_price_usd: Optional[float] = None
    unrealized_pnl_sol: Optional[float] = None
    unrealized_pnl_usd: Optional[float] = None

class LivePaperTradingSystem:
    """Live paper trading system using real market data"""
    
    def __init__(self):
        self.settings = None
        self.db = None
        self.market_data = None
        self.paper_trading = None
        self.wallet_manager = None
        self.entry_exit_strategy = None
        self.thresholds = None
        
        # Trading state
        self.is_running = False
        self.start_time = None
        self.positions: Dict[str, LiveTradingPosition] = {}
        self.monitored_tokens: List[str] = []
        self.trade_count = 0
        self.total_pnl_sol = 0.0
        self.total_pnl_usd = 0.0
        
        # Configuration
        self.max_positions = 3
        self.position_size_sol = 5.0  # 5 SOL per position
        self.price_check_interval = 30  # Check prices every 30 seconds
        self.signal_check_interval = 60  # Check for signals every 60 seconds
        
    async def initialize(self):
        """Initialize all components for live paper trading"""
        try:
            logger.info("🔧 Initializing Live Paper Trading System with Real Data...")
            
            # Initialize settings
            self.settings = Settings()
            
            # Initialize database
            self.db = await TokenDatabase.create(self.settings.DATABASE_FILE_PATH, self.settings)
            
            # Initialize APIs
            self.dexscreener_api = DexScreenerAPI(self.settings)
            
            # Initialize market data with real-time capabilities
            self.market_data = MarketData(self.settings, self.dexscreener_api, self.db)
            await self.market_data.initialize()
            
            # Initialize wallet manager (for paper trading) with required parameters
            from solana.rpc.async_api import AsyncClient
            solana_client = AsyncClient(self.settings.SOLANA_RPC_URL)
            self.wallet_manager = WalletManager(self.settings, solana_client, self.db)
            
            # Initialize thresholds
            self.thresholds = Thresholds()
            
            # Initialize paper trading system
            self.paper_trading = PaperTrading(
                settings=self.settings,
                db=self.db,
                wallet_manager=self.wallet_manager,
                price_monitor=self.market_data.price_monitor
            )
            await self.paper_trading.load_persistent_state()
            
            # Initialize entry/exit strategy
            self.entry_exit_strategy = EntryExitStrategy(
                settings=self.settings,
                db=self.db,
                trade_queue=None,  # Signal generation mode
                market_data=self.market_data,
                thresholds=self.thresholds,
                wallet_manager=self.wallet_manager
            )
            await self.entry_exit_strategy.initialize()
            
            logger.info("✅ Live Paper Trading System initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Live Paper Trading System: {e}")
            return False
    
    async def select_tokens_for_trading(self) -> List[Dict[str, Any]]:
        """Select best tokens for live paper trading"""
        try:
            logger.info("🔍 Selecting tokens for live paper trading...")
            
            # Get all tokens from database
            all_tokens = await self.db.get_tokens_list()
            if not all_tokens:
                logger.warning("No tokens found in database")
                return []
            
            # Filter tokens for trading eligibility
            eligible_tokens = []
            for token in all_tokens:
                # Basic eligibility criteria
                if (token.volume_24h and token.volume_24h > 50000 and  # $50k+ volume
                    token.liquidity and token.liquidity > 5000 and      # $5k+ liquidity
                    token.rugcheck_score and token.rugcheck_score > 15 and  # 15+ rugcheck
                    token.dex_id in ['raydium_v4', 'raydium_clmm', 'pumpswap']):  # Supported DEXs
                    
                    eligible_tokens.append({
                        'mint': token.mint,
                        'symbol': token.symbol or 'UNKNOWN',
                        'volume_24h': token.volume_24h,
                        'liquidity': token.liquidity,
                        'rugcheck_score': token.rugcheck_score,
                        'dex_id': token.dex_id,
                        'pair_address': token.pair_address
                    })
            
            # Sort by volume and take top tokens
            eligible_tokens.sort(key=lambda x: x['volume_24h'], reverse=True)
            selected_tokens = eligible_tokens[:self.max_positions * 2]  # Select more than max positions
            
            logger.info(f"✅ Selected {len(selected_tokens)} tokens for monitoring")
            for i, token in enumerate(selected_tokens[:5], 1):  # Log top 5
                logger.info(f"  {i}. {token['symbol']} | Vol: ${token['volume_24h']:,.0f} | Liq: ${token['liquidity']:,.0f}")
            
            return selected_tokens
            
        except Exception as e:
            logger.error(f"Error selecting tokens: {e}")
            return []
    
    async def start_monitoring_tokens(self, tokens: List[Dict[str, Any]]):
        """Start monitoring selected tokens for real-time price data"""
        try:
            logger.info("📊 Starting real-time monitoring for selected tokens...")
            
            for token in tokens:
                mint = token['mint']
                pair_address = token.get('pair_address')
                dex_id = token.get('dex_id')
                
                # Add token to market data monitoring
                success = await self.market_data.add_token_for_monitoring(
                    mint=mint,
                    pair_address=pair_address,
                    dex_id=dex_id
                )
                
                if success:
                    self.monitored_tokens.append(mint)
                    logger.info(f"✅ Started monitoring {token['symbol']} ({mint[:8]}...)")
                else:
                    logger.warning(f"⚠️ Failed to start monitoring {token['symbol']}")
            
            logger.info(f"📈 Monitoring {len(self.monitored_tokens)} tokens for real-time data")
            
        except Exception as e:
            logger.error(f"Error starting token monitoring: {e}")
    
    async def check_trading_signals(self, tokens: List[Dict[str, Any]]):
        """Check for trading signals using real market data"""
        try:
            for token in tokens:
                mint = token['mint']
                symbol = token['symbol']
                
                # Skip if already have position
                if mint in self.positions:
                    continue
                
                # Skip if at max positions
                if len(self.positions) >= self.max_positions:
                    continue
                
                # Get current price from market data
                current_price_sol = await self.market_data.get_token_price_sol(mint, max_age_seconds=60)
                current_price_usd = await self.market_data.get_token_price_usd(mint, max_age_seconds=60)
                
                if not current_price_sol or not current_price_usd:
                    continue
                
                # Set active mint for strategy
                self.entry_exit_strategy.set_active_mint(mint)
                
                # Get trading signal using real price data
                signal = await self.entry_exit_strategy.get_signal_on_price_event(
                    event_data={
                        'mint': mint,
                        'price': current_price_sol,
                        'timestamp': datetime.now(timezone.utc)
                    },
                    pool_address=token.get('pair_address'),
                    dex_id=token.get('dex_id')
                )
                
                # Execute buy signal
                if signal and signal.get('action') == 'BUY':
                    await self.enter_position(token, current_price_sol, current_price_usd, signal)
                    
        except Exception as e:
            logger.error(f"Error checking trading signals: {e}")
    
    async def enter_position(self, token: Dict[str, Any], price_sol: float, price_usd: float, signal: Dict[str, Any]):
        """Enter a new paper trading position"""
        try:
            mint = token['mint']
            symbol = token['symbol']
            
            # Calculate position size
            amount_tokens = self.position_size_sol / price_sol
            
            # Create position
            position = LiveTradingPosition(
                mint=mint,
                symbol=symbol,
                entry_price_sol=price_sol,
                entry_price_usd=price_usd,
                amount=amount_tokens,
                entry_time=datetime.now(timezone.utc)
            )
            
            # Execute paper trade
            paper_trade_success = await self.paper_trading.execute_trade(
                trade_id=self.trade_count + 1,
                action='BUY',
                mint=mint,
                price=price_usd,  # Paper trading expects USD price
                amount=amount_tokens
            )
            
            if paper_trade_success:
                self.positions[mint] = position
                self.trade_count += 1
                
                logger.info(f"🟢 ENTERED POSITION: {symbol}")
                logger.info(f"   Price: {price_sol:.8f} SOL (${price_usd:.6f})")
                logger.info(f"   Amount: {amount_tokens:,.0f} tokens")
                logger.info(f"   Cost: {self.position_size_sol:.2f} SOL")
                logger.info(f"   Signal: {signal.get('reason', 'N/A')}")
                logger.info(f"   Confidence: {signal.get('confidence', 'N/A')}")
            else:
                logger.error(f"❌ Failed to execute paper trade for {symbol}")
                
        except Exception as e:
            logger.error(f"Error entering position for {token['symbol']}: {e}")
    
    async def check_exit_conditions(self):
        """Check exit conditions for existing positions using real market data"""
        try:
            positions_to_close = []
            
            for mint, position in self.positions.items():
                # Get current price from market data
                current_price_sol = await self.market_data.get_token_price_sol(mint, max_age_seconds=60)
                current_price_usd = await self.market_data.get_token_price_usd(mint, max_age_seconds=60)
                
                if not current_price_sol or not current_price_usd:
                    continue
                
                # Update position with current prices
                position.current_price_sol = current_price_sol
                position.current_price_usd = current_price_usd
                position.unrealized_pnl_sol = (current_price_sol - position.entry_price_sol) * position.amount
                position.unrealized_pnl_usd = (current_price_usd - position.entry_price_usd) * position.amount
                
                # Calculate percentage change
                pnl_pct = ((current_price_sol - position.entry_price_sol) / position.entry_price_sol) * 100
                
                # Check exit conditions
                should_exit = False
                exit_reason = ""
                
                # Stop loss check
                if pnl_pct <= -position.stop_loss_pct * 100:
                    should_exit = True
                    exit_reason = f"Stop Loss ({pnl_pct:.1f}%)"
                
                # Take profit check
                elif pnl_pct >= position.take_profit_pct * 100:
                    should_exit = True
                    exit_reason = f"Take Profit ({pnl_pct:.1f}%)"
                
                # Time-based exit (hold for max 30 minutes)
                elif (datetime.now(timezone.utc) - position.entry_time).total_seconds() > 1800:
                    should_exit = True
                    exit_reason = f"Time Limit ({pnl_pct:.1f}%)"
                
                # Get trading signal for exit
                if not should_exit:
                    self.entry_exit_strategy.set_active_mint(mint)
                    signal = await self.entry_exit_strategy.get_signal_on_price_event(
                        event_data={
                            'mint': mint,
                            'price': current_price_sol,
                            'timestamp': datetime.now(timezone.utc)
                        },
                        pool_address=None,
                        dex_id=None
                    )
                    
                    if signal and signal.get('action') == 'SELL':
                        should_exit = True
                        exit_reason = f"Signal: {signal.get('reason', 'SELL')} ({pnl_pct:.1f}%)"
                
                if should_exit:
                    positions_to_close.append((mint, position, exit_reason, current_price_usd))
            
            # Close positions
            for mint, position, reason, exit_price_usd in positions_to_close:
                await self.exit_position(mint, position, reason, exit_price_usd)
                
        except Exception as e:
            logger.error(f"Error checking exit conditions: {e}")
    
    async def exit_position(self, mint: str, position: LiveTradingPosition, reason: str, exit_price_usd: float):
        """Exit a paper trading position"""
        try:
            # Execute paper trade
            paper_trade_success = await self.paper_trading.execute_trade(
                trade_id=self.trade_count + 1,
                action='SELL',
                mint=mint,
                price=exit_price_usd,
                amount=position.amount
            )
            
            if paper_trade_success:
                # Calculate final P&L
                pnl_sol = position.unrealized_pnl_sol or 0
                pnl_usd = position.unrealized_pnl_usd or 0
                pnl_pct = ((position.current_price_sol - position.entry_price_sol) / position.entry_price_sol) * 100
                
                # Update totals
                self.total_pnl_sol += pnl_sol
                self.total_pnl_usd += pnl_usd
                self.trade_count += 1
                
                # Log the exit
                logger.info(f"🔴 EXITED POSITION: {position.symbol}")
                logger.info(f"   Entry: {position.entry_price_sol:.8f} SOL (${position.entry_price_usd:.6f})")
                logger.info(f"   Exit: {position.current_price_sol:.8f} SOL (${exit_price_usd:.6f})")
                logger.info(f"   P&L: {pnl_sol:+.6f} SOL (${pnl_usd:+.2f}) [{pnl_pct:+.1f}%]")
                logger.info(f"   Reason: {reason}")
                logger.info(f"   Duration: {(datetime.now(timezone.utc) - position.entry_time).total_seconds():.0f}s")
                
                # Remove position
                del self.positions[mint]
            else:
                logger.error(f"❌ Failed to execute exit trade for {position.symbol}")
                
        except Exception as e:
            logger.error(f"Error exiting position for {position.symbol}: {e}")
    
    async def log_portfolio_status(self):
        """Log current portfolio status"""
        try:
            if not self.positions:
                return
            
            logger.info("📊 PORTFOLIO STATUS:")
            total_unrealized_sol = 0
            total_unrealized_usd = 0
            
            for mint, position in self.positions.items():
                if position.unrealized_pnl_sol is not None:
                    total_unrealized_sol += position.unrealized_pnl_sol
                if position.unrealized_pnl_usd is not None:
                    total_unrealized_usd += position.unrealized_pnl_usd
                
                pnl_pct = 0
                if position.current_price_sol and position.entry_price_sol:
                    pnl_pct = ((position.current_price_sol - position.entry_price_sol) / position.entry_price_sol) * 100
                
                logger.info(f"   {position.symbol}: {position.unrealized_pnl_sol:+.6f} SOL (${position.unrealized_pnl_usd:+.2f}) [{pnl_pct:+.1f}%]")
            
            total_pnl_sol = self.total_pnl_sol + total_unrealized_sol
            total_pnl_usd = self.total_pnl_usd + total_unrealized_usd
            
            logger.info(f"📈 TOTAL P&L: {total_pnl_sol:+.6f} SOL (${total_pnl_usd:+.2f})")
            logger.info(f"📊 TRADES: {self.trade_count} | POSITIONS: {len(self.positions)}")
            
        except Exception as e:
            logger.error(f"Error logging portfolio status: {e}")
    
    async def trading_loop(self):
        """Main trading loop with real market data"""
        logger.info("🚀 Starting Live Paper Trading Loop with Real Market Data")
        
        # Select tokens for trading
        tokens = await self.select_tokens_for_trading()
        if not tokens:
            logger.error("No tokens selected for trading")
            return
        
        # Start monitoring tokens
        await self.start_monitoring_tokens(tokens)
        
        # Wait for initial price data
        logger.info("⏳ Waiting for initial price data...")
        await asyncio.sleep(30)
        
        last_signal_check = 0
        last_status_log = 0
        
        while self.is_running:
            try:
                current_time = time.time()
                
                # Check for new trading signals
                if current_time - last_signal_check >= self.signal_check_interval:
                    await self.check_trading_signals(tokens)
                    last_signal_check = current_time
                
                # Check exit conditions for existing positions
                await self.check_exit_conditions()
                
                # Log portfolio status every 5 minutes
                if current_time - last_status_log >= 300:
                    await self.log_portfolio_status()
                    last_status_log = current_time
                
                # Sleep between checks
                await asyncio.sleep(self.price_check_interval)
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(60)  # Longer sleep on error
    
    async def start(self, duration_minutes: int = 60):
        """Start live paper trading for specified duration"""
        try:
            if not await self.initialize():
                logger.error("Failed to initialize system")
                return
            
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            
            logger.info("🎯 STARTING LIVE PAPER TRADING WITH REAL MARKET DATA")
            logger.info(f"   Duration: {duration_minutes} minutes")
            logger.info(f"   Max Positions: {self.max_positions}")
            logger.info(f"   Position Size: {self.position_size_sol} SOL")
            logger.info(f"   Price Check Interval: {self.price_check_interval}s")
            logger.info("=" * 60)
            
            # Start trading loop with timeout
            try:
                await asyncio.wait_for(self.trading_loop(), timeout=duration_minutes * 60)
            except asyncio.TimeoutError:
                logger.info(f"⏰ Trading session completed after {duration_minutes} minutes")
            
            # Stop trading
            await self.stop()
            
        except Exception as e:
            logger.error(f"Error in live paper trading: {e}")
            await self.stop()
    
    async def stop(self):
        """Stop live paper trading and cleanup"""
        try:
            logger.info("🛑 Stopping Live Paper Trading...")
            self.is_running = False
            
            # Close all open positions
            for mint in list(self.positions.keys()):
                position = self.positions[mint]
                current_price_usd = await self.market_data.get_token_price_usd(mint, max_age_seconds=60)
                if current_price_usd:
                    await self.exit_position(mint, position, "Session End", current_price_usd)
            
            # Final portfolio summary
            runtime = datetime.now(timezone.utc) - self.start_time if self.start_time else timedelta(0)
            
            logger.info("\n" + "="*60)
            logger.info("📊 FINAL TRADING SESSION SUMMARY")
            logger.info("="*60)
            logger.info(f"⏱️  Duration: {runtime.total_seconds() / 60:.1f} minutes")
            logger.info(f"📈 Total Trades: {self.trade_count}")
            logger.info(f"💰 Total P&L: {self.total_pnl_sol:+.6f} SOL (${self.total_pnl_usd:+.2f})")
            logger.info(f"📊 Monitored Tokens: {len(self.monitored_tokens)}")
            
            if self.trade_count > 0:
                avg_pnl_sol = self.total_pnl_sol / (self.trade_count // 2) if self.trade_count > 1 else self.total_pnl_sol
                logger.info(f"📈 Average P&L per trade: {avg_pnl_sol:+.6f} SOL")
            
            # Cleanup
            if self.market_data:
                await self.market_data.close()
            if self.db:
                await self.db.close()
            
            logger.info("✅ Live Paper Trading stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping live paper trading: {e}")

async def main():
    """Main function to run live paper trading"""
    try:
        # Create and start live paper trading system
        trading_system = LivePaperTradingSystem()
        
        # Run for 30 minutes by default
        await trading_system.start(duration_minutes=30)
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping...")
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    print("🚀 SUPERTRADEX LIVE PAPER TRADING WITH REAL MARKET DATA")
    print("=" * 60)
    print("Press Ctrl+C to stop trading")
    print("=" * 60)
    
    asyncio.run(main()) 