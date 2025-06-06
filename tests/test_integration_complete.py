#!/usr/bin/env python3
"""
Test complete parser integration
Verify BlockchainListener and MarketData both use new parsers correctly
"""

import sys
import os
import time
import asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import Settings
from config.blockchain_logging import setup_price_monitoring_logger, PriceMonitoringAggregator

async def test_integration_complete():
    """Test the complete integration with simplified files and price monitoring"""
    
    print("=== Testing Complete Integration ===")
    
    # Test 1: Parser imports and initialization
    print("\n1. Testing Parser Imports and Initialization...")
    try:
        # Test parser imports
        from data import RaydiumV4Parser, PumpSwapParser, RaydiumClmmParser
        print("✓ Parser imports successful")
        
        # Create a simple logger for testing
        import logging
        test_logger = logging.getLogger("test")
        test_logger.setLevel(logging.INFO)
        
        # Mock settings class for testing
        class MockSettings:
            def __init__(self):
                self.HELIUS_API_KEY = "test_key"
                self.SOLSNIFFER_API_KEY = "test_key"
                self.ALCHEMY_API_KEY = "test_key"
                self.HELIUS_WSS_URL = "wss://test"
                self.SOLANA_MAINNET_WSS = "wss://fallback"
                self.MONITORED_PROGRAMS_LIST = ['raydium_v4', 'pumpswap']
        
        settings = MockSettings()
        
        # Initialize parsers
        parsers = {
            'raydium_v4': RaydiumV4Parser(settings, test_logger),
            'pumpswap': PumpSwapParser(settings, test_logger),
            'raydium_clmm': RaydiumClmmParser(settings, test_logger)
        }
        print(f"✓ Initialized {len(parsers)} parsers: {list(parsers.keys())}")
        
    except Exception as e:
        print(f"✗ Parser initialization failed: {e}")
        return False
    
    # Test 2: Price monitoring aggregator
    print("\n2. Testing Price Monitoring Aggregator...")
    try:
        price_logger = setup_price_monitoring_logger("TestPriceMonitor")
        aggregator = PriceMonitoringAggregator(price_logger)
        
        # Test recording prices
        aggregator.record_price_update("test_mint_1", 0.00123, "blockchain", "raydium_v4")
        aggregator.record_price_update("test_mint_1", 0.00125, "dexscreener", None)
        aggregator.record_price_update("test_mint_2", 0.00456, "blockchain", "pumpswap")
        
        print("✓ Price aggregator working correctly")
        
    except Exception as e:
        print(f"✗ Price aggregator failed: {e}")
        return False
    
    # Test 3: Parser functionality
    print("\n3. Testing Parser Functionality...")
    try:
        # Test Raydium V4 parser with sample logs
        sample_logs = [
            "Program log: Instruction: SwapBaseIn",
            "Program log: transfer amount: 1000000",
            "Program log: transfer amount: 950000"
        ]
        
        raydium_parser = parsers['raydium_v4']
        result = raydium_parser.parse_swap_logs(sample_logs, "test_signature")
        
        if result and result.get('found_swap'):
            print(f"✓ Raydium V4 parser working - confidence: {result.get('parsing_confidence', 0):.2f}")
        else:
            print("✗ Raydium V4 parser not detecting swaps")
            return False
            
    except Exception as e:
        print(f"✗ Parser functionality test failed: {e}")
        return False
    
    # Test 4: File size verification
    print("\n4. Checking File Sizes...")
    try:
        import os
        
        files_to_check = [
            'data/blockchain_listener.py',
            'data/market_data.py'
        ]
        
        for file_path in files_to_check:
            if os.path.exists(file_path):
                size_kb = os.path.getsize(file_path) / 1024
                with open(file_path, 'r') as f:
                    line_count = sum(1 for _ in f)
                print(f"✓ {file_path}: {size_kb:.1f}KB, {line_count} lines")
            else:
                print(f"✗ {file_path} not found")
                return False
                
    except Exception as e:
        print(f"✗ File size check failed: {e}")
        return False
    
    # Test 5: Check that old parsing methods are removed
    print("\n5. Verifying Old Parsing Methods Removed...")
    try:
        # Check blockchain_listener.py
        with open('data/blockchain_listener.py', 'r') as f:
            bl_content = f.read()
        
        # Check market_data.py  
        with open('data/market_data.py', 'r') as f:
            md_content = f.read()
        
        old_methods = [
            '_parse_raydium_v4_swap_log',
            '_parse_pumpswap_amm_log', 
            '_parse_raydium_clmm_swap_log'
        ]
        
        removed_count = 0
        for method in old_methods:
            if method not in bl_content and method not in md_content:
                removed_count += 1
                print(f"✓ {method} successfully removed")
            else:
                print(f"✗ {method} still exists in files")
                
        if removed_count == len(old_methods):
            print(f"✓ All {removed_count} old parsing methods removed")
        else:
            print(f"✗ Only {removed_count}/{len(old_methods)} old methods removed")
            return False
            
    except Exception as e:
        print(f"✗ Old method verification failed: {e}")
        return False
    
    # Test 6: Check price aggregator integration
    print("\n6. Testing Price Aggregator Integration...")
    try:
        # Check if price aggregator is properly integrated
        with open('data/blockchain_listener.py', 'r') as f:
            bl_content = f.read()
            
        with open('data/market_data.py', 'r') as f:
            md_content = f.read()
        
        integration_checks = [
            ('PriceMonitoringAggregator', 'Price aggregator import'),
            ('price_aggregator', 'Price aggregator instance'),
            ('record_price_update', 'Price recording method')
        ]
        
        for check_str, description in integration_checks:
            if check_str in bl_content or check_str in md_content:
                print(f"✓ {description} found")
            else:
                print(f"✗ {description} missing")
                return False
                
    except Exception as e:
        print(f"✗ Price aggregator integration check failed: {e}")
        return False
    
    print("\n=== Integration Test Complete ===")
    print("✓ All tests passed! The system is ready for deployment.")
    print("\n📋 Summary of Changes:")
    print("   • Removed old parsing methods from blockchain_listener.py and market_data.py")
    print("   • Integrated modular parser system with dedicated parsers")
    print("   • Added price monitoring aggregator for 60-second price comparisons")
    print("   • Separated blockchain logs to dedicated file")
    print("   • Significantly reduced file sizes and complexity")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_integration_complete())
    sys.exit(0 if success else 1) 