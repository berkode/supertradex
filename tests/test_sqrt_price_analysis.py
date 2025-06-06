#!/usr/bin/env python3
"""
Analyze the suspicious sqrt_price_x64 value to prove it's invalid.
"""

def analyze_sqrt_price():
    print("🔍 ANALYZING SUSPICIOUS SQRT_PRICE_X64 VALUE\n")
    
    # The extracted value
    sqrt_price_x64 = 79228162514264337593543950336
    
    print(f"Extracted sqrt_price_x64: {sqrt_price_x64}")
    print(f"In scientific notation: {sqrt_price_x64:.2e}")
    
    # Check if it's a power of 2
    import math
    log2_value = math.log2(sqrt_price_x64)
    print(f"Log2 of value: {log2_value}")
    
    # Check common powers of 2
    powers_of_2 = {
        64: 2**64,
        96: 2**96,
        128: 2**128,
        256: 2**256
    }
    
    print(f"\n📊 COMPARING TO POWERS OF 2:")
    for power, value in powers_of_2.items():
        if value == sqrt_price_x64:
            print(f"  ✅ EXACTLY equals 2^{power}")
        else:
            print(f"  ❌ 2^{power} = {value}")
    
    print(f"\n🧮 WHAT THIS WOULD MEAN AS A PRICE:")
    
    # In CLMM: sqrt_price_x64 = sqrt(price) * 2^64
    # So: sqrt(price) = sqrt_price_x64 / 2^64
    
    if sqrt_price_x64 == 2**96:
        print(f"  If sqrt_price_x64 = 2^96, then:")
        print(f"  sqrt(price) = 2^96 / 2^64 = 2^32 = {2**32:,}")
        print(f"  price = (2^32)^2 = 2^64 = {2**64:,}")
        print(f"  That's ${2**64:,.0f} per token! 🤯")
        print(f"  For comparison:")
        print(f"    - Bitcoin: ~$43,000")
        print(f"    - This 'price': ~$18,446,744,073,709,551,616")
        print(f"    - That's 429 TRILLION times more expensive than Bitcoin!")
    
    print(f"\n💡 CONCLUSION:")
    print(f"  🚨 This is clearly NOT a real price!")
    print(f"  🔧 This is likely:")
    print(f"     - A default/max value constant (2^96)")
    print(f"     - Pool initialization state")
    print(f"     - Overflow/corrupted data")
    print(f"     - System placeholder value")
    
    print(f"\n✅ RECOMMENDATION:")
    print(f"  Filter out sqrt_price values >= 2^95 as invalid")
    print(f"  Similar to how we filtered amount_a >= 1e24")

if __name__ == "__main__":
    analyze_sqrt_price() 