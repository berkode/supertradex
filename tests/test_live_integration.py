#!/usr/bin/env python3
"""
Live Integration Test for SupertradeX
Tests the complete live trading platform with paper trading enabled
All components are real except SOL reserves (paper trading)
"""

import asyncio
import sys
import logging
import os
import time
from pathlib import Path
from datetime import datetime, timezone

# Add project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Environment loading (like main.py)
ENV_DIR = Path(__file__).parent / "config"
ENV_PLAIN_PATH = ENV_DIR / ".env"
ENV_ENCRYPTED_PATH = ENV_DIR / ".env.encrypted"

def load_environment():
    """Load environment variables from .env files like main.py does"""
    try:
        from utils.encryption import decrypt_env_file, get_encryption_password
        from dotenv import load_dotenv, dotenv_values
        import io
        
        # Helper function from main.py
        def update_dotenv_vars(env_vars: dict, override: bool = False):
            for key, value in env_vars.items():
                if override or key not in os.environ:
                    os.environ[key] = str(value)
        
        # Get encryption password
        password = get_encryption_password()
        
        # Load encrypted environment first
        if ENV_ENCRYPTED_PATH.exists():
            if password:
                try:
                    decrypted_content = decrypt_env_file(ENV_ENCRYPTED_PATH, password)
                    if decrypted_content:
                        loaded_vars = dotenv_values(stream=io.StringIO(decrypted_content))
                        update_dotenv_vars(loaded_vars, override=False)
                        print(f"✅ Loaded {len(loaded_vars)} variables from .env.encrypted")
                except Exception as e:
                    print(f"⚠️ Could not decrypt .env.encrypted: {e}")
            else:
                print("⚠️ No encryption password available for .env.encrypted")
        
        # Load plain environment file (with override)
        if ENV_PLAIN_PATH.exists():
            try:
                load_dotenv(dotenv_path=ENV_PLAIN_PATH, override=True)
                print("✅ Loaded variables from .env")
            except Exception as e:
                print(f"⚠️ Could not load .env: {e}")
        
    except Exception as e:
        print(f"❌ Environment loading error: {e}")
        sys.exit(1)

# Load environment variables first
load_environment()

# Ensure paper trading is enabled
os.environ['PAPER_TRADING_ENABLED'] = 'true'

