#!/usr/bin/env python3
"""
Simple test to verify amount parsing regex fixes.
"""

import re

def test_old_vs_new_patterns():
    """Test old problematic patterns vs new fixed patterns"""
    
    # Sample log that contained the suspicious amount
    test_log = "Amount_a: 111111111111111111111111111111, Amount_b: 141700, Block: 999999999, Timestamp: 1699999999999"
    
    print("🧪 TESTING AMOUNT PARSING PATTERNS\n")
    
    # OLD PROBLEMATIC PATTERNS
    old_patterns = [
        r'(\d{6,})',  # This was catching everything!
        r'(\d{4,})'   # This was also too broad
    ]
    
    print("=== OLD PROBLEMATIC PATTERNS ===")
    for pattern in old_patterns:
        matches = re.findall(pattern, test_log)
        print(f"Pattern: {pattern}")
        print(f"Matches: {matches}")
        suspicious = [m for m in matches if len(m) > 15]  # Very long numbers
        if suspicious:
            print(f"🚨 SUSPICIOUS: {suspicious}")
        print()
    
    # NEW FIXED PATTERNS
    new_patterns = [
        r'transfer[_\s]*amount[:\s]+(\d+)',
        r'swap[_\s]*amount[:\s]+(\d+)',
        r'in[_\s]*amount[:\s]+(\d+)', 
        r'out[_\s]*amount[:\s]+(\d+)',
        r'fee[_\s]*amount[:\s]+(\d+)'
        # REMOVED: r'amount[_\w]*[:\s]+(\d+)' - too broad, matches Amount_a
    ]
    
    print("=== NEW FIXED PATTERNS ===")
    all_amounts = []
    for pattern in new_patterns:
        matches = re.findall(pattern, test_log, re.IGNORECASE)
        print(f"Pattern: {pattern}")
        print(f"Matches: {matches}")
        all_amounts.extend([int(m) for m in matches])
    
    # Apply amount filtering
    filtered_amounts = [amt for amt in all_amounts if 100 <= amt <= 1000000000000]
    suspicious_amounts = [amt for amt in all_amounts if amt > 1000000000000]
    
    print(f"\n📊 RESULTS:")
    print(f"All extracted amounts: {all_amounts}")
    print(f"Filtered realistic amounts: {filtered_amounts}")
    print(f"Suspicious amounts (>1T): {suspicious_amounts}")
    
    if suspicious_amounts:
        print("❌ STILL EXTRACTING SUSPICIOUS AMOUNTS!")
        return False
    else:
        print("✅ NO SUSPICIOUS AMOUNTS - PATTERNS FIXED!")
        return True

def test_realistic_swap_log():
    """Test with a realistic swap log"""
    
    realistic_log = [
        "Program 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8 invoke [1]",
        "Instruction: SwapBaseIn",
        "Transfer amount: 1000000",  # 1M tokens
        "Transfer amount: 950000",   # 950K tokens  
        "Fee amount: 2500",          # 2.5K fee
        "Block 271234567",           # Block number - should be ignored
        "Timestamp: 1704067200",     # Timestamp - should be ignored
        "Program success"
    ]
    
    print("\n=== REALISTIC SWAP LOG TEST ===")
    
    # Use the new patterns
    new_patterns = [
        r'transfer[_\s]*amount[:\s]+(\d+)',
        r'fee[_\s]*amount[:\s]+(\d+)',
        r'amount[_\w]*[:\s]+(\d+)'
    ]
    
    all_amounts = []
    for log_line in realistic_log:
        for pattern in new_patterns:
            matches = re.findall(pattern, log_line, re.IGNORECASE)
            all_amounts.extend([int(m) for m in matches])
    
    # Remove duplicates and filter
    unique_amounts = list(set(all_amounts))
    filtered_amounts = [amt for amt in unique_amounts if 1000 <= amt <= 1000000000000]
    
    print(f"Log lines: {len(realistic_log)}")
    print(f"All extracted: {sorted(unique_amounts)}")
    print(f"Filtered amounts: {sorted(filtered_amounts)}")
    
    expected_amounts = [1000000, 950000, 2500]  # What we should extract
    
    if set(filtered_amounts) >= set(expected_amounts):
        print("✅ CORRECTLY EXTRACTED SWAP AMOUNTS")
        return True
    else:
        print("❌ MISSED SOME EXPECTED AMOUNTS")
        return False

if __name__ == "__main__":
    print("🔍 TESTING AMOUNT PARSING FIXES\n")
    
    test1 = test_old_vs_new_patterns()
    test2 = test_realistic_swap_log()
    
    print(f"\n📊 FINAL RESULTS: {sum([test1, test2])}/2 tests passed")
    
    if test1 and test2:
        print("✅ AMOUNT PARSING FIXES SUCCESSFUL!")
        print("No more suspicious amounts like 111111111111111111111111111111")
    else:
        print("❌ AMOUNT PARSING STILL HAS ISSUES") 