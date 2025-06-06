#!/usr/bin/env python3
"""
Debug script to test FIXED CLMM parsing logic.
"""

import re

def debug_clmm_parsing():
    """Debug CLMM parsing with updated patterns"""
    
    print("🔍 DEBUG: FIXED CLMM LOG PARSING\n")
    
    # Sample logs that were causing issues
    sample_logs = [
        "Program CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK invoke [1]",
        "Instruction: Swap",
        "Log: amount_a: 111111111111111111111111111111",  # Suspicious huge amount
        "Log: amount_b: 141700", 
        "Log: tick_current: -276324",  # This was missing before
        "Log: sqrt_price_x64: 79228162514264337593543950336",  # This was missing before
        "Log: liquidity: 1000000000",
        "Log: fee_amount: 500",
        "Transfer: 1000000 tokens",
        "Transfer: 500000 tokens"
    ]
    
    print("📋 SAMPLE LOGS:")
    for i, log in enumerate(sample_logs, 1):
        print(f"{i:2d}. {log}")
    
    print("\n🧪 TESTING NEW FIXED PATTERNS:")
    
    # Test updated patterns
    patterns_to_test = {
        "tick_current": r'tick[_\s]*current[:\s]+(-?\d+)',
        "tick_fallback": r'tick[:\s]+(-?\d+)',
        "sqrt_price_x64": r'sqrt[_\s]*price[_\s]*x64[:\s]+(\d+)',
        "sqrt_price": r'sqrt[_\s]*price[:\s]+(\d+)',
        "amount_a": r'amount[_\s]*a[:\s]+(\d+)',
        "amount_b": r'amount[_\s]*b[:\s]+(\d+)',
        "liquidity": r'liquidity[:\s]+(\d+)'
    }
    
    for pattern_name, pattern in patterns_to_test.items():
        print(f"\n--- {pattern_name.upper()} ---")
        
        for log in sample_logs:
            matches = re.findall(pattern, log, re.IGNORECASE)
            if matches:
                print(f"  ✅ {log}")
                print(f"     Found: {matches}")
    
    print("\n🔧 SIMULATING FIXED PARSER LOGIC:")
    
    swap_info = {
        "event_type": "swap",
        "found_swap": False,
        "amount_in": None,
        "amount_out": None,
        "amount_a": None,
        "amount_b": None,
        "tick_current": None,
        "sqrt_price": None,
        "liquidity": None,
        "parsing_confidence": 0.0
    }
    
    for log in sample_logs:
        log_lower = log.lower()
        
        # Swap detection
        if "instruction: swap" in log_lower:
            swap_info["found_swap"] = True
            swap_info["parsing_confidence"] += 0.4
            print(f"✅ Found swap instruction")
        
        # Amount_a extraction with filtering
        amount_a_matches = re.findall(r'amount[_\s]*a[:\s]+(\d+)', log_lower)
        if amount_a_matches:
            try:
                amount_a_raw = int(amount_a_matches[0])
                if amount_a_raw > 1000000000000000000000000:  # 1e24
                    print(f"⚠️  Filtering out suspicious amount_a: {amount_a_raw} (too large)")
                else:
                    swap_info["amount_a"] = amount_a_raw
                    swap_info["parsing_confidence"] += 0.1
                    print(f"✅ Found valid amount_a: {swap_info['amount_a']}")
            except ValueError:
                print(f"❌ Failed to parse amount_a")
        
        # Amount_b extraction  
        amount_b_matches = re.findall(r'amount[_\s]*b[:\s]+(\d+)', log_lower)
        if amount_b_matches:
            try:
                swap_info["amount_b"] = int(amount_b_matches[0])
                swap_info["parsing_confidence"] += 0.1
                print(f"✅ Found amount_b: {swap_info['amount_b']}")
            except ValueError:
                print(f"❌ Failed to parse amount_b")
        
        # Tick extraction (updated pattern)
        tick_matches = re.findall(r'tick[_\s]*current[:\s]+(-?\d+)', log_lower)
        if not tick_matches:
            tick_matches = re.findall(r'tick[:\s]+(-?\d+)', log_lower)
        if tick_matches:
            try:
                swap_info["tick_current"] = int(tick_matches[0])
                swap_info["parsing_confidence"] += 0.15
                print(f"✅ Found tick: {swap_info['tick_current']}")
            except ValueError:
                print(f"❌ Failed to parse tick")
        
        # Sqrt price extraction (updated pattern + filtering)
        sqrt_price_matches = re.findall(r'sqrt[_\s]*price[_\s]*x64[:\s]+(\d+)', log_lower)
        if not sqrt_price_matches:
            sqrt_price_matches = re.findall(r'sqrt[_\s]*price[:\s]+(\d+)', log_lower)
        if sqrt_price_matches:
            try:
                sqrt_price_raw = int(sqrt_price_matches[0])
                # FILTER OUT SYSTEM CONSTANTS - 2^96 and other unrealistic values
                if sqrt_price_raw >= 2**95:  # Filter values >= 2^95 (half of 2^96)
                    print(f"⚠️  Filtering out suspicious sqrt_price: {sqrt_price_raw} (system constant like 2^96)")
                else:
                    swap_info["sqrt_price"] = sqrt_price_raw
                    swap_info["parsing_confidence"] += 0.15
                    print(f"✅ Found valid sqrt_price: {swap_info['sqrt_price']}")
            except ValueError:
                print(f"❌ Failed to parse sqrt_price")
        
        # Liquidity extraction
        liquidity_matches = re.findall(r'liquidity[:\s]+(\d+)', log_lower)
        if liquidity_matches:
            try:
                swap_info["liquidity"] = int(liquidity_matches[0])
                swap_info["parsing_confidence"] += 0.1
                print(f"✅ Found liquidity: {swap_info['liquidity']}")
            except ValueError:
                print(f"❌ Failed to parse liquidity")
    
    # NEW FIXED LOGIC: Priority-based amount assignment
    print(f"\n🔄 APPLYING FIXED AMOUNT LOGIC:")
    
    # Simulate transfer amounts that would be found
    transfers_detected = [1000000, 500000]  # From the transfer logs
    
    # Priority 1: Use amount_a and amount_b if both available and reasonable
    if swap_info["amount_a"] is not None and swap_info["amount_b"] is not None:
        swap_info["amount_in"] = swap_info["amount_a"]
        swap_info["amount_out"] = swap_info["amount_b"]
        swap_info["parsing_confidence"] += 0.3
        print(f"✅ Using amount_a/amount_b: in={swap_info['amount_in']}, out={swap_info['amount_out']}")
        
    # Priority 2: Use amount_b as out, try to find amount_in from other sources
    elif swap_info["amount_b"] is not None:
        swap_info["amount_out"] = swap_info["amount_b"]
        if len(transfers_detected) >= 1:
            swap_info["amount_in"] = max(transfers_detected)
            swap_info["parsing_confidence"] += 0.2
            print(f"✅ Using amount_b + transfer fallback: in={swap_info['amount_in']}, out={swap_info['amount_out']}")
        else:
            print(f"⚠️  Only amount_out available: {swap_info['amount_out']}")
    else:
        print(f"❌ amount_a and amount_b both missing")
    
    print(f"\n📊 FIXED PARSER RESULT:")
    for key, value in swap_info.items():
        status = "✅" if value is not None else "❌"
        print(f"  {status} {key}: {value}")
    
    print(f"\n🎯 FINAL ANALYSIS:")
    none_fields = [k for k, v in swap_info.items() if v is None and k in ['amount_in', 'amount_out', 'amount_a', 'amount_b', 'tick_current', 'sqrt_price']]
    if none_fields:
        print(f"  ❌ Still None: {none_fields}")
    else:
        print(f"  ✅ ALL CRITICAL FIELDS PARSED SUCCESSFULLY!")
    
    print(f"  📈 Parsing confidence: {swap_info['parsing_confidence']:.1f}")
    
    return swap_info

if __name__ == "__main__":
    debug_clmm_parsing() 