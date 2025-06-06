#!/usr/bin/env python3
"""
Test script to verify parsing fixes for amount extraction.
Checks if the suspicious amount parsing issues are resolved.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock settings for testing
class MockSettings:
    def __init__(self):
        self.LOG_LEVEL = "INFO"

def test_raydium_v4_parsing():
    """Test Raydium V4 parser with mock logs"""
    # Import the parsing method directly to avoid Settings validation
    from data.market_data import MarketData
    
    # Create minimal MarketData instance for testing
    market_data = MarketData.__new__(MarketData)
    market_data.logger = print  # Use print as logger for testing
    
    # Mock logs that would previously cause issues
    mock_logs = [
        "Program 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8 invoke [1]",
        "Instruction: SwapBaseIn",
        "Transfer amount: 1000000",  # 1M tokens - reasonable
        "Transfer amount: 500000",   # 500K tokens - reasonable
        "Block height: 111111111111111111111111111111",  # Should NOT be parsed as amount
        "Timestamp: 1699999999999",  # Should NOT be parsed as amount
        "Program 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8 consumed 12345 of 200000 compute units",
        "Program 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8 success"
    ]
    
    result = market_data._parse_raydium_v4_swap_log(mock_logs)
    
    print("=== RAYDIUM V4 PARSER TEST ===")
    if result:
        print(f"✅ Parsed swap successfully")
        print(f"Amount In: {result.get('amount_in')}")
        print(f"Amount Out: {result.get('amount_out')}")
        print(f"Raw amounts: {result.get('raw_amounts', [])}")
        print(f"Confidence: {result.get('parsing_confidence')}")
        
        # Check for suspicious values
        amounts = [result.get('amount_in'), result.get('amount_out')] + result.get('raw_amounts', [])
        suspicious_amounts = [amt for amt in amounts if amt and amt > 1000000000000]  # 1T+
        
        if suspicious_amounts:
            print(f"🚨 SUSPICIOUS AMOUNTS FOUND: {suspicious_amounts}")
            return False
        else:
            print("✅ No suspicious amounts detected")
            return True
    else:
        print("❌ No swap detected")
        return False

def test_clmm_parsing():
    """Test CLMM parser with mock logs"""
    from data.market_data import MarketData
    
    # Create minimal MarketData instance for testing
    market_data = MarketData.__new__(MarketData)
    market_data.logger = print  # Use print as logger for testing
    
    mock_logs = [
        "Program CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK invoke [1]",
        "Instruction: swap",
        "Amount_a: 111111111111111111111111111111",  # This was the suspicious amount!
        "Amount_b: 141700",
        "Tick: -12345",
        "Program CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK success"
    ]
    
    result = market_data._parse_raydium_clmm_swap_log(mock_logs)
    
    print("\n=== RAYDIUM CLMM PARSER TEST ===")
    if result:
        print(f"✅ Parsed swap successfully")
        print(f"Amount In: {result.get('amount_in')}")
        print(f"Amount Out: {result.get('amount_out')}")
        print(f"Amount A: {result.get('amount_a')}")
        print(f"Amount B: {result.get('amount_b')}")
        print(f"Raw amounts: {result.get('raw_amounts', [])}")
        print(f"Confidence: {result.get('parsing_confidence')}")
        
        # Check for suspicious values
        amounts = [result.get('amount_in'), result.get('amount_out'), 
                  result.get('amount_a'), result.get('amount_b')] + result.get('raw_amounts', [])
        suspicious_amounts = [amt for amt in amounts if amt and amt > 1000000000000]  # 1T+
        
        if suspicious_amounts:
            print(f"🚨 SUSPICIOUS AMOUNTS FOUND: {suspicious_amounts}")
            return False
        else:
            print("✅ No suspicious amounts detected")
            return True
    else:
        print("❌ No swap detected")
        return False

def test_pumpswap_parsing():
    """Test PumpSwap parser"""
    from data.market_data import MarketData
    
    # Create minimal MarketData instance for testing
    market_data = MarketData.__new__(MarketData)
    market_data.logger = print  # Use print as logger for testing
    
    mock_logs = [
        "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA invoke [1]",
        "Instruction: buy",
        "Pump B: 36102659, S: 36320064",
        "🤑 Transaction successful",
        "Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA success"
    ]
    
    result = market_data._parse_pumpswap_amm_log(mock_logs)
    
    print("\n=== PUMPSWAP PARSER TEST ===")
    if result:
        print(f"✅ Parsed event successfully")
        print(f"Event type: {result.get('event_type')}")
        print(f"Instruction: {result.get('instruction_type')}")
        print(f"Found swap: {result.get('found_swap')}")
        print(f"Buy amount: {result.get('buy_amount')}")
        print(f"Sell amount: {result.get('sell_amount')}")
        return True
    else:
        print("❌ No event detected")
        return False

if __name__ == "__main__":
    print("🧪 Testing Parser Fixes\n")
    
    results = []
    results.append(test_raydium_v4_parsing())
    results.append(test_clmm_parsing())
    results.append(test_pumpswap_parsing())
    
    print(f"\n📊 TEST RESULTS: {sum(results)}/{len(results)} passed")
    
    if all(results):
        print("✅ ALL PARSERS FIXED - No suspicious amounts detected!")
    else:
        print("❌ SOME PARSERS STILL HAVE ISSUES")
        
    print("\n🔍 PARSER STATUS ANALYSIS:")
    print("✅ PUMPSWAP: Working (from your logs)")
    print("❓ RAYDIUM_V4: Testing needed")
    print("❓ RAYDIUM_CLMM: Testing needed")  
    print("❓ PUMPFUN: Testing needed") 