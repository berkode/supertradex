#!/usr/bin/env python3
"""
Phase 7: Live-Like Paper Trading System
A comprehensive paper trading system that mimics live trading with:
- Real-time price monitoring
- Automatic signal generation and trade execution  
- Live SOL balance and position tracking
- Real-time P&L, stop loss, and take profit monitoring
- Live logging and performance tracking
"""

import asyncio
import sys
import signal
import logging
from pathlib import Path
from datetime import datetime, timezone
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import json

# Add project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging for live trading
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('live_paper_trader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class LiveTradingConfig:
    """Configuration for live paper trading"""
    # Trading parameters
    max_concurrent_positions: int = 3
    max_position_size_sol: float = 10.0  # Max SOL per position
    min_position_size_sol: float = 0.1   # Min SOL per position
    
    # Risk management
    global_stop_loss_pct: float = 0.10   # 10% global stop loss
    global_take_profit_pct: float = 0.20 # 20% global take profit
    max_daily_loss_sol: float = 50.0     # Max daily loss in SOL
    
    # Monitoring intervals
    price_check_interval: int = 30       # Check prices every 30 seconds
    position_check_interval: int = 10    # Check positions every 10 seconds
    signal_check_interval: int = 60      # Check for new signals every 60 seconds
    
    # Token filtering
    min_volume_24h_usd: float = 100000   # Minimum $100k daily volume
    min_liquidity_sol: float = 1000      # Minimum 1000 SOL liquidity
    max_token_age_hours: int = 72        # Only trade tokens less than 72 hours old

@dataclass
class LivePosition:
    """Represents a live trading position"""
    mint: str
    symbol: str
    entry_price_sol: float
    entry_price_usd: float
    amount: float
    entry_time: datetime
    stop_loss_sol: float
    take_profit_sol: float
    current_price_sol: Optional[float] = None
    current_value_sol: Optional[float] = None
    unrealized_pnl_sol: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None

class LivePaperTrader:
    """
    Live-like paper trading system that mimics real trading
    """
    
    def __init__(self, config: LiveTradingConfig):
        self.config = config
        self.is_running = False
        self.start_time = datetime.now(timezone.utc)
        
        # Portfolio state
        self.sol_balance = 1000.0  # Starting balance
        self.initial_balance = self.sol_balance
        self.positions: Dict[str, LivePosition] = {}
        self.daily_pnl_sol = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        # Performance tracking
        self.performance_log = []
        self.last_performance_update = time.time()
        
        # Simulated token universe for testing
        self.test_tokens = self._create_test_token_universe()
        
        logger.info(f"LivePaperTrader initialized with {self.sol_balance:.2f} SOL starting balance")
    
    def _create_test_token_universe(self) -> List[Dict[str, Any]]:
        """Create a simulated universe of tokens for testing"""
        return [
            {
                'mint': 'TokenA' + '0' * 35,
                'symbol': 'TOKA',
                'base_price_sol': 0.0001,
                'volatility': 0.05,  # 5% volatility
                'trend': 0.02,       # 2% positive trend
                'volume_24h_usd': 250000,
                'liquidity_sol': 2000
            },
            {
                'mint': 'TokenB' + '0' * 35,
                'symbol': 'TOKB', 
                'base_price_sol': 0.0005,
                'volatility': 0.08,  # 8% volatility
                'trend': -0.01,      # 1% negative trend
                'volume_24h_usd': 180000,
                'liquidity_sol': 1500
            },
            {
                'mint': 'TokenC' + '0' * 35,
                'symbol': 'TOKC',
                'base_price_sol': 0.00025,
                'volatility': 0.12,  # 12% volatility
                'trend': 0.05,       # 5% positive trend
                'volume_24h_usd': 500000,
                'liquidity_sol': 3000
            }
        ]
    
    def _simulate_price_movement(self, token: Dict[str, Any]) -> float:
        """Simulate realistic price movement for a token"""
        import random
        import math
        
        base_price = token['base_price_sol']
        volatility = token['volatility']
        trend = token['trend']
        
        # Generate random price movement with trend and volatility
        random_factor = random.normalvariate(0, volatility)
        time_factor = (time.time() % 3600) / 3600  # Hour cycle
        trend_factor = trend * time_factor
        
        # Add some realistic price patterns
        momentum = math.sin(time.time() / 300) * 0.02  # 5-minute momentum cycle
        
        price_multiplier = 1 + random_factor + trend_factor + momentum
        current_price = base_price * max(0.1, price_multiplier)  # Prevent negative prices
        
        return current_price
    
    async def _get_current_sol_price_usd(self) -> float:
        """Get current SOL price in USD (simulated)"""
        # Simulate SOL price with some realistic movement
        import random
        base_sol_price = 150.0
        variation = random.normalvariate(0, 0.02)  # 2% variation
        return base_sol_price * (1 + variation)
    
    async def _check_prices(self):
        """Check and update current prices for all tokens and positions"""
        try:
            sol_price_usd = await self._get_current_sol_price_usd()
            
            # Update position prices
            for mint, position in self.positions.items():
                # Find token in universe
                token = next((t for t in self.test_tokens if t['mint'] == mint), None)
                if token:
                    current_price_sol = self._simulate_price_movement(token)
                    current_price_usd = current_price_sol * sol_price_usd
                    
                    # Update position data
                    position.current_price_sol = current_price_sol
                    position.current_value_sol = current_price_sol * position.amount
                    position.unrealized_pnl_sol = position.current_value_sol - (position.entry_price_sol * position.amount)
                    position.unrealized_pnl_pct = (position.unrealized_pnl_sol / (position.entry_price_sol * position.amount)) * 100
                    
                    # Log significant price movements
                    price_change_pct = ((current_price_sol / position.entry_price_sol) - 1) * 100
                    if abs(price_change_pct) > 5:  # Log moves > 5%
                        logger.info(f"📊 {position.symbol}: {current_price_sol:.8f} SOL ({price_change_pct:+.1f}%) | P&L: {position.unrealized_pnl_sol:+.6f} SOL ({position.unrealized_pnl_pct:+.1f}%)")
            
        except Exception as e:
            logger.error(f"Error checking prices: {e}")
    
    async def _check_exit_conditions(self):
        """Check stop loss and take profit conditions for all positions"""
        positions_to_close = []
        
        for mint, position in self.positions.items():
            if position.current_price_sol is None:
                continue
                
            # Check stop loss
            if position.current_price_sol <= position.stop_loss_sol:
                logger.warning(f"🚨 STOP LOSS triggered for {position.symbol}: {position.current_price_sol:.8f} SOL <= {position.stop_loss_sol:.8f} SOL")
                positions_to_close.append((mint, 'STOP_LOSS'))
                
            # Check take profit
            elif position.current_price_sol >= position.take_profit_sol:
                logger.info(f"🎯 TAKE PROFIT triggered for {position.symbol}: {position.current_price_sol:.8f} SOL >= {position.take_profit_sol:.8f} SOL")
                positions_to_close.append((mint, 'TAKE_PROFIT'))
        
        # Execute exits
        for mint, reason in positions_to_close:
            await self._close_position(mint, reason)
    
    async def _close_position(self, mint: str, reason: str = 'MANUAL'):
        """Close a position and update portfolio"""
        if mint not in self.positions:
            logger.warning(f"Attempted to close non-existent position: {mint}")
            return
        
        position = self.positions[mint]
        
        if position.current_price_sol is None:
            logger.error(f"Cannot close position {mint} - no current price")
            return
        
        # Calculate final P&L
        proceeds_sol = position.current_price_sol * position.amount
        cost_sol = position.entry_price_sol * position.amount
        realized_pnl_sol = proceeds_sol - cost_sol
        realized_pnl_pct = (realized_pnl_sol / cost_sol) * 100
        
        # Update balances
        self.sol_balance += proceeds_sol
        self.daily_pnl_sol += realized_pnl_sol
        self.total_trades += 1
        
        if realized_pnl_sol > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        # Log the exit
        logger.info(f"📤 CLOSED {position.symbol} ({reason})")
        logger.info(f"   Entry: {position.entry_price_sol:.8f} SOL → Exit: {position.current_price_sol:.8f} SOL")
        logger.info(f"   Amount: {position.amount:,.0f} tokens")
        logger.info(f"   P&L: {realized_pnl_sol:+.6f} SOL ({realized_pnl_pct:+.1f}%)")
        logger.info(f"   New SOL Balance: {self.sol_balance:.6f} SOL")
        
        # Remove position
        del self.positions[mint]
    
    async def _check_for_new_signals(self):
        """Check for new trading opportunities"""
        try:
            # Don't open new positions if at limit
            if len(self.positions) >= self.config.max_concurrent_positions:
                return
            
            # Don't trade if daily loss limit reached
            if self.daily_pnl_sol < -self.config.max_daily_loss_sol:
                logger.warning(f"Daily loss limit reached: {self.daily_pnl_sol:.2f} SOL")
                return
            
            # Check each token for entry signals
            for token in self.test_tokens:
                mint = token['mint']
                
                # Skip if already have position
                if mint in self.positions:
                    continue
                
                # Apply filters
                if token['volume_24h_usd'] < self.config.min_volume_24h_usd:
                    continue
                if token['liquidity_sol'] < self.config.min_liquidity_sol:
                    continue
                
                # Simulate signal generation
                current_price_sol = self._simulate_price_movement(token)
                signal_strength = self._generate_signal(token, current_price_sol)
                
                # Enter position if signal is strong enough
                if signal_strength > 0.7:  # 70% confidence threshold
                    await self._enter_position(token, current_price_sol)
                    
        except Exception as e:
            logger.error(f"Error checking for signals: {e}")
    
    def _generate_signal(self, token: Dict[str, Any], current_price_sol: float) -> float:
        """Generate a trading signal (0.0 to 1.0) for a token"""
        import random
        
        # Simulate technical analysis
        trend_score = min(1.0, max(0.0, (token['trend'] + 0.05) / 0.1))  # Normalize trend
        volatility_score = min(1.0, max(0.0, 1 - (token['volatility'] / 0.2)))  # Prefer lower volatility
        volume_score = min(1.0, token['volume_24h_usd'] / 1000000)  # Volume factor
        
        # Add some randomness for realistic signal variation
        random_factor = random.uniform(0.8, 1.2)
        
        signal = (trend_score * 0.4 + volatility_score * 0.3 + volume_score * 0.3) * random_factor
        
        return min(1.0, signal)
    
    async def _enter_position(self, token: Dict[str, Any], entry_price_sol: float):
        """Enter a new position"""
        try:
            mint = token['mint']
            symbol = token['symbol']
            
            # Calculate position size
            available_sol = min(self.sol_balance * 0.3, self.config.max_position_size_sol)  # Max 30% of balance per trade
            position_size_sol = max(self.config.min_position_size_sol, available_sol)
            
            if position_size_sol > self.sol_balance:
                logger.warning(f"Insufficient balance for {symbol}: need {position_size_sol:.2f} SOL, have {self.sol_balance:.2f} SOL")
                return
            
            # Calculate amount of tokens
            amount = position_size_sol / entry_price_sol
            
            # Calculate risk management levels
            stop_loss_sol = entry_price_sol * (1 - self.config.global_stop_loss_pct)
            take_profit_sol = entry_price_sol * (1 + self.config.global_take_profit_pct)
            
            # Get USD prices for logging
            sol_price_usd = await self._get_current_sol_price_usd()
            entry_price_usd = entry_price_sol * sol_price_usd
            
            # Create position
            position = LivePosition(
                mint=mint,
                symbol=symbol,
                entry_price_sol=entry_price_sol,
                entry_price_usd=entry_price_usd,
                amount=amount,
                entry_time=datetime.now(timezone.utc),
                stop_loss_sol=stop_loss_sol,
                take_profit_sol=take_profit_sol
            )
            
            # Update balances
            self.sol_balance -= position_size_sol
            self.positions[mint] = position
            
            # Log the entry
            logger.info(f"📥 ENTERED {symbol}")
            logger.info(f"   Price: {entry_price_sol:.8f} SOL (${entry_price_usd:.6f})")
            logger.info(f"   Amount: {amount:,.0f} tokens")
            logger.info(f"   Cost: {position_size_sol:.6f} SOL")
            logger.info(f"   Stop Loss: {stop_loss_sol:.8f} SOL ({-self.config.global_stop_loss_pct*100:.0f}%)")
            logger.info(f"   Take Profit: {take_profit_sol:.8f} SOL ({self.config.global_take_profit_pct*100:.0f}%)")
            logger.info(f"   Remaining Balance: {self.sol_balance:.6f} SOL")
            
        except Exception as e:
            logger.error(f"Error entering position for {token['symbol']}: {e}")
    
    async def _update_performance_metrics(self):
        """Update and log performance metrics"""
        try:
            current_time = time.time()
            
            # Only update every 5 minutes
            if current_time - self.last_performance_update < 300:
                return
            
            # Calculate portfolio value
            total_position_value = sum(
                pos.current_value_sol for pos in self.positions.values() 
                if pos.current_value_sol is not None
            )
            total_portfolio_value = self.sol_balance + total_position_value
            
            # Calculate total P&L
            total_unrealized_pnl = sum(
                pos.unrealized_pnl_sol for pos in self.positions.values()
                if pos.unrealized_pnl_sol is not None
            )
            total_pnl_sol = self.daily_pnl_sol + total_unrealized_pnl
            total_pnl_pct = ((total_portfolio_value / self.initial_balance) - 1) * 100
            
            # Calculate win rate
            win_rate = (self.winning_trades / max(1, self.total_trades)) * 100
            
            # Calculate time running
            runtime = datetime.now(timezone.utc) - self.start_time
            runtime_hours = runtime.total_seconds() / 3600
            
            # Performance metrics
            metrics = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'runtime_hours': runtime_hours,
                'initial_balance_sol': self.initial_balance,
                'current_balance_sol': self.sol_balance,
                'position_value_sol': total_position_value,
                'total_portfolio_sol': total_portfolio_value,
                'daily_realized_pnl_sol': self.daily_pnl_sol,
                'unrealized_pnl_sol': total_unrealized_pnl,
                'total_pnl_sol': total_pnl_sol,
                'total_pnl_pct': total_pnl_pct,
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'win_rate_pct': win_rate,
                'active_positions': len(self.positions)
            }
            
            # Log performance summary
            logger.info("📊 PERFORMANCE UPDATE")
            logger.info(f"   Runtime: {runtime_hours:.1f} hours")
            logger.info(f"   Portfolio: {total_portfolio_value:.6f} SOL ({total_pnl_pct:+.2f}%)")
            logger.info(f"   SOL Balance: {self.sol_balance:.6f} SOL")
            logger.info(f"   Position Value: {total_position_value:.6f} SOL")
            logger.info(f"   Realized P&L: {self.daily_pnl_sol:+.6f} SOL")
            logger.info(f"   Unrealized P&L: {total_unrealized_pnl:+.6f} SOL")
            logger.info(f"   Trades: {self.total_trades} (Win Rate: {win_rate:.1f}%)")
            logger.info(f"   Active Positions: {len(self.positions)}")
            
            # Store metrics
            self.performance_log.append(metrics)
            self.last_performance_update = current_time
            
            # Write performance to file
            with open('live_paper_trader_performance.json', 'w') as f:
                json.dump(self.performance_log, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error updating performance metrics: {e}")
    
    async def _trading_loop(self):
        """Main trading loop"""
        logger.info("🚀 Starting live paper trading loop")
        
        last_price_check = 0
        last_position_check = 0
        last_signal_check = 0
        
        while self.is_running:
            try:
                current_time = time.time()
                
                # Check prices
                if current_time - last_price_check >= self.config.price_check_interval:
                    await self._check_prices()
                    last_price_check = current_time
                
                # Check positions
                if current_time - last_position_check >= self.config.position_check_interval:
                    await self._check_exit_conditions()
                    last_position_check = current_time
                
                # Check for new signals
                if current_time - last_signal_check >= self.config.signal_check_interval:
                    await self._check_for_new_signals()
                    last_signal_check = current_time
                
                # Update performance metrics
                await self._update_performance_metrics()
                
                # Sleep for a short interval
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(10)  # Longer sleep on error
    
    async def start(self):
        """Start the live paper trading system"""
        if self.is_running:
            logger.warning("Trading system is already running")
            return
        
        self.is_running = True
        logger.info("🎯 STARTING LIVE PAPER TRADING SYSTEM")
        logger.info(f"   Initial Balance: {self.sol_balance:.2f} SOL")
        logger.info(f"   Max Positions: {self.config.max_concurrent_positions}")
        logger.info(f"   Max Position Size: {self.config.max_position_size_sol:.2f} SOL")
        logger.info(f"   Stop Loss: {self.config.global_stop_loss_pct*100:.0f}%")
        logger.info(f"   Take Profit: {self.config.global_take_profit_pct*100:.0f}%")
        logger.info(f"   Price Check Interval: {self.config.price_check_interval}s")
        
        # Start trading loop
        await self._trading_loop()
    
    async def stop(self):
        """Stop the live paper trading system"""
        logger.info("🛑 Stopping live paper trading system...")
        self.is_running = False
        
        # Close all positions
        for mint in list(self.positions.keys()):
            await self._close_position(mint, 'SHUTDOWN')
        
        # Final performance update
        await self._update_performance_metrics()
        
        logger.info("✅ Live paper trading system stopped")

async def main():
    """Main function to run the live paper trader"""
    
    # Create configuration
    config = LiveTradingConfig(
        max_concurrent_positions=3,
        max_position_size_sol=10.0,
        global_stop_loss_pct=0.08,      # 8% stop loss
        global_take_profit_pct=0.15,    # 15% take profit
        price_check_interval=30,        # Check prices every 30 seconds
        position_check_interval=10,     # Check positions every 10 seconds
        signal_check_interval=120       # Check signals every 2 minutes
    )
    
    # Create trader
    trader = LivePaperTrader(config)
    
    # Setup graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(trader.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start trading
        await trader.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Trading system error: {e}")
    finally:
        if trader.is_running:
            await trader.stop()

if __name__ == "__main__":
    print("🚀 SUPERTRADEX LIVE PAPER TRADING SYSTEM")
    print("=" * 50)
    print("Press Ctrl+C to stop trading")
    print("=" * 50)
    
    asyncio.run(main()) 