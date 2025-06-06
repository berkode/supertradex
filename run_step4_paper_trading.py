#!/usr/bin/env python3
"""
Run Step 4: Paper Trading Simulation Only
"""
import asyncio
import sys
from pathlib import Path
import time
import random
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from data.token_database import TokenDatabase

async def run_paper_trading_simulation():
    """Run paper trading simulation with the best token from database"""
    try:
        print("🚀 STARTING PAPER TRADING SIMULATION")
        print("=" * 60)
        
        # Initialize database
        settings = Settings()
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        
        # Get all tokens and select the best one
        all_tokens = await db.get_tokens_list()
        if not all_tokens:
            print("❌ No tokens found in database!")
            return
        
        # Select token with highest volume
        best_token = max(all_tokens, key=lambda x: x.volume_24h or 0)
        
        print(f"🎯 SELECTED TOKEN: {best_token.symbol or 'UNKNOWN'}")
        print(f"   Mint: {best_token.mint}")
        print(f"   Volume 24h: ${best_token.volume_24h or 0:,.2f}")
        print(f"   Liquidity: ${best_token.liquidity or 0:,.2f}")
        print(f"   RugCheck Score: {best_token.rugcheck_score or 0:.1f}")
        print(f"   DEX: {best_token.dex_id or 'N/A'}")
        
        print("\n" + "="*60)
        print(f"💰 PAPER TRADING SIMULATION FOR {best_token.symbol or 'UNKNOWN'}")
        print("="*60)
        
        # Simulate trading session with mock prices
        trade_amount_usd = 100.0  # $100 paper trade
        position = None
        trade_count = 0
        total_pnl = 0.0
        
        # Start with a base price (simulate getting initial price)
        base_price = 0.001  # $0.001 starting price
        current_price = base_price
        
        print(f"📊 Starting paper trading simulation...")
        print(f"💰 Trade Amount: ${trade_amount_usd}")
        print(f"💲 Starting Price: ${current_price:.6f}")
        
        # Simulate 30 price updates over 5 minutes
        start_time = time.time()
        for i in range(30):
            # Simulate price movement (±5% random walk)
            price_change = random.uniform(-0.05, 0.05)
            current_price *= (1 + price_change)
            
            # Simple trading logic: buy low, sell high
            if position is None and price_change < -0.02:  # Buy on 2%+ dip
                position = {
                    'type': 'long',
                    'entry_price': current_price,
                    'amount': trade_amount_usd / current_price,
                    'entry_time': time.time()
                }
                print(f"🟢 BUY  | Price: ${current_price:.6f} | Amount: {position['amount']:.2f} tokens")
                
            elif position and position['type'] == 'long' and price_change > 0.015:  # Sell on 1.5%+ gain
                exit_price = current_price
                pnl = (exit_price - position['entry_price']) * position['amount']
                total_pnl += pnl
                trade_count += 1
                
                print(f"🔴 SELL | Price: ${exit_price:.6f} | P&L: ${pnl:.2f} | Total P&L: ${total_pnl:.2f}")
                position = None
            
            # Show price updates every 5 iterations
            if i % 5 == 0:
                trend = "📈" if price_change > 0 else "📉"
                print(f"{trend} Price: ${current_price:.6f} | Change: {price_change*100:+.2f}%")
            
            await asyncio.sleep(0.2)  # 200ms between updates
        
        # Close any open position
        if position:
            exit_price = current_price
            pnl = (exit_price - position['entry_price']) * position['amount']
            total_pnl += pnl
            trade_count += 1
            print(f"🔴 CLOSE | Price: ${exit_price:.6f} | P&L: ${pnl:.2f} | Total P&L: ${total_pnl:.2f}")
        
        trading_duration = time.time() - start_time
        
        # Trading summary
        print("\n" + "="*60)
        print("📊 TRADING SESSION SUMMARY")
        print("="*60)
        print(f"🎯 Token: {best_token.symbol or 'UNKNOWN'}")
        print(f"⏱️  Duration: {trading_duration:.1f} seconds")
        print(f"📈 Total Trades: {trade_count}")
        print(f"💰 Total P&L: ${total_pnl:.2f}")
        print(f"📊 Return: {(total_pnl / trade_amount_usd) * 100:.2f}%")
        print(f"💲 Final Price: ${current_price:.6f}")
        print(f"📈 Price Change: {((current_price - base_price) / base_price) * 100:+.2f}%")
        
        if total_pnl > 0:
            print("🎉 PROFITABLE SESSION! 💰")
        elif total_pnl < 0:
            print("📉 Loss session - better luck next time!")
        else:
            print("🤝 Break-even session")
        
        # Cleanup
        await db.close()
        print("\n✅ Paper trading simulation completed!")
        
    except Exception as e:
        print(f"❌ Error in paper trading simulation: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Main function"""
    await run_paper_trading_simulation()

if __name__ == "__main__":
    asyncio.run(main()) 