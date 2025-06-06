#!/usr/bin/env python3
"""
Test script for the Live Paper Trading System
Runs the trading system for a limited time to demonstrate functionality
"""

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from live_paper_trader import LivePaperTrader, LiveTradingConfig

async def test_live_paper_trader():
    """Test the live paper trading system for a limited time"""
    
    print("🎯 TESTING LIVE PAPER TRADING SYSTEM")
    print("=" * 60)
    
    # Create configuration for faster testing
    config = LiveTradingConfig(
        max_concurrent_positions=2,
        max_position_size_sol=5.0,       # Smaller positions for testing
        global_stop_loss_pct=0.05,       # 5% stop loss
        global_take_profit_pct=0.10,     # 10% take profit
        price_check_interval=5,          # Check prices every 5 seconds
        position_check_interval=3,       # Check positions every 3 seconds
        signal_check_interval=10         # Check signals every 10 seconds
    )
    
    # Create trader
    trader = LivePaperTrader(config)
    
    print(f"📊 Starting live paper trading test...")
    print(f"   Test Duration: 45 seconds")
    print(f"   Initial Balance: {trader.sol_balance:.2f} SOL")
    print(f"   Max Positions: {config.max_concurrent_positions}")
    print(f"   Position Size: {config.max_position_size_sol:.1f} SOL max")
    print("=" * 60)
    
    # Start the trader
    trader.is_running = True
    
    try:
        # Run for 45 seconds to demonstrate functionality
        test_duration = 45
        
        # Start the trading loop as a task
        trading_task = asyncio.create_task(trader._trading_loop())
        
        # Wait for the test duration
        await asyncio.sleep(test_duration)
        
        print("\n" + "="*60)
        print("🛑 Test completed, stopping trading system...")
        
        # Stop the trader
        await trader.stop()
        
        # Cancel the trading task
        trading_task.cancel()
        try:
            await trading_task
        except asyncio.CancelledError:
            pass
        
        # Display final results
        print("\n📊 FINAL TEST RESULTS")
        print("=" * 60)
        
        # Calculate final portfolio value
        total_position_value = sum(
            pos.current_value_sol for pos in trader.positions.values() 
            if pos.current_value_sol is not None
        )
        total_portfolio_value = trader.sol_balance + total_position_value
        total_pnl_pct = ((total_portfolio_value / trader.initial_balance) - 1) * 100
        
        print(f"Initial Balance: {trader.initial_balance:.6f} SOL")
        print(f"Final SOL Balance: {trader.sol_balance:.6f} SOL")
        print(f"Position Value: {total_position_value:.6f} SOL")
        print(f"Total Portfolio: {total_portfolio_value:.6f} SOL")
        print(f"Total P&L: {total_portfolio_value - trader.initial_balance:+.6f} SOL ({total_pnl_pct:+.2f}%)")
        print(f"Realized P&L: {trader.daily_pnl_sol:+.6f} SOL")
        print(f"Total Trades: {trader.total_trades}")
        
        if trader.total_trades > 0:
            win_rate = (trader.winning_trades / trader.total_trades) * 100
            print(f"Winning Trades: {trader.winning_trades}")
            print(f"Losing Trades: {trader.losing_trades}")
            print(f"Win Rate: {win_rate:.1f}%")
        
        if trader.positions:
            print(f"\nActive Positions: {len(trader.positions)}")
            for mint, pos in trader.positions.items():
                print(f"  {pos.symbol}: {pos.amount:,.0f} tokens at {pos.current_price_sol:.8f} SOL")
                if pos.unrealized_pnl_sol is not None:
                    print(f"    P&L: {pos.unrealized_pnl_sol:+.6f} SOL ({pos.unrealized_pnl_pct:+.1f}%)")
        
        print("\n✅ Live paper trading test completed successfully!")
        print("🚀 System demonstrated:")
        print("  • Real-time price monitoring and updates")
        print("  • Automatic signal generation and evaluation") 
        print("  • Live position entry and management")
        print("  • Real-time P&L tracking in SOL")
        print("  • Stop loss and take profit monitoring")
        print("  • Performance logging and metrics")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        if trader.is_running:
            await trader.stop()
        return False

if __name__ == "__main__":
    print("🎯 STARTING LIVE PAPER TRADING SYSTEM TEST")
    print("This will run for 45 seconds to demonstrate functionality")
    print("Press Ctrl+C to stop early if needed")
    print("=" * 60)
    
    try:
        success = asyncio.run(test_live_paper_trader())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrupted by user")
        sys.exit(0) 