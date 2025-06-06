#!/usr/bin/env python3
"""
Simple Live Monitor - Updates every 1 minute
Shows: Prices, Indicators, Trade Info
"""

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.settings import Settings
from data.token_database import TokenDatabase
from utils.logger import get_logger

logger = get_logger("LiveMonitor")

class SimpleLiveMonitor:
    def __init__(self):
        self.settings = Settings()
        self.db = None
        self.monitored_tokens = []
        
    async def initialize(self):
        """Initialize database connection."""
        try:
            db_path = "/Users/morpheus/berkode/supertradex/outputs/supertradex.db"
            self.db = TokenDatabase(db_path, self.settings)
            await self.db.initialize()
            print("✅ Database initialized")
        except Exception as e:
            print(f"❌ Database init failed: {e}")
            
    async def get_monitored_tokens(self):
        """Get currently monitored tokens."""
        try:
            if self.db:
                tokens = await self.db.get_top_tokens_for_trading(limit=3)
                return tokens[:3] if tokens else []
        except Exception as e:
            print(f"❌ Error getting tokens: {e}")
        return []
        
    def parse_recent_logs(self):
        """Parse recent log entries for prices and activity."""
        try:
            log_file = "/Users/morpheus/berkode/supertradex/outputs/supertradex.log"
            with open(log_file, 'r') as f:
                lines = f.readlines()
                
            # Get last 100 lines
            recent_lines = lines[-100:] if len(lines) > 100 else lines
            
            prices = {}
            activity_count = 0
            latest_activity = None
            
            for line in recent_lines:
                # Parse Jupiter API prices
                if "💰 JUPITER_API price:" in line:
                    try:
                        parts = line.split("💰 JUPITER_API price:")[1].strip()
                        if "|" in parts:
                            symbol = parts.split("|")[0].strip()
                            price_part = parts.split("|")[2].strip()
                            price = price_part.split(" SOL")[0].strip()
                            prices[symbol] = price
                    except:
                        pass
                        
                # Count PumpSwap activity
                if "PumpSwap" in line and ("BUY" in line or "SELL" in line or "Swap" in line):
                    activity_count += 1
                    if not latest_activity:
                        latest_activity = line.strip()
                        
            return prices, activity_count, latest_activity
            
        except Exception as e:
            print(f"❌ Error parsing logs: {e}")
            return {}, 0, None
            
    def display_monitor(self, prices, activity_count, latest_activity):
        """Display the monitoring information."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Clear screen and show header
        print("\033[2J\033[H")  # Clear screen
        print("=" * 80)
        print(f"🚀 SUPERTRADEX LIVE MONITOR - {timestamp}")
        print("=" * 80)
        
        # System Status
        print("\n📊 SYSTEM STATUS:")
        print(f"   ✅ Status: RUNNING")
        print(f"   🔄 Update: Every 1 minute")
        print(f"   💼 Paper Trading: 1000 SOL")
        
        # Token Prices
        print("\n💰 TOKEN PRICES (Jupiter API):")
        if prices:
            for symbol, price in prices.items():
                print(f"   🎯 {symbol}: {price} SOL")
        else:
            print("   ⏳ Waiting for price updates...")
            
        # Market Activity
        print(f"\n🔥 MARKET ACTIVITY:")
        print(f"   📈 PumpSwap Transactions: {activity_count} (last 100 logs)")
        print(f"   🌊 Market Status: {'VERY ACTIVE' if activity_count > 20 else 'ACTIVE' if activity_count > 5 else 'QUIET'}")
        
        # Trading Indicators
        print(f"\n🎯 TRADING INDICATORS:")
        print(f"   📊 RSI Range: 35-65 (Enhanced Sensitivity)")
        print(f"   🎪 Strategy: Conservative (Capital Preservation)")
        print(f"   ⚡ Signal Frequency: Every 30 seconds")
        
        # Recent Activity
        print(f"\n📝 LATEST ACTIVITY:")
        if latest_activity:
            # Clean up the log line for display
            clean_activity = latest_activity.replace("I ", "").replace("data.market_data: ", "")
            if len(clean_activity) > 70:
                clean_activity = clean_activity[:70] + "..."
            print(f"   {clean_activity}")
        else:
            print("   ⏳ No recent activity detected")
            
        print("\n" + "=" * 80)
        print("Press Ctrl+C to stop monitoring")
        print("=" * 80)
        
    async def run_monitor(self):
        """Main monitoring loop."""
        print("🚀 Starting SuperTradeX Live Monitor...")
        print("📊 Updates every 1 minute")
        print("Press Ctrl+C to stop\n")
        
        await self.initialize()
        
        try:
            while True:
                # Get current data
                prices, activity_count, latest_activity = self.parse_recent_logs()
                
                # Display monitor
                self.display_monitor(prices, activity_count, latest_activity)
                
                # Wait 1 minute
                await asyncio.sleep(60)
                
        except KeyboardInterrupt:
            print("\n\n🛑 Monitor stopped by user")
        except Exception as e:
            print(f"\n❌ Monitor error: {e}")
        finally:
            if self.db:
                await self.db.close()

async def main():
    monitor = SimpleLiveMonitor()
    await monitor.run_monitor()

if __name__ == "__main__":
    asyncio.run(main()) 