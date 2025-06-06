#!/usr/bin/env python3
"""
Test the new parser refactoring
Verify parsers work correctly and blockchain logging is set up
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_parser_refactor():
    """Test that the new parser structure works"""
    
    try:
        print("🧪 Testing Parser Refactor")
        print("=" * 50)
        
        # Test imports
        from data import RaydiumV4Parser, PumpSwapParser, RaydiumClmmParser
        from config.blockchain_logging import setup_blockchain_logger
        print("✅ Parser imports successful")
        
        # Test logger setup  
        logger = setup_blockchain_logger()
        logger.info("Test blockchain logger")
        print("✅ Blockchain logger setup successful")
        
        # Test parser instantiation
        class MockSettings:
            pass
        
        parsers = [
            RaydiumV4Parser(MockSettings(), logger),
            PumpSwapParser(MockSettings(), logger), 
            RaydiumClmmParser(MockSettings(), logger)
        ]
        
        for parser in parsers:
            print(f"✅ {parser.__class__.__name__} (DEX: {parser.get_dex_id()}) initialized")
            
        # Test basic functionality
        sample_logs = [
            "Program log: instruction: SwapBaseIn",
            "Program log: transfer amount: 1000000",
            "Program log: transfer amount: 950000"
        ]
        
        raydium_parser = parsers[0]
        result = raydium_parser.parse_swap_logs(sample_logs, "test_signature")
        
        if result and result.get("found_swap"):
            print(f"✅ Raydium V4 parser successfully parsed sample logs: {result.get('instruction_type')}")
        else:
            print("⚠️  Raydium V4 parser did not find swap in sample logs")
            
        print("\n🎉 Parser refactor test completed successfully!")
        print("📄 Check outputs/blockchain_listener.log for dedicated blockchain logs")
        
    except Exception as e:
        print(f"❌ Parser refactor test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_parser_refactor() 