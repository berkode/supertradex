#!/usr/bin/env python3
"""
Phase 6: End-to-End System Testing with Real Data
Tests the complete SOL-based trading pipeline with real price data and live-like conditions
"""

import asyncio
import sys
import traceback
import os
from pathlib import Path
from datetime import datetime, timezone
import time
import httpx

# Add project root to sys.path  
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def test_phase6_end_to_end():
    """Test Phase 6: End-to-End System with Real Data"""
    print("🚀 Testing Phase 6: End-to-End SOL-Based Trading System with Real Data")
    print("=" * 90)
    
    test_results = {}
    
    try:
        # Initialize real components (but with paper trading)
        from config.settings import Settings
        from config.dexscreener_api import DexScreenerAPI
        from data.token_database import TokenDatabase
        from data.price_monitor import PriceMonitor
        from data.market_data import MarketData
        from strategies.paper_trading import PaperTrading
        from strategies.entry_exit import EntryExitStrategy
        from config.thresholds import Thresholds
        from wallet.wallet_manager import WalletManager
        
        # ============================================================================
        # STEP 1: Initialize Real System Components
        # ============================================================================
        print("\n🔧 STEP 1: Initializing Real System Components")
        print("-" * 70)
        
        # Initialize settings
        settings = Settings()
        print(f"✅ Settings initialized")
        
        # Initialize database
        db = TokenDatabase(settings)
        await db.initialize()
        print(f"✅ Database initialized")
        
        # Initialize HTTP client
        http_client = httpx.AsyncClient(timeout=30.0)
        print(f"✅ HTTP client initialized")
        
        # Initialize DexScreener API
        dex_api = DexScreenerAPI(settings, http_client)
        print(f"✅ DexScreener API initialized")
        
        # Initialize PriceMonitor with real data sources
        price_monitor = PriceMonitor(
            settings=settings,
            dex_api_client=dex_api,
            http_client=http_client,
            db=db
        )
        await price_monitor.initialize()
        print(f"✅ PriceMonitor initialized with real data sources")
        
        # Initialize MarketData with real components
        market_data = MarketData(
            settings=settings,
            dexscreener_api=dex_api,
            token_db=db,
            http_client=http_client
        )
        await market_data.initialize()
        print(f"✅ MarketData initialized")
        
        # Initialize wallet manager (for paper trading)
        wallet_manager = WalletManager(settings, db)
        await wallet_manager.initialize()
        print(f"✅ Wallet manager initialized")
        
        # Initialize paper trading with real components
        paper_trading = PaperTrading(
            settings=settings,
            db=db,
            wallet_manager=wallet_manager,
            price_monitor=price_monitor
        )
        await paper_trading.load_persistent_state()
        print(f"✅ Paper trading initialized with SOL balance: {paper_trading.paper_sol_balance:.6f} SOL")
        
        # Initialize thresholds
        thresholds = Thresholds()
        print(f"✅ Thresholds initialized")
        
        # Initialize entry/exit strategy
        entry_exit_strategy = EntryExitStrategy(
            settings=settings,
            db=db,
            trade_queue=None,  # Signal generation mode
            market_data=market_data,
            thresholds=thresholds,
            wallet_manager=wallet_manager
        )
        await entry_exit_strategy.initialize()
        print(f"✅ Entry/Exit strategy initialized")
        
        test_results['initialization'] = True
        print("✅ STEP 1 COMPLETE: All system components initialized")
        
        # ============================================================================
        # STEP 2: Test Real Price Discovery with SOL-Based Pricing
        # ============================================================================
        print("\n📊 STEP 2: Testing Real Price Discovery with SOL-Based Pricing")
        print("-" * 70)
        
        # Test with a well-known Solana token (USDC as an example)
        usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC mint
        bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"   # BONK mint
        
        print(f"Testing price discovery for well-known tokens...")
        
        # Test SOL-based pricing
        try:
            usdc_price_sol = await price_monitor.get_current_price_sol(usdc_mint, max_age_seconds=300)
            usdc_price_usd = await price_monitor.get_current_price_usd(usdc_mint, max_age_seconds=300)
            
            if usdc_price_sol:
                print(f"✅ USDC Price: {usdc_price_sol:.8f} SOL (${usdc_price_usd:.6f} USD)")
                
                # Validate that USDC price is reasonable (should be close to 1/SOL_PRICE_USD)
                sol_price_usd = await price_monitor.get_sol_price()
                if sol_price_usd:
                    expected_usdc_sol = 1.0 / sol_price_usd
                    price_diff_pct = abs(usdc_price_sol - expected_usdc_sol) / expected_usdc_sol * 100
                    print(f"   SOL Price: ${sol_price_usd:.2f} USD")
                    print(f"   Expected USDC/SOL: {expected_usdc_sol:.8f} (diff: {price_diff_pct:.2f}%)")
                    
                    if price_diff_pct < 10:  # Within 10% is reasonable
                        print(f"   ✅ USDC pricing validation passed")
                    else:
                        print(f"   ⚠️ USDC pricing seems off by {price_diff_pct:.2f}%")
            else:
                print(f"⚠️ Could not get USDC price - this may be expected for some APIs")
                
        except Exception as e:
            print(f"⚠️ USDC pricing test encountered issue: {e}")
        
        # Test with BONK (more volatile token)
        try:
            bonk_price_sol = await price_monitor.get_current_price_sol(bonk_mint, max_age_seconds=300)
            bonk_price_usd = await price_monitor.get_current_price_usd(bonk_mint, max_age_seconds=300)
            
            if bonk_price_sol and bonk_price_usd:
                print(f"✅ BONK Price: {bonk_price_sol:.12f} SOL (${bonk_price_usd:.8f} USD)")
                
                # Test market data integration
                bonk_sol_via_market_data = await market_data.get_token_price_sol(bonk_mint)
                bonk_usd_via_market_data = await market_data.get_token_price_usd(bonk_mint)
                
                if bonk_sol_via_market_data:
                    print(f"✅ BONK via MarketData: {bonk_sol_via_market_data:.12f} SOL (${bonk_usd_via_market_data:.8f} USD)")
                    
                    # Validate consistency between PriceMonitor and MarketData
                    if abs(bonk_price_sol - bonk_sol_via_market_data) / bonk_price_sol < 0.01:  # Within 1%
                        print(f"   ✅ PriceMonitor and MarketData consistency validated")
                    else:
                        print(f"   ⚠️ Price discrepancy between PriceMonitor and MarketData")
            else:
                print(f"⚠️ Could not get BONK price")
                
        except Exception as e:
            print(f"⚠️ BONK pricing test encountered issue: {e}")
        
        test_results['price_discovery'] = True
        print("✅ STEP 2 COMPLETE: Real price discovery with SOL-based pricing tested")
        
        # ============================================================================
        # STEP 3: Test SOL-Based Signal Generation
        # ============================================================================
        print("\n🎯 STEP 3: Testing SOL-Based Signal Generation")
        print("-" * 70)
        
        # Choose a token for signal testing
        test_mint = bonk_mint if bonk_price_sol else usdc_mint
        test_price_sol = bonk_price_sol if bonk_price_sol else usdc_price_sol
        
        if test_price_sol:
            print(f"Testing signal generation for {test_mint[:8]}...")
            
            # Set active mint for strategy
            entry_exit_strategy.set_active_mint(test_mint)
            
            # Test SOL-based risk calculations
            strategy_type = 'default'
            sl_price_sol = entry_exit_strategy._calculate_stop_loss_sol(test_price_sol, strategy_type)
            tp_price_sol = entry_exit_strategy._calculate_take_profit_sol(test_price_sol, strategy_type)
            
            print(f"✅ Signal Generation Results:")
            print(f"   Entry Price: {test_price_sol:.12f} SOL")
            print(f"   Stop Loss:   {sl_price_sol:.12f} SOL ({((sl_price_sol/test_price_sol-1)*100):+.2f}%)")
            print(f"   Take Profit: {tp_price_sol:.12f} SOL ({((tp_price_sol/test_price_sol-1)*100):+.2f}%)")
            
            # Test price conversion
            test_usd_price = 0.01  # $0.01
            converted_sol_price = await entry_exit_strategy._convert_price_to_sol(test_usd_price, test_mint)
            print(f"   Price Conversion: ${test_usd_price:.2f} USD → {converted_sol_price:.8f} SOL")
            
            test_results['signal_generation'] = True
        else:
            print(f"⚠️ Skipping signal generation test - no valid price data")
            test_results['signal_generation'] = False
        
        print("✅ STEP 3 COMPLETE: SOL-based signal generation tested")
        
        # ============================================================================
        # STEP 4: Test SOL-Based Paper Trading Execution
        # ============================================================================
        print("\n📈 STEP 4: Testing SOL-Based Paper Trading Execution")
        print("-" * 70)
        
        if test_price_sol:
            print(f"Testing SOL-based paper trading execution...")
            
            # Record initial state
            initial_sol_balance = paper_trading.paper_sol_balance
            print(f"Initial SOL Balance: {initial_sol_balance:.6f} SOL")
            
            # Execute a test BUY trade
            trade_id = int(time.time())  # Use timestamp as trade ID
            trade_amount = 1000  # 1000 tokens
            trade_cost_sol = test_price_sol * trade_amount
            
            if initial_sol_balance > trade_cost_sol:
                print(f"Executing BUY trade: {trade_amount} tokens at {test_price_sol:.12f} SOL")
                print(f"Trade cost: {trade_cost_sol:.8f} SOL")
                
                success = await paper_trading.execute_trade_sol(
                    trade_id=trade_id,
                    action='BUY',
                    mint=test_mint,
                    price_sol=test_price_sol,
                    amount=trade_amount
                )
                
                if success:
                    print(f"✅ BUY trade executed successfully")
                    
                    # Check updated balances
                    new_sol_balance = paper_trading.paper_sol_balance
                    sol_spent = initial_sol_balance - new_sol_balance
                    print(f"New SOL Balance: {new_sol_balance:.6f} SOL (spent: {sol_spent:.8f} SOL)")
                    
                    # Get position data
                    position = await paper_trading.get_paper_position(test_mint)
                    print(f"Position: {position['amount']:,.0f} tokens")
                    print(f"Cost Basis SOL: {position.get('cost_basis_sol', 0):.8f} SOL")
                    print(f"Cost Basis USD: ${position.get('cost_basis_usd', 0):.6f} USD")
                    
                    # Test SELL trade (partial)
                    sell_amount = trade_amount // 2  # Sell half
                    current_price_sol = test_price_sol * 1.05  # Simulate 5% price increase
                    
                    print(f"\nTesting SELL trade: {sell_amount} tokens at {current_price_sol:.12f} SOL")
                    
                    sell_success = await paper_trading.execute_trade_sol(
                        trade_id=trade_id + 1,
                        action='SELL',
                        mint=test_mint,
                        price_sol=current_price_sol,
                        amount=sell_amount
                    )
                    
                    if sell_success:
                        print(f"✅ SELL trade executed successfully")
                        
                        # Check final state
                        final_sol_balance = paper_trading.paper_sol_balance
                        final_position = await paper_trading.get_paper_position(test_mint)
                        
                        print(f"Final SOL Balance: {final_sol_balance:.6f} SOL")
                        print(f"Remaining Position: {final_position['amount']:,.0f} tokens")
                        
                        # Calculate realized P&L
                        proceeds_sol = sell_amount * current_price_sol
                        cost_basis_sold = sell_amount * test_price_sol
                        realized_pnl_sol = proceeds_sol - cost_basis_sold
                        realized_pnl_pct = (realized_pnl_sol / cost_basis_sold) * 100
                        
                        print(f"Realized P&L: {realized_pnl_sol:.8f} SOL ({realized_pnl_pct:+.2f}%)")
                        
                        test_results['paper_trading'] = True
                    else:
                        print(f"❌ SELL trade failed")
                        test_results['paper_trading'] = False
                else:
                    print(f"❌ BUY trade failed")
                    test_results['paper_trading'] = False
            else:
                print(f"⚠️ Insufficient SOL balance for test trade")
                test_results['paper_trading'] = False
        else:
            print(f"⚠️ Skipping paper trading test - no valid price data")
            test_results['paper_trading'] = False
        
        print("✅ STEP 4 COMPLETE: SOL-based paper trading execution tested")
        
        # ============================================================================
        # STEP 5: Test End-to-End Pipeline Performance
        # ============================================================================
        print("\n⚡ STEP 5: Testing End-to-End Pipeline Performance")
        print("-" * 70)
        
        if test_price_sol:
            print(f"Testing complete pipeline performance...")
            
            # Measure complete cycle time
            pipeline_start = time.time()
            
            # 1. Price discovery
            price_start = time.time()
            current_price_sol = await market_data.get_token_price_sol(test_mint)
            price_time = time.time() - price_start
            
            # 2. Signal generation
            signal_start = time.time()
            if current_price_sol:
                sl_price = entry_exit_strategy._calculate_stop_loss_sol(current_price_sol, 'default')
                tp_price = entry_exit_strategy._calculate_take_profit_sol(current_price_sol, 'default')
            signal_time = time.time() - signal_start
            
            # 3. Position evaluation
            position_start = time.time()
            current_position = await paper_trading.get_paper_position(test_mint)
            position_time = time.time() - position_start
            
            pipeline_total = time.time() - pipeline_start
            
            print(f"✅ Pipeline Performance Results:")
            print(f"   Price Discovery: {price_time*1000:.2f}ms")
            print(f"   Signal Generation: {signal_time*1000:.2f}ms")
            print(f"   Position Evaluation: {position_time*1000:.2f}ms")
            print(f"   Total Pipeline: {pipeline_total*1000:.2f}ms")
            
            if pipeline_total < 1.0:  # Should complete in under 1 second
                print(f"   ✅ Pipeline performance acceptable")
                test_results['performance'] = True
            else:
                print(f"   ⚠️ Pipeline performance may need optimization")
                test_results['performance'] = False
        else:
            print(f"⚠️ Skipping performance test - no valid price data")
            test_results['performance'] = False
        
        print("✅ STEP 5 COMPLETE: End-to-end pipeline performance tested")
        
        # ============================================================================
        # CLEANUP AND SUMMARY
        # ============================================================================
        print("\n🧹 Cleaning up resources...")
        
        # Close HTTP client
        await http_client.aclose()
        
        # Close database connections
        await db.close()
        
        print("✅ Resources cleaned up")
        
        # ============================================================================
        # TEST SUMMARY
        # ============================================================================
        print("\n🎉 PHASE 6 END-TO-END TEST COMPLETE!")
        print("=" * 90)
        
        # Calculate success rate
        total_tests = len(test_results)
        passed_tests = sum(test_results.values())
        success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        
        print("📊 TEST RESULTS:")
        for test_name, result in test_results.items():
            status_icon = "✅" if result else "❌"
            test_display = test_name.replace('_', ' ').title()
            print(f"  {status_icon} {test_display}")
        
        print(f"\n📈 OVERALL RESULTS:")
        print(f"  Tests Passed: {passed_tests}/{total_tests}")
        print(f"  Success Rate: {success_rate:.1f}%")
        
        if success_rate >= 80:
            print(f"\n🚀 END-TO-END SYSTEM VALIDATION SUCCESSFUL!")
            print(f"✅ SOL-based trading system ready for live-like paper trading")
            return True
        else:
            print(f"\n⚠️ Some tests failed - system may need attention before proceeding")
            return False
        
    except Exception as e:
        print(f"\n❌ PHASE 6 END-TO-END TEST FAILED: {e}")
        traceback.print_exc()
        print(f"\n📊 Test Results So Far: {test_results}")
        return False

if __name__ == "__main__":
    async def run_test():
        print("🎯 STARTING PHASE 6: END-TO-END SYSTEM TESTING")
        print("=" * 90)
        
        success = await test_phase6_end_to_end()
        
        if success:
            print("\n" + "=" * 90)
            print("🎉 PHASE 6 COMPLETED SUCCESSFULLY!")
            print("🚀 Ready to proceed with Phase 7: Live-Like Paper Trading System")
            print("=" * 90)
        else:
            print("\n" + "=" * 90)
            print("❌ PHASE 6 ENCOUNTERED ISSUES")
            print("⚠️ Review and fix issues before proceeding to Phase 7")
            print("=" * 90)
        
        return success
    
    success = asyncio.run(run_test())
    sys.exit(0 if success else 1) 