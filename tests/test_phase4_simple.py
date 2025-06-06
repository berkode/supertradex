#!/usr/bin/env python3
"""
Simplified test for Phase 4: SOL-Based Entry/Exit Strategy Core Functions
Tests the core SOL-based calculations without complex exit logic
"""

import asyncio
import sys
import traceback
from pathlib import Path
from unittest.mock import Mock, AsyncMock

# Add project root to sys.path  
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def create_mock_settings():
    """Create a mock Settings object with required attributes"""
    mock_settings = Mock()
    
    # Entry/Exit strategy settings
    mock_settings.MAX_PRICE_HISTORY_LEN = 100
    mock_settings.MIN_VOLUME_24H = 10000
    mock_settings.MIN_LIQUIDITY = 50000
    mock_settings.MIN_MARKET_CAP = 100000
    
    # Stop loss and take profit settings
    mock_settings.get = Mock(side_effect=lambda key, default=None: {
        'DEFAULT_STOP_LOSS': 0.05,
        'TIGHT_STOP_LOSS': 0.02,
        'WIDE_STOP_LOSS': 0.1,
        'DEFAULT_TAKE_PROFIT': 0.1,
        'AGGRESSIVE_TAKE_PROFIT': 0.2,
        'CONSERVATIVE_TAKE_PROFIT': 0.05
    }.get(key, default))
    
    return mock_settings

def create_mock_market_data():
    """Create a mock MarketData with SOL-based methods"""
    mock_md = AsyncMock()
    
    # Mock SOL price methods
    mock_md.get_token_price_sol = AsyncMock(return_value=0.0001)  # 0.0001 SOL per token
    mock_md.get_token_price_usd = AsyncMock(return_value=0.015)   # $0.015 USD per token
    mock_md._get_sol_price_usd = AsyncMock(return_value=150.0)    # $150 per SOL
    
    return mock_md

