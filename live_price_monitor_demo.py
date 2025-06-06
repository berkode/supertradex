#!/usr/bin/env python3
"""
Live Price Monitor Demo
Demonstrates real-time price monitoring using MarketData and PriceMonitor
"""
import asyncio
import sys
from pathlib import Path
import time
import logging
from datetime import datetime, timezone

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
        logging.FileHandler('live_price_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LivePriceMonitorDemo:
    """Demo class for live price monitoring with real market data"""
    
    def __init__(self):
        self.settings = None
        self.db = None
        self.market_data = None
        self.monitored_tokens = []
        self.is_running = False
        
    async def initialize(self):
        """Initialize components for price monitoring"""
        try:
            logger.info("🔧 Initializing Live Price Monitor Demo...")
            
            # Initialize settings
            self.settings = Settings()
            
            # Initialize database
            self.db = await TokenDatabase.create(self.settings.DATABASE_FILE_PATH, self.settings)
            
            # Initialize APIs
            self.dexscreener_api = DexScreenerAPI(self.settings)
            
            # Initialize market data
            self.market_data = MarketData(self.settings, self.dexscreener_api, self.db)
            await self.market_data.initialize()
            
            logger.info("✅ Live Price Monitor Demo initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize: {e}")
            return False
    
    async def select_tokens_to_monitor(self, max_tokens: int = 5):
        """Select top tokens from database for monitoring"""
        try:
            logger.info(f"🔍 Selecting top {max_tokens} tokens for monitoring...")
            
            # Get all tokens from database
            all_tokens = await self.db.get_tokens_list()
            if not all_tokens:
                logger.warning("No tokens found in database")
                return []
            
            # Filter and sort by volume
            eligible_tokens = []
            for token in all_tokens:
                if (token.volume_24h and token.volume_24h > 10000 and  # $10k+ volume
                    token.liquidity and token.liquidity > 1000 and     # $1k+ liquidity
                    token.dex_id in ['raydium_v4', 'raydium_clmm', 'pumpswap']):
                    eligible_tokens.append(token)
            
            # Sort by volume and take top tokens
            eligible_tokens.sort(key=lambda x: x.volume_24h or 0, reverse=True)
            selected_tokens = eligible_tokens[:max_tokens]
            
            logger.info(f"✅ Selected {len(selected_tokens)} tokens for monitoring:")
            for i, token in enumerate(selected_tokens, 1):
                logger.info(f"  {i}. {token.symbol or 'UNKNOWN'} | Vol: ${token.volume_24h:,.0f} | Liq: ${token.liquidity:,.0f}")
            
            return selected_tokens
            
        except Exception as e:
            logger.error(f"Error selecting tokens: {e}")
            return []
    
    async def start_monitoring(self, tokens):
        """Start monitoring selected tokens using PriceMonitor polling"""
        try:
            logger.info("📊 Starting price monitoring via PriceMonitor polling...")
            
            for token in tokens:
                # Add token directly to PriceMonitor for polling
                self.market_data.price_monitor.add_token(token.mint)
                
                self.monitored_tokens.append({
                    'mint': token.mint,
                    'symbol': token.symbol or 'UNKNOWN',
                    'last_price_sol': None,
                    'last_price_usd': None,
                    'last_update': None,
                    'price_changes': []
                })
                logger.info(f"✅ Added {token.symbol or 'UNKNOWN'} to PriceMonitor")
            
            logger.info(f"📈 Monitoring {len(self.monitored_tokens)} tokens via polling")
            
        except Exception as e:
            logger.error(f"Error starting monitoring: {e}")
    
    async def price_monitoring_loop(self, duration_minutes: int = 10):
        """Main price monitoring loop using PriceMonitor"""
        logger.info(f"🚀 Starting {duration_minutes}-minute live price monitoring session")
        logger.info("=" * 80)
        logger.info(f"{'Time':<12} {'Token':<10} {'Price (SOL)':<15} {'Price (USD)':<12} {'Change %':<10} {'Status'}")
        logger.info("-" * 80)
        
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)
        update_count = 0
        
        while self.is_running and time.time() < end_time:
            try:
                current_time = datetime.now().strftime("%H:%M:%S")
                
                for token_info in self.monitored_tokens:
                    mint = token_info['mint']
                    symbol = token_info['symbol']
                    
                    # Get current prices using PriceMonitor directly
                    try:
                        # Fetch fresh prices from PriceMonitor
                        prices = await self.market_data.price_monitor.fetch_prices([mint])
                        
                        if mint in prices and prices[mint]:
                            price_data = prices[mint]
                            current_price_sol = price_data.get('price_sol')
                            current_price_usd = price_data.get('price_usd')
                            
                            if current_price_sol and current_price_usd:
                                # Calculate price change
                                change_pct = 0.0
                                status = "NEW"
                                
                                if token_info['last_price_sol']:
                                    change_pct = ((current_price_sol - token_info['last_price_sol']) / token_info['last_price_sol']) * 100
                                    status = "📈" if change_pct > 0 else "📉" if change_pct < 0 else "➡️"
                                
                                # Update token info
                                token_info['last_price_sol'] = current_price_sol
                                token_info['last_price_usd'] = current_price_usd
                                token_info['last_update'] = datetime.now(timezone.utc)
                                
                                # Store price change
                                if abs(change_pct) > 0.1:  # Only log significant changes
                                    token_info['price_changes'].append({
                                        'timestamp': datetime.now(timezone.utc),
                                        'price_sol': current_price_sol,
                                        'price_usd': current_price_usd,
                                        'change_pct': change_pct
                                    })
                                
                                # Log price update
                                print(f"{current_time:<12} {symbol:<10} {current_price_sol:<15.8f} ${current_price_usd:<11.6f} {change_pct:+8.2f}% {status}")
                                update_count += 1
                                
                                # Log significant price movements
                                if abs(change_pct) > 5:  # 5%+ movement
                                    logger.info(f"🚨 SIGNIFICANT MOVE: {symbol} {change_pct:+.2f}% - Price: {current_price_sol:.8f} SOL (${current_price_usd:.6f})")
                            else:
                                logger.debug(f"No valid price data for {symbol}")
                        else:
                            logger.debug(f"No price data returned for {symbol}")
                            
                    except Exception as e:
                        logger.debug(f"Error fetching price for {symbol}: {e}")
                
                # Sleep between updates
                await asyncio.sleep(15)  # Check every 15 seconds
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(30)  # Longer sleep on error
        
        # Session summary
        runtime_minutes = (time.time() - start_time) / 60
        logger.info("\n" + "=" * 80)
        logger.info("📊 PRICE MONITORING SESSION SUMMARY")
        logger.info("=" * 80)
        logger.info(f"⏱️  Duration: {runtime_minutes:.1f} minutes")
        logger.info(f"📈 Price Updates: {update_count}")
        logger.info(f"📊 Tokens Monitored: {len(self.monitored_tokens)}")
        
        # Show price change summary
        for token_info in self.monitored_tokens:
            if token_info['price_changes']:
                changes = token_info['price_changes']
                max_change = max(changes, key=lambda x: abs(x['change_pct']))
                total_changes = len(changes)
                
                logger.info(f"   {token_info['symbol']}: {total_changes} updates, max change: {max_change['change_pct']:+.2f}%")
            else:
                logger.info(f"   {token_info['symbol']}: No price changes recorded")
    
    async def run_demo(self, duration_minutes: int = 10, max_tokens: int = 5):
        """Run the complete price monitoring demo"""
        try:
            # Initialize system
            if not await self.initialize():
                logger.error("Failed to initialize system")
                return
            
            # Select tokens
            tokens = await self.select_tokens_to_monitor(max_tokens)
            if not tokens:
                logger.error("No tokens selected for monitoring")
                return
            
            # Start monitoring
            await self.start_monitoring(tokens)
            
            # Wait for initial data
            logger.info("⏳ Waiting for initial price data...")
            await asyncio.sleep(10)
            
            # Start monitoring loop
            self.is_running = True
            await self.price_monitoring_loop(duration_minutes)
            
        except Exception as e:
            logger.error(f"Error in demo: {e}")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            logger.info("🧹 Cleaning up resources...")
            self.is_running = False
            
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
        demo = LivePriceMonitorDemo()
        
        # Run demo for 3 minutes with 3 tokens
        await demo.run_demo(duration_minutes=3, max_tokens=3)
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping...")
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    print("🚀 SUPERTRADEX LIVE PRICE MONITOR DEMO")
    print("=" * 50)
    print("Monitoring real-time price data for top tokens")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    
    asyncio.run(main()) 