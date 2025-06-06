#!/usr/bin/env python3
"""
Comprehensive Live Paper Trading Pipeline Test
Tests the complete flow: Scan -> Select -> Monitor -> Trade
"""
import asyncio
import sys
from pathlib import Path
import time
from datetime import datetime, timezone
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Settings
from data.token_database import TokenDatabase
from data.token_scanner import TokenScanner
from data.market_data import MarketData
from strategies.strategy_evaluator import StrategyEvaluator
from strategies.entry_exit import EntryExitStrategy
from config.thresholds import Thresholds
from filters.filter_manager import FilterManager
from config.dexscreener_api import DexScreenerAPI
from data.token_metrics import TokenMetrics
from config.rugcheck_api import RugcheckAPI

class TradingPipelineTest:
    def __init__(self):
        self.settings = Settings()
        self.db = None
        self.token_scanner = None
        self.market_data = None
        self.strategy_evaluator = None
        self.current_best_token = None
        
    async def initialize(self):
        """Initialize all components"""
        print("🔧 Initializing trading pipeline components...")
        
        # Initialize database
        self.db = await TokenDatabase.create(self.settings.DATABASE_FILE_PATH, self.settings)
        
        # Initialize other components
        thresholds = Thresholds(self.settings)
        filter_manager = FilterManager(self.settings, thresholds)
        dexscreener_api = DexScreenerAPI(self.settings)
        token_metrics = TokenMetrics(self.settings)
        rugcheck_api = RugcheckAPI(self.settings)
        
        # Initialize market data
        self.market_data = MarketData(self.settings, dexscreener_api, self.db)
        await self.market_data.initialize()
        
        # Initialize token scanner
        self.token_scanner = TokenScanner(
            db=self.db,
            settings=self.settings,
            thresholds=thresholds,
            filter_manager=filter_manager,
            market_data=self.market_data,
            dexscreener_api=dexscreener_api,
            token_metrics=token_metrics,
            rugcheck_api=rugcheck_api
        )
        await self.token_scanner.initialize()
        
        # Initialize strategy evaluator
        entry_exit_strategy = EntryExitStrategy(
            settings=self.settings,
            db=self.db,
            trade_queue=None,  # Paper trading mode
            market_data=self.market_data,
            thresholds=thresholds
        )
        await entry_exit_strategy.initialize()
        
        self.strategy_evaluator = StrategyEvaluator(
            settings=self.settings,
            db=self.db,
            market_data=self.market_data,
            entry_exit_strategy=entry_exit_strategy
        )
        
        print("✅ All components initialized successfully!")
        
    async def step1_scan_and_show_db(self):
        """Step 1: Scan for tokens and show database contents"""
        print("\n" + "="*60)
        print("📊 STEP 1: TOKEN SCANNING & DATABASE ANALYSIS")
        print("="*60)
        
        # Show current database state
        tokens = await self.db.get_tokens_list()
        print(f"📈 Current database contains {len(tokens)} tokens")
        
        if tokens:
            print("\n🔍 Top 10 tokens by volume:")
            sorted_tokens = sorted(tokens, key=lambda x: x.volume_24h or 0, reverse=True)[:10]
            for i, token in enumerate(sorted_tokens, 1):
                status_emoji = "🟢" if token.monitoring_status == "active" else "🔴" if token.monitoring_status == "monitoring_failed" else "🟡"
                print(f"  {i:2d}. {status_emoji} {token.symbol:8s} | Vol: ${token.volume_24h:>12,.0f} | Liq: ${token.liquidity:>10,.0f} | Rug: {token.rugcheck_score:>4.1f}")
        
        # Run a fresh scan
        print(f"\n🔄 Running fresh token scan...")
        await self.token_scanner.scan_tokens()
        
        # Show updated database state
        new_tokens = await self.db.get_tokens_list()
        new_count = len(new_tokens) - len(tokens)
        print(f"✅ Scan complete! Added {new_count} new tokens. Total: {len(new_tokens)} tokens")
        
        if new_count > 0:
            print("\n🆕 Newly discovered tokens:")
            newest_tokens = sorted(new_tokens, key=lambda x: x.last_updated, reverse=True)[:5]
            for token in newest_tokens:
                if token not in tokens:
                    print(f"  • {token.symbol:8s} | Vol: ${token.volume_24h:>12,.0f} | Liq: ${token.liquidity:>10,.0f} | Rug: {token.rugcheck_score:>4.1f}")
        
        return await self._wait_for_approval("Continue to token selection?")
    
    async def step2_select_best_token(self):
        """Step 2: Select best token with detailed explanation"""
        print("\n" + "="*60)
        print("🎯 STEP 2: BEST TOKEN SELECTION & ANALYSIS")
        print("="*60)
        
        # Get all eligible tokens
        all_tokens = await self.db.get_tokens_list()
        eligible_tokens = []
        
        print("🔍 Analyzing token eligibility...")
        
        for token in all_tokens:
            # Check basic criteria
            is_eligible = True
            reasons = []
            
            # Volume check
            min_volume = getattr(self.settings, 'MIN_VOLUME_24H', 10000)
            if not token.volume_24h or token.volume_24h < min_volume:
                is_eligible = False
                reasons.append(f"Volume ${token.volume_24h or 0:,.0f} < ${min_volume:,.0f}")
            
            # Liquidity check
            min_liquidity = getattr(self.settings, 'MIN_LIQUIDITY', 1000)
            if not token.liquidity or token.liquidity < min_liquidity:
                is_eligible = False
                reasons.append(f"Liquidity ${token.liquidity or 0:,.0f} < ${min_liquidity:,.0f}")
            
            # RugCheck score check
            min_rugcheck = getattr(self.settings, 'MIN_RUGCHECK_SCORE', 10)
            if not token.rugcheck_score or token.rugcheck_score < min_rugcheck:
                is_eligible = False
                reasons.append(f"RugCheck {token.rugcheck_score or 0:.1f} < {min_rugcheck:.1f}")
            
            # Overall filter check
            if not token.overall_filter_passed:
                is_eligible = False
                reasons.append("Failed overall filters")
            
            # DEX check (only monitor supported DEXs)
            monitored_dexs = ['pumpswap', 'raydium_v4', 'raydium_clmm']
            if token.dex_id not in monitored_dexs:
                is_eligible = False
                reasons.append(f"DEX '{token.dex_id}' not monitored")
            
            if is_eligible:
                eligible_tokens.append(token)
            else:
                print(f"  ❌ {token.symbol:8s}: {', '.join(reasons)}")
        
        print(f"\n✅ Found {len(eligible_tokens)} eligible tokens out of {len(all_tokens)} total")
        
        if not eligible_tokens:
            print("⚠️  No eligible tokens found! Relaxing criteria...")
            # Get best available token even if not perfect
            best_token = await self.db.get_best_token_for_trading(include_inactive_tokens=True)
        else:
            # Rank eligible tokens by composite score
            print("\n📊 Ranking eligible tokens:")
            
            for token in eligible_tokens:
                # Calculate composite score
                volume_score = min((token.volume_24h or 0) / 100000, 10)  # Max 10 points for $100k+ volume
                liquidity_score = min((token.liquidity or 0) / 10000, 5)  # Max 5 points for $10k+ liquidity
                rugcheck_score = min((token.rugcheck_score or 0) / 20, 5)  # Max 5 points for 20+ rugcheck
                
                composite_score = volume_score + liquidity_score + rugcheck_score
                token.composite_score = composite_score
                
                print(f"  🏆 {token.symbol:8s} | Score: {composite_score:5.1f} | Vol: ${token.volume_24h:>10,.0f} | Liq: ${token.liquidity:>8,.0f} | Rug: {token.rugcheck_score:>4.1f}")
            
            # Select best token
            best_token = max(eligible_tokens, key=lambda x: x.composite_score)
        
        if best_token:
            self.current_best_token = best_token
            print(f"\n🎯 SELECTED BEST TOKEN: {best_token.symbol}")
            print(f"   Mint: {best_token.mint}")
            print(f"   DEX: {best_token.dex_id}")
            print(f"   Pair: {best_token.pair_address}")
            print(f"   Volume 24h: ${best_token.volume_24h:,.2f}")
            print(f"   Liquidity: ${best_token.liquidity:,.2f}")
            print(f"   RugCheck Score: {best_token.rugcheck_score:.1f}")
            print(f"   Composite Score: {getattr(best_token, 'composite_score', 'N/A')}")
            
            # Explain selection reasoning
            print(f"\n💡 SELECTION REASONING:")
            print(f"   • High trading volume indicates active market interest")
            print(f"   • Sufficient liquidity ensures we can enter/exit positions")
            print(f"   • RugCheck score above threshold reduces scam risk")
            print(f"   • DEX '{best_token.dex_id}' is supported for monitoring")
            print(f"   • Token passed all filter criteria")
        else:
            print("❌ No suitable token found!")
            return False
        
        return await self._wait_for_approval(f"Start monitoring {best_token.symbol}?")
    
    async def step3_monitor_token(self):
        """Step 3: Monitor token prices and indicators"""
        print("\n" + "="*60)
        print(f"📈 STEP 3: MONITORING {self.current_best_token.symbol}")
        print("="*60)
        
        if not self.current_best_token:
            print("❌ No token selected for monitoring!")
            return False
        
        # Start monitoring
        print(f"🔄 Starting monitoring for {self.current_best_token.symbol}...")
        success = await self.market_data.add_token_for_monitoring(
            mint=self.current_best_token.mint,
            pair_address=self.current_best_token.pair_address,
            dex_id=self.current_best_token.dex_id
        )
        
        if not success:
            print(f"❌ Failed to start monitoring {self.current_best_token.symbol}")
            return False
        
        print(f"✅ Successfully started monitoring {self.current_best_token.symbol}")
        
        # Set active mint in strategy evaluator
        self.strategy_evaluator.entry_exit_strategy.set_active_mint(self.current_best_token.mint)
        
        # Monitor for a period and show price updates
        print(f"\n📊 Monitoring prices and indicators for 2 minutes...")
        print(f"{'Time':<12} {'Price (SOL)':<15} {'Price (USD)':<12} {'RSI':<8} {'Signal':<10}")
        print("-" * 70)
        
        monitoring_duration = 120  # 2 minutes
        start_time = time.time()
        price_count = 0
        
        while time.time() - start_time < monitoring_duration:
            try:
                # Get current price
                price_data = await self.market_data.get_current_price(self.current_best_token.mint)
                
                if price_data and price_data.get('price'):
                    price_sol = price_data.get('price_sol', price_data.get('price'))
                    price_usd = price_data.get('price_usd', 0)
                    
                    # Get trading signal
                    signal = await self.strategy_evaluator.entry_exit_strategy.get_signal_on_price_event(
                        event_data={
                            'mint': self.current_best_token.mint,
                            'price': price_sol,
                            'timestamp': datetime.now(timezone.utc)
                        },
                        pool_address=self.current_best_token.pair_address,
                        dex_id=self.current_best_token.dex_id
                    )
                    
                    # Get price history for RSI calculation
                    price_history = self.strategy_evaluator.entry_exit_strategy.price_history.get(self.current_best_token.mint, [])
                    rsi = "N/A"
                    if len(price_history) >= 14:
                        # Simple RSI approximation
                        recent_prices = list(price_history)[-14:]
                        gains = [max(0, recent_prices[i] - recent_prices[i-1]) for i in range(1, len(recent_prices))]
                        losses = [max(0, recent_prices[i-1] - recent_prices[i]) for i in range(1, len(recent_prices))]
                        avg_gain = sum(gains) / len(gains) if gains else 0
                        avg_loss = sum(losses) / len(losses) if losses else 0
                        if avg_loss > 0:
                            rs = avg_gain / avg_loss
                            rsi = f"{100 - (100 / (1 + rs)):.1f}"
                    
                    signal_text = signal['action'] if signal else "HOLD"
                    current_time = datetime.now().strftime("%H:%M:%S")
                    
                    print(f"{current_time:<12} {price_sol:<15.8f} ${price_usd:<11.6f} {rsi:<8} {signal_text:<10}")
                    price_count += 1
                    
                    # If we get a signal, break early
                    if signal and signal.get('action') in ['BUY', 'SELL']:
                        print(f"\n🚨 TRADING SIGNAL DETECTED: {signal['action']}")
                        print(f"   Reason: {signal.get('reason', 'N/A')}")
                        print(f"   Confidence: {signal.get('confidence', 'N/A')}")
                        break
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                print(f"❌ Error during monitoring: {e}")
                await asyncio.sleep(5)
        
        print(f"\n📊 Monitoring complete. Collected {price_count} price updates.")
        
        return await self._wait_for_approval("Proceed to trading simulation?")
    
    async def step4_execute_paper_trades(self):
        """Step 4: Execute paper trades and show results"""
        print("\n" + "="*60)
        print(f"💰 STEP 4: PAPER TRADING SIMULATION")
        print("="*60)
        
        if not self.current_best_token:
            print("❌ No token selected for trading!")
            return False
        
        print(f"🎯 Simulating paper trades for {self.current_best_token.symbol}")
        
        # Simulate trading session
        trade_amount_usd = 100.0  # $100 paper trade
        position = None
        trade_count = 0
        total_pnl = 0.0
        
        print(f"\n💵 Starting with ${trade_amount_usd:.2f} paper money")
        print(f"{'Time':<12} {'Action':<6} {'Price':<12} {'Quantity':<12} {'Value':<12} {'P&L':<12} {'Reason':<20}")
        print("-" * 100)
        
        # Trading simulation for 3 minutes
        trading_duration = 180  # 3 minutes
        start_time = time.time()
        
        while time.time() - start_time < trading_duration:
            try:
                # Get current price
                price_data = await self.market_data.get_current_price(self.current_best_token.mint)
                
                if price_data and price_data.get('price'):
                    current_price = price_data.get('price_sol', price_data.get('price'))
                    current_time = datetime.now().strftime("%H:%M:%S")
                    
                    # Get trading signal
                    signal = await self.strategy_evaluator.entry_exit_strategy.get_signal_on_price_event(
                        event_data={
                            'mint': self.current_best_token.mint,
                            'price': current_price,
                            'timestamp': datetime.now(timezone.utc)
                        },
                        pool_address=self.current_best_token.pair_address,
                        dex_id=self.current_best_token.dex_id
                    )
                    
                    # Execute trades based on signals
                    if signal and signal.get('action') == 'BUY' and position is None:
                        # Enter position
                        quantity = trade_amount_usd / (current_price * 174.26)  # Approximate SOL/USD rate
                        position = {
                            'entry_price': current_price,
                            'quantity': quantity,
                            'entry_time': time.time(),
                            'entry_value': trade_amount_usd
                        }
                        trade_count += 1
                        
                        print(f"{current_time:<12} {'BUY':<6} {current_price:<12.8f} {quantity:<12.2f} ${trade_amount_usd:<11.2f} {'$0.00':<12} {signal.get('reason', 'Signal')[:20]:<20}")
                    
                    elif signal and signal.get('action') == 'SELL' and position is not None:
                        # Exit position
                        current_value = position['quantity'] * current_price * 174.26  # Approximate SOL/USD rate
                        pnl = current_value - position['entry_value']
                        total_pnl += pnl
                        
                        print(f"{current_time:<12} {'SELL':<6} {current_price:<12.8f} {position['quantity']:<12.2f} ${current_value:<11.2f} ${pnl:<11.2f} {signal.get('reason', 'Signal')[:20]:<20}")
                        
                        position = None
                        trade_count += 1
                    
                    # Show current position status
                    elif position is not None:
                        current_value = position['quantity'] * current_price * 174.26
                        unrealized_pnl = current_value - position['entry_value']
                        
                        # Check for time-based exit (hold for max 60 seconds)
                        if time.time() - position['entry_time'] > 60:
                            total_pnl += unrealized_pnl
                            print(f"{current_time:<12} {'SELL':<6} {current_price:<12.8f} {position['quantity']:<12.2f} ${current_value:<11.2f} ${unrealized_pnl:<11.2f} {'Time limit':<20}")
                            position = None
                            trade_count += 1
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                print(f"❌ Error during trading: {e}")
                await asyncio.sleep(10)
        
        # Close any remaining position
        if position is not None:
            try:
                price_data = await self.market_data.get_current_price(self.current_best_token.mint)
                if price_data and price_data.get('price'):
                    final_price = price_data.get('price_sol', price_data.get('price'))
                    final_value = position['quantity'] * final_price * 174.26
                    final_pnl = final_value - position['entry_value']
                    total_pnl += final_pnl
                    
                    current_time = datetime.now().strftime("%H:%M:%S")
                    print(f"{current_time:<12} {'SELL':<6} {final_price:<12.8f} {position['quantity']:<12.2f} ${final_value:<11.2f} ${final_pnl:<11.2f} {'Session end':<20}")
                    trade_count += 1
            except Exception as e:
                print(f"❌ Error closing final position: {e}")
        
        # Trading summary
        print("\n" + "="*60)
        print("📊 TRADING SESSION SUMMARY")
        print("="*60)
        print(f"🎯 Token: {self.current_best_token.symbol}")
        print(f"⏱️  Duration: {trading_duration // 60} minutes")
        print(f"📈 Total Trades: {trade_count}")
        print(f"💰 Total P&L: ${total_pnl:.2f}")
        print(f"📊 Return: {(total_pnl / trade_amount_usd) * 100:.2f}%")
        
        if trade_count > 0:
            print(f"📈 Average P&L per trade: ${total_pnl / (trade_count // 2 if trade_count > 1 else 1):.2f}")
        
        return True
    
    async def _wait_for_approval(self, message):
        """Wait for user approval to continue"""
        print(f"\n⏸️  {message}")
        response = input("   Press Enter to continue, 'q' to quit: ").strip().lower()
        if response == 'q':
            print("🛑 Test stopped by user")
            return False
        return True
    
    async def run_full_test(self):
        """Run the complete trading pipeline test"""
        try:
            print("🚀 STARTING COMPREHENSIVE TRADING PIPELINE TEST")
            print("=" * 60)
            
            await self.initialize()
            
            # Step 1: Scan and show database
            if not await self.step1_scan_and_show_db():
                return
            
            # Step 2: Select best token
            if not await self.step2_select_best_token():
                return
            
            # Step 3: Monitor token
            if not await self.step3_monitor_token():
                return
            
            # Step 4: Execute paper trades
            if not await self.step4_execute_paper_trades():
                return
            
            print("\n🎉 TRADING PIPELINE TEST COMPLETED SUCCESSFULLY!")
            
        except Exception as e:
            print(f"\n❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # Cleanup
            if self.market_data:
                await self.market_data.close()
            if self.db:
                await self.db.close()

async def main():
    """Main test function"""
    test = TradingPipelineTest()
    await test.run_full_test()

if __name__ == "__main__":
    asyncio.run(main()) 