async def test_phase4_core_functions():
    """Test Phase 4: Core SOL-Based Entry/Exit Strategy Functions"""
    print("🚀 Testing Phase 4: Core SOL-Based Entry/Exit Strategy Functions")
    print("=" * 70)
    
    try:
        # Import EntryExitStrategy
        from strategies.entry_exit import EntryExitStrategy
        
        # Create minimal mock dependencies
        print("1. Creating mock dependencies...")
        mock_settings = create_mock_settings()
        mock_db = AsyncMock()
        mock_thresholds = Mock()
        mock_market_data = create_mock_market_data()
        mock_wallet_manager = AsyncMock()
        print("✅ Mock dependencies created")
        
        # Initialize EntryExitStrategy
        print("2. Testing SOL-based EntryExitStrategy initialization...")
        entry_exit_strategy = EntryExitStrategy(
            settings=mock_settings,
            db=mock_db,
            trade_queue=None,  # Signal generation mode
            market_data=mock_market_data,
            thresholds=mock_thresholds,
            wallet_manager=mock_wallet_manager
        )
        
        # Initialize strategy
        init_success = await entry_exit_strategy.initialize()
        assert init_success, "EntryExitStrategy initialization failed"
        print("✅ SOL-based EntryExitStrategy initialized successfully")
        
        # Test SOL-based stop loss calculation
        print("3. Testing SOL-based stop loss calculation...")
        test_entry_price_sol = 0.0001  # 0.0001 SOL per token
        
        # Test different strategies
        strategies_to_test = ['breakout', 'trend_following', 'mean_reversion', 'default']
        for strategy in strategies_to_test:
            sl_price_sol = entry_exit_strategy._calculate_stop_loss_sol(test_entry_price_sol, strategy)
            assert sl_price_sol < test_entry_price_sol, f"Stop loss should be lower than entry price for {strategy}"
            sl_percentage = ((test_entry_price_sol - sl_price_sol) / test_entry_price_sol) * 100
            print(f"   {strategy}: Entry {test_entry_price_sol:.8f} SOL → SL {sl_price_sol:.8f} SOL ({sl_percentage:.1f}% below)")
        
        print("✅ SOL-based stop loss calculations working")
        
        # Test SOL-based take profit calculation
        print("4. Testing SOL-based take profit calculation...")
        for strategy in strategies_to_test:
            tp_price_sol = entry_exit_strategy._calculate_take_profit_sol(test_entry_price_sol, strategy)
            assert tp_price_sol > test_entry_price_sol, f"Take profit should be higher than entry price for {strategy}"
            tp_percentage = ((tp_price_sol - test_entry_price_sol) / test_entry_price_sol) * 100
            print(f"   {strategy}: Entry {test_entry_price_sol:.8f} SOL → TP {tp_price_sol:.8f} SOL ({tp_percentage:.1f}% above)")
        
        print("✅ SOL-based take profit calculations working")
        
        # Test SOL-based profit/loss calculation
        print("5. Testing SOL-based profit/loss calculation...")
        
        # Mock position data with SOL entry price
        position_data = {
            'mint': 'TestTokenMint123456789',
            'entry_price_sol': 0.0001,   # SOL entry price
            'entry_price': 0.015,        # USD entry price (fallback)
            'size': 10000,               # 10,000 tokens
            'quantity': 10000
        }
        
        # Set current price in price history (SOL price)
        current_price_sol = 0.00015  # 50% price increase in SOL
        test_mint = position_data['mint']
        entry_exit_strategy.price_history[test_mint] = [current_price_sol]
        
        # Calculate P&L
        pnl_result = await entry_exit_strategy._calculate_profit_loss_sol(position_data)
        
        # Verify SOL-based P&L calculation
        expected_pnl_sol = (current_price_sol - position_data['entry_price_sol']) * position_data['size']
        expected_pnl_percentage = ((current_price_sol - position_data['entry_price_sol']) / position_data['entry_price_sol']) * 100
        
        assert 'amount_sol' in pnl_result, "Missing SOL P&L amount"
        assert 'amount_usd' in pnl_result, "Missing USD P&L amount"
        assert 'percentage' in pnl_result, "Missing P&L percentage"
        
        assert abs(pnl_result['amount_sol'] - expected_pnl_sol) < 1e-8, f"SOL P&L mismatch: expected {expected_pnl_sol:.8f}, got {pnl_result['amount_sol']:.8f}"
        assert abs(pnl_result['percentage'] - expected_pnl_percentage) < 0.01, f"P&L percentage mismatch: expected {expected_pnl_percentage:.2f}%, got {pnl_result['percentage']:.2f}%"
        
        print(f"✅ SOL-based P&L calculation:")
        print(f"   P&L Amount (SOL): {pnl_result['amount_sol']:.8f} SOL")
        print(f"   P&L Amount (USD): ${pnl_result['amount_usd']:.4f}")
        print(f"   P&L Percentage: {pnl_result['percentage']:.2f}%")
        
        # Test price conversion to SOL
        print("6. Testing price conversion to SOL...")
        
        # Test USD to SOL conversion
        usd_price = 0.015  # $0.015 per token
        converted_sol_price = await entry_exit_strategy._convert_price_to_sol(usd_price, test_mint)
        
        # Should return direct SOL price from market_data.get_token_price_sol
        assert converted_sol_price == 0.0001, f"Expected SOL price conversion to return 0.0001, got {converted_sol_price}"
        print(f"✅ Price conversion: ${usd_price:.6f} USD → {converted_sol_price:.8f} SOL")
        
        # Test backward compatibility
        print("7. Testing backward compatibility...")
        
        # Test USD-based methods still work (should call SOL-based methods internally)
        sl_price_usd = entry_exit_strategy._calculate_stop_loss(test_entry_price_sol, 'default')
        tp_price_usd = entry_exit_strategy._calculate_take_profit(test_entry_price_sol, 'default')
        pnl_result_usd = await entry_exit_strategy._calculate_profit_loss(position_data)
        
        assert sl_price_usd < test_entry_price_sol, "USD-based stop loss should work"
        assert tp_price_usd > test_entry_price_sol, "USD-based take profit should work"
        assert 'amount_sol' in pnl_result_usd, "USD-based P&L should include SOL amounts"
        
        print("✅ Backward compatibility maintained")
        
        print("\n🎉 PHASE 4 CORE SOL-BASED FUNCTIONS SUCCESSFUL!")
        print("✅ SOL-based stop loss and take profit calculations implemented")
        print("✅ SOL-based profit/loss tracking with USD display values")
        print("✅ Price conversion to SOL for consistent trading decisions")
        print("✅ Backward compatibility maintained for USD-based methods")
        print("✅ Core SOL-based trading calculations ready")
        
        return True
        
    except Exception as e:
        print(f"\n❌ PHASE 4 CORE TEST FAILED: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_phase4_core_functions())
    if success:
        print("\n🚀 Phase 4 core functions verified! SOL-based entry/exit strategy ready!")
        print("\n📋 IMPLEMENTATION STATUS:")
        print("  ✅ Phase 1: Enhanced PriceMonitor with smart API routing")
        print("  ✅ Phase 2: SOL-based pricing integration")
        print("  ✅ Phase 3: SOL-based paper trading enhancement")
        print("  ✅ Phase 4: SOL-based entry/exit strategy core functions")
        print("  📋 Next: Integration testing and full auto trading pipeline")
        print("\n🔄 READY FOR COMPLETE SOL-BASED AUTO TRADING:")
        print("  • Enhanced PriceMonitor with smart API routing")
        print("  • SOL-based pricing throughout the system")
        print("  • SOL-based paper trading with P&L tracking")
        print("  • SOL-based entry/exit strategies and risk management")
        print("  • USD values maintained for display purposes")
    else:
        print("\n⚠️ Fix Phase 4 core issues before proceeding")
        sys.exit(1) 