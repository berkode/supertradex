#!/usr/bin/env python3
"""
Simple Live Paper Trading with Real Market Data
Simplified version that focuses on price monitoring and paper trading without wallet complexity
"""
import asyncio
import sys
from pathlib import Path
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from data.token_database import TokenDatabase
from data.market_data import MarketData
from config.dexscreener_api import DexScreenerAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('simple_live_paper_trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class SimplePaperPosition:
    """Simple paper trading position"""
    mint: str
    symbol: str
    entry_price_sol: float
    entry_price_usd: float
    amount: float
    entry_time: datetime
    cost_sol: float
    cost_usd: float

class SimpleLivePaperTrading:
    """Simplified live paper trading system using real market data"""
    
    def __init__(self):
        self.settings = None
        self.db = None
        self.market_data = None
        
        # Trading state
        self.is_running = False
        self.start_time = None
        self.positions: Dict[str, SimplePaperPosition] = {}
        self.monitored_tokens: List[str] = []
        self.trade_count = 0
        self.total_pnl_sol = 0.0
        self.total_pnl_usd = 0.0
        self.paper_sol_balance = 100.0  # Start with 100 SOL
        
        # Configuration
        self.max_positions = 2
        self.position_size_sol = 10.0  # 10 SOL per position
        self.stop_loss_pct = 0.05  # 5% stop loss
        self.take_profit_pct = 0.10  # 10% take profit
        
    async def initialize(self):
        """Initialize components for live paper trading"""
        try:
            logger.info("🔧 Initializing Simple Live Paper Trading System...")
            
            # Initialize settings
            self.settings = Settings()
            
            # Initialize database
            self.db = await TokenDatabase.create(self.settings.DATABASE_FILE_PATH, self.settings)
            
            # Initialize APIs
            self.dexscreener_api = DexScreenerAPI(self.settings)
            
            # Initialize market data
            self.market_data = MarketData(self.settings, self.dexscreener_api, self.db)
            await self.market_data.initialize()
            
            logger.info("✅ Simple Live Paper Trading System initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize: {e}")
            return False
    
    async def select_tokens_for_trading(self, max_tokens: int = 5):
        """Select best tokens for live paper trading"""
        try:
            logger.info(f"🔍 Selecting top {max_tokens} tokens for trading...")
            
            # Get all tokens from database
            all_tokens = await self.db.get_tokens_list()
            if not all_tokens:
                logger.warning("No tokens found in database")
                return []
            
            # Filter and sort by volume
            eligible_tokens = []
            for token in all_tokens:
                if (token.volume_24h and token.volume_24h > 50000 and  # $50k+ volume
                    token.liquidity and token.liquidity > 5000 and     # $5k+ liquidity
                    token.rugcheck_score and token.rugcheck_score > 15 and  # 15+ rugcheck
                    token.dex_id in ['raydium_v4', 'raydium_clmm', 'pumpswap']):
                    eligible_tokens.append(token)
            
            # Sort by volume and take top tokens
            eligible_tokens.sort(key=lambda x: x.volume_24h or 0, reverse=True)
            selected_tokens = eligible_tokens[:max_tokens]
            
            logger.info(f"✅ Selected {len(selected_tokens)} tokens for trading:")
            for i, token in enumerate(selected_tokens, 1):
                logger.info(f"  {i}. {token.symbol or 'UNKNOWN'} | Vol: ${token.volume_24h:,.0f} | Liq: ${token.liquidity:,.0f}")
            
            return selected_tokens
            
        except Exception as e:
            logger.error(f"Error selecting tokens: {e}")
            return []
    
    async def start_monitoring(self, tokens):
        """Start monitoring selected tokens"""
        try:
            logger.info("📊 Starting price monitoring for selected tokens...")
            
            for token in tokens:
                # Add token directly to PriceMonitor
                self.market_data.price_monitor.add_token(token.mint)
                self.monitored_tokens.append(token.mint)
                logger.info(f"✅ Added {token.symbol or 'UNKNOWN'} to monitoring")
            
            logger.info(f"📈 Monitoring {len(self.monitored_tokens)} tokens")
            
        except Exception as e:
            logger.error(f"Error starting monitoring: {e}")
    
    async def check_for_entry_signals(self, tokens):
        """Check for entry signals using simple price-based logic"""
        try:
            for token in tokens:
                mint = token.mint
                symbol = token.symbol or 'UNKNOWN'
                
                # Skip if already have position
                if mint in self.positions:
                    continue
                
                # Skip if at max positions
                if len(self.positions) >= self.max_positions:
                    continue
                
                # Skip if insufficient balance
                if self.paper_sol_balance < self.position_size_sol:
                    continue
                
                # Get current prices
                prices = await self.market_data.price_monitor.fetch_prices([mint])
                if mint not in prices or not prices[mint]:
                    continue
                
                price_data = prices[mint]
                current_price_sol = price_data.get('price_sol')
                current_price_usd = price_data.get('price_usd')
                
                if not current_price_sol or not current_price_usd:
                    continue
                
                # Simple entry logic: random entry for demo (in real system, use technical indicators)
                import random
                if random.random() > 0.95:  # 5% chance to enter per check
                    await self.enter_position(token, current_price_sol, current_price_usd)
                    
        except Exception as e:
            logger.error(f"Error checking entry signals: {e}")
    
    async def enter_position(self, token, price_sol: float, price_usd: float):
        """Enter a new paper trading position"""
        try:
            mint = token.mint
            symbol = token.symbol or 'UNKNOWN'
            
            # Calculate position
            amount_tokens = self.position_size_sol / price_sol
            cost_sol = self.position_size_sol
            cost_usd = price_usd * amount_tokens
            
            # Create position
            position = SimplePaperPosition(
                mint=mint,
                symbol=symbol,
                entry_price_sol=price_sol,
                entry_price_usd=price_usd,
                amount=amount_tokens,
                entry_time=datetime.now(timezone.utc),
                cost_sol=cost_sol,
                cost_usd=cost_usd
            )
            
            # Update balances
            self.paper_sol_balance -= cost_sol
            self.positions[mint] = position
            self.trade_count += 1
            
            logger.info(f"🟢 ENTERED POSITION: {symbol}")
            logger.info(f"   Price: {price_sol:.8f} SOL (${price_usd:.6f})")
            logger.info(f"   Amount: {amount_tokens:,.0f} tokens")
            logger.info(f"   Cost: {cost_sol:.2f} SOL (${cost_usd:.2f})")
            logger.info(f"   Remaining Balance: {self.paper_sol_balance:.2f} SOL")
            
        except Exception as e:
            logger.error(f"Error entering position for {token.symbol}: {e}")
    
    async def check_exit_conditions(self):
        """Check exit conditions for existing positions"""
        try:
            positions_to_close = []
            
            for mint, position in self.positions.items():
                # Get current prices
                prices = await self.market_data.price_monitor.fetch_prices([mint])
                if mint not in prices or not prices[mint]:
                    continue
                
                price_data = prices[mint]
                current_price_sol = price_data.get('price_sol')
                current_price_usd = price_data.get('price_usd')
                
                if not current_price_sol or not current_price_usd:
                    continue
                
                # Calculate P&L
                current_value_sol = current_price_sol * position.amount
                pnl_sol = current_value_sol - position.cost_sol
                pnl_pct = (pnl_sol / position.cost_sol) * 100
                
                # Check exit conditions
                should_exit = False
                exit_reason = ""
                
                # Stop loss
                if pnl_pct <= -self.stop_loss_pct * 100:
                    should_exit = True
                    exit_reason = f"Stop Loss ({pnl_pct:.1f}%)"
                
                # Take profit
                elif pnl_pct >= self.take_profit_pct * 100:
                    should_exit = True
                    exit_reason = f"Take Profit ({pnl_pct:.1f}%)"
                
                # Time-based exit (hold for max 10 minutes for demo)
                elif (datetime.now(timezone.utc) - position.entry_time).total_seconds() > 600:
                    should_exit = True
                    exit_reason = f"Time Limit ({pnl_pct:.1f}%)"
                
                if should_exit:
                    positions_to_close.append((mint, position, exit_reason, current_price_sol, current_price_usd, pnl_sol))
            
            # Close positions
            for mint, position, reason, exit_price_sol, exit_price_usd, pnl_sol in positions_to_close:
                await self.exit_position(mint, position, reason, exit_price_sol, exit_price_usd, pnl_sol)
                
        except Exception as e:
            logger.error(f"Error checking exit conditions: {e}")
    
    async def exit_position(self, mint: str, position: SimplePaperPosition, reason: str, 
                          exit_price_sol: float, exit_price_usd: float, pnl_sol: float):
        """Exit a paper trading position"""
        try:
            # Calculate final values
            exit_value_sol = exit_price_sol * position.amount
            exit_value_usd = exit_price_usd * position.amount
            pnl_usd = exit_value_usd - position.cost_usd
            pnl_pct = (pnl_sol / position.cost_sol) * 100
            
            # Update balances
            self.paper_sol_balance += exit_value_sol
            self.total_pnl_sol += pnl_sol
            self.total_pnl_usd += pnl_usd
            self.trade_count += 1
            
            # Log the exit
            logger.info(f"🔴 EXITED POSITION: {position.symbol}")
            logger.info(f"   Entry: {position.entry_price_sol:.8f} SOL (${position.entry_price_usd:.6f})")
            logger.info(f"   Exit: {exit_price_sol:.8f} SOL (${exit_price_usd:.6f})")
            logger.info(f"   P&L: {pnl_sol:+.6f} SOL (${pnl_usd:+.2f}) [{pnl_pct:+.1f}%]")
            logger.info(f"   Reason: {reason}")
            logger.info(f"   Duration: {(datetime.now(timezone.utc) - position.entry_time).total_seconds():.0f}s")
            logger.info(f"   New Balance: {self.paper_sol_balance:.2f} SOL")
            
            # Remove position
            del self.positions[mint]
            
        except Exception as e:
            logger.error(f"Error exiting position for {position.symbol}: {e}")
    
    async def log_portfolio_status(self):
        """Log current portfolio status"""
        try:
            if not self.positions:
                logger.info(f"📊 PORTFOLIO: {self.paper_sol_balance:.2f} SOL | No open positions")
                return
            
            logger.info("📊 PORTFOLIO STATUS:")
            total_unrealized_sol = 0
            
            for mint, position in self.positions.items():
                # Get current price
                prices = await self.market_data.price_monitor.fetch_prices([mint])
                if mint in prices and prices[mint]:
                    price_data = prices[mint]
                    current_price_sol = price_data.get('price_sol')
                    
                    if current_price_sol:
                        current_value_sol = current_price_sol * position.amount
                        unrealized_pnl_sol = current_value_sol - position.cost_sol
                        unrealized_pnl_pct = (unrealized_pnl_sol / position.cost_sol) * 100
                        total_unrealized_sol += unrealized_pnl_sol
                        
                        logger.info(f"   {position.symbol}: {unrealized_pnl_sol:+.6f} SOL [{unrealized_pnl_pct:+.1f}%]")
            
            total_portfolio_value = self.paper_sol_balance + sum(pos.cost_sol for pos in self.positions.values()) + total_unrealized_sol
            total_pnl = self.total_pnl_sol + total_unrealized_sol
            
            logger.info(f"📈 TOTAL PORTFOLIO: {total_portfolio_value:.2f} SOL | P&L: {total_pnl:+.6f} SOL")
            logger.info(f"📊 TRADES: {self.trade_count} | POSITIONS: {len(self.positions)}")
            
        except Exception as e:
            logger.error(f"Error logging portfolio status: {e}")
    
    async def trading_loop(self, tokens):
        """Main trading loop"""
        logger.info("🚀 Starting Simple Live Paper Trading Loop")
        
        last_signal_check = 0
        last_status_log = 0
        
        while self.is_running:
            try:
                current_time = time.time()
                
                # Check for entry signals every 60 seconds
                if current_time - last_signal_check >= 60:
                    await self.check_for_entry_signals(tokens)
                    last_signal_check = current_time
                
                # Check exit conditions every 30 seconds
                await self.check_exit_conditions()
                
                # Log portfolio status every 2 minutes
                if current_time - last_status_log >= 120:
                    await self.log_portfolio_status()
                    last_status_log = current_time
                
                # Sleep between checks
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(60)
    
    async def run_demo(self, duration_minutes: int = 15):
        """Run the complete live paper trading demo"""
        try:
            # Initialize system
            if not await self.initialize():
                logger.error("Failed to initialize system")
                return
            
            # Select tokens
            tokens = await self.select_tokens_for_trading(max_tokens=5)
            if not tokens:
                logger.error("No tokens selected for trading")
                return
            
            # Start monitoring
            await self.start_monitoring(tokens)
            
            # Wait for initial data
            logger.info("⏳ Waiting for initial price data...")
            await asyncio.sleep(15)
            
            # Start trading
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            
            logger.info("🎯 STARTING SIMPLE LIVE PAPER TRADING")
            logger.info(f"   Duration: {duration_minutes} minutes")
            logger.info(f"   Starting Balance: {self.paper_sol_balance} SOL")
            logger.info(f"   Max Positions: {self.max_positions}")
            logger.info(f"   Position Size: {self.position_size_sol} SOL")
            logger.info("=" * 60)
            
            # Run trading loop with timeout
            try:
                await asyncio.wait_for(self.trading_loop(tokens), timeout=duration_minutes * 60)
            except asyncio.TimeoutError:
                logger.info(f"⏰ Trading session completed after {duration_minutes} minutes")
            
            # Stop trading
            await self.stop()
            
        except Exception as e:
            logger.error(f"Error in demo: {e}")
        finally:
            await self.cleanup()
    
    async def stop(self):
        """Stop trading and show final summary"""
        try:
            logger.info("🛑 Stopping Simple Live Paper Trading...")
            self.is_running = False
            
            # Close all open positions
            for mint in list(self.positions.keys()):
                position = self.positions[mint]
                
                # Get current price for final exit
                prices = await self.market_data.price_monitor.fetch_prices([mint])
                if mint in prices and prices[mint]:
                    price_data = prices[mint]
                    current_price_sol = price_data.get('price_sol')
                    current_price_usd = price_data.get('price_usd')
                    
                    if current_price_sol and current_price_usd:
                        current_value_sol = current_price_sol * position.amount
                        pnl_sol = current_value_sol - position.cost_sol
                        await self.exit_position(mint, position, "Session End", current_price_sol, current_price_usd, pnl_sol)
            
            # Final summary
            runtime = datetime.now(timezone.utc) - self.start_time if self.start_time else timedelta(0)
            final_balance = self.paper_sol_balance
            total_return = ((final_balance - 100.0) / 100.0) * 100  # Starting balance was 100 SOL
            
            logger.info("\n" + "="*60)
            logger.info("📊 FINAL TRADING SESSION SUMMARY")
            logger.info("="*60)
            logger.info(f"⏱️  Duration: {runtime.total_seconds() / 60:.1f} minutes")
            logger.info(f"💰 Starting Balance: 100.00 SOL")
            logger.info(f"💰 Final Balance: {final_balance:.2f} SOL")
            logger.info(f"📈 Total Return: {total_return:+.2f}%")
            logger.info(f"📊 Total Trades: {self.trade_count}")
            logger.info(f"💰 Total P&L: {self.total_pnl_sol:+.6f} SOL (${self.total_pnl_usd:+.2f})")
            
            if self.trade_count > 0:
                avg_pnl = self.total_pnl_sol / (self.trade_count // 2) if self.trade_count > 1 else self.total_pnl_sol
                logger.info(f"📈 Average P&L per trade: {avg_pnl:+.6f} SOL")
            
            logger.info("✅ Simple Live Paper Trading completed successfully")
            
        except Exception as e:
            logger.error(f"Error stopping trading: {e}")
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            logger.info("🧹 Cleaning up resources...")
            
            if self.market_data:
                await self.market_data.close()
            if self.db:
                await self.db.close()
            
            logger.info("✅ Cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

async def main():
    """Main function"""
    try:
        trading_system = SimpleLivePaperTrading()
        
        # Run for 10 minutes
        await trading_system.run_demo(duration_minutes=10)
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping...")
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    print("🚀 SUPERTRADEX SIMPLE LIVE PAPER TRADING")
    print("=" * 50)
    print("Live paper trading with real market data")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    
    asyncio.run(main()) 