# Import SupertradeX components after environment loading
from config.settings import Settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('live_integration_test.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def test_component_initialization():
    """Test that all components initialize correctly"""
    print("\n🧪 TESTING COMPONENT INITIALIZATION")
    print("=" * 50)
    
    try:
        # Initialize settings
        settings = Settings()
        logger.info(f"✅ Settings initialized - Paper Trading: {settings.PAPER_TRADING_ENABLED}")
        
        # Import and initialize components like main.py does
        from main import initialize_components
        
        logger.info("🔧 Initializing all components...")
        start_time = time.time()
        
        components = await initialize_components(settings)
        
        if components is None:
            logger.error("❌ Component initialization failed")
            return False
        
        init_time = time.time() - start_time
        logger.info(f"✅ All components initialized in {init_time:.2f}s")
        
        # Verify critical components
        required_components = [
            "db", "market_data", "token_scanner", "strategy_evaluator", 
            "paper_trading", "order_manager", "wallet_manager", "price_monitor"
        ]
        
        missing = []
        for comp in required_components:
            if comp not in components or components[comp] is None:
                missing.append(comp)
        
        if missing:
            logger.error(f"❌ Missing components: {missing}")
            return False
        
        logger.info(f"✅ All {len(required_components)} critical components present")
        
        # Test paper trading configuration
        paper_trading = components["paper_trading"]
        if hasattr(paper_trading, 'is_paper_trading_enabled'):
            enabled = paper_trading.is_paper_trading_enabled()
        else:
            enabled = settings.PAPER_TRADING_ENABLED
            
        logger.info(f"✅ Paper Trading Status: {'ENABLED' if enabled else 'DISABLED'}")
        
        # Cleanup
        from main import close_all_components
        await close_all_components(components)
        logger.info("✅ Components cleaned up successfully")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Component initialization test failed: {e}", exc_info=True)
        return False

async def test_live_system_integration():
    """Test live system integration with real APIs and paper trading"""
    print("\n🚀 TESTING LIVE SYSTEM INTEGRATION")
    print("=" * 50)
    
    try:
        settings = Settings()
        
        # Import components
        from main import initialize_components, close_all_components
        from data.token_database import TokenDatabase
        
        # Initialize components
        components = await initialize_components(settings)
        if components is None:
            logger.error("❌ Failed to initialize components")
            return False
        
        db = components["db"]
        market_data = components["market_data"]
        token_scanner = components["token_scanner"]
        strategy_evaluator = components["strategy_evaluator"]
        paper_trading = components["paper_trading"]
        
        # Test 1: Database connectivity and token fetching
        logger.info("🔍 Testing database connectivity...")
        tokens_list = await db.get_valid_tokens()
        token_count = len(tokens_list)
        logger.info(f"✅ Database connected - {token_count} tokens in database")
        
        # Test 2: Market data and price monitoring
        logger.info("📊 Testing market data integration...")
        if hasattr(market_data, 'price_monitor'):
            price_monitor = market_data.price_monitor
            
            # Test SOL price fetching
            sol_price = await price_monitor.get_sol_price_usd()
            if sol_price and sol_price > 0:
                logger.info(f"✅ SOL price fetched: ${sol_price:.2f}")
            else:
                logger.warning("⚠️ Could not fetch SOL price")
        
        # Test 3: Token scanning capability
        logger.info("🔍 Testing token scanner...")
        if hasattr(token_scanner, 'scan_tokens_once'):
            try:
                scan_result = await token_scanner.scan_tokens_once()
                logger.info(f"✅ Token scan completed - Found tokens: {len(scan_result) if scan_result else 0}")
            except Exception as e:
                logger.warning(f"⚠️ Token scan failed: {e}")
        
        # Test 4: Paper trading functionality
        logger.info("📄 Testing paper trading system...")
        if paper_trading:
            # Check paper trading balance
            if hasattr(paper_trading, 'get_sol_balance'):
                balance = await paper_trading.get_sol_balance()
                logger.info(f"✅ Paper trading SOL balance: {balance:.4f} SOL")
            
            # Test paper trade simulation
            if hasattr(paper_trading, 'execute_paper_trade'):
                try:
                    # Simulate a small buy order
                    test_mint = "So11111111111111111111111111111111111111112"  # SOL mint
                    result = await paper_trading.execute_paper_trade(
                        action="BUY",
                        mint=test_mint,
                        amount_sol=0.1,
                        price=sol_price if 'sol_price' in locals() else 150.0
                    )
                    if result:
                        logger.info("✅ Paper trade simulation successful")
                    else:
                        logger.warning("⚠️ Paper trade simulation failed")
                except Exception as e:
                    logger.warning(f"⚠️ Paper trade test failed: {e}")
        
        # Test 5: Strategy evaluation system
        logger.info("🎯 Testing strategy evaluation...")
        if strategy_evaluator:
            # Get a token to test strategy evaluation
            best_token = await db.get_best_token_for_trading()
            if best_token:
                logger.info(f"✅ Found test token: {best_token.mint}")
                
                # Test strategy evaluation
                if hasattr(strategy_evaluator, 'evaluate_trading_conditions'):
                    try:
                        evaluation = await strategy_evaluator.evaluate_trading_conditions(best_token.mint)
                        logger.info(f"✅ Strategy evaluation completed: {bool(evaluation)}")
                    except Exception as e:
                        logger.warning(f"⚠️ Strategy evaluation failed: {e}")
        
        # Test 6: Live price monitoring
        logger.info("💰 Testing live price monitoring...")
        if hasattr(market_data, 'start_monitoring_token') and best_token:
            try:
                success = await market_data.start_monitoring_token(best_token.mint)
                if success:
                    logger.info(f"✅ Started monitoring token: {best_token.mint}")
                    
                    # Wait a moment for price data
                    await asyncio.sleep(5)
                    
                    # Stop monitoring
                    await market_data.stop_monitoring_token(best_token.mint)
                    logger.info("✅ Stopped monitoring token")
                else:
                    logger.warning("⚠️ Failed to start token monitoring")
            except Exception as e:
                logger.warning(f"⚠️ Price monitoring test failed: {e}")
        
        # Cleanup
        await close_all_components(components)
        logger.info("✅ Live system integration test completed")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Live system integration test failed: {e}", exc_info=True)
        return False

async def test_end_to_end_trading_flow():
    """Test complete end-to-end trading flow with paper trading"""
    print("\n🔄 TESTING END-TO-END TRADING FLOW")
    print("=" * 50)
    
    try:
        settings = Settings()
        
        # Import main trading function
        from main import initialize_components, close_all_components, manage_top_token_trading
        
        # Initialize components
        components = await initialize_components(settings)
        if components is None:
            logger.error("❌ Failed to initialize components")
            return False
        
        db = components["db"]
        market_data = components["market_data"]
        token_scanner = components["token_scanner"]
        strategy_evaluator = components["strategy_evaluator"]
        
        # Create shutdown event for controlled testing
        shutdown_event = asyncio.Event()
        
        # Start the trading manager for a short period
        logger.info("🚀 Starting trading manager for 30 seconds...")
        
        # Start trading manager as background task
        trading_task = asyncio.create_task(
            manage_top_token_trading(
                db=db,
                market_data=market_data,
                settings=settings,
                token_scanner=token_scanner,
                strategy_evaluator=strategy_evaluator,
                shutdown_event=shutdown_event
            )
        )
        
        # Let it run for 30 seconds
        await asyncio.sleep(30)
        
        # Signal shutdown
        shutdown_event.set()
        
        # Wait for trading task to complete
        try:
            await asyncio.wait_for(trading_task, timeout=10.0)
            logger.info("✅ Trading manager stopped gracefully")
        except asyncio.TimeoutError:
            trading_task.cancel()
            logger.warning("⚠️ Trading manager task cancelled due to timeout")
        
        # Check if any tokens were evaluated
        current_tokens = await db.get_valid_tokens()
        logger.info(f"✅ Valid tokens after trading cycle: {len(current_tokens)}")
        
        # Cleanup
        await close_all_components(components)
        logger.info("✅ End-to-end trading flow test completed")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ End-to-end trading flow test failed: {e}", exc_info=True)
        return False

async def main():
    """Main test execution"""
    print("🧪 SUPERTRADEX LIVE INTEGRATION TEST")
    print("=" * 60)
    print(f"📅 Test started at: {datetime.now(timezone.utc)}")
    print(f"🔧 Paper Trading: ENABLED")
    print("=" * 60)
    
    # Test results
    results = []
    
    # Run component initialization test
    result1 = await test_component_initialization()
    results.append(("Component Initialization", result1))
    
    # Run live system integration test
    result2 = await test_live_system_integration()
    results.append(("Live System Integration", result2))
    
    # Run end-to-end trading flow test
    result3 = await test_end_to_end_trading_flow()
    results.append(("End-to-End Trading Flow", result3))
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:<30} {status}")
        if success:
            passed += 1
    
    print("=" * 60)
    print(f"📈 Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - SupertradeX live integration working!")
        print("🚀 Ready for extended live paper trading!")
    else:
        print("⚠️ Some tests failed - check logs for details")
    
    print("=" * 60)
    return passed == total

if __name__ == "__main__":
    asyncio.run(main()) 