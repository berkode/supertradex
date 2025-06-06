#!/usr/bin/env python3
"""
Quick test script to verify the blockchain listener fix
"""

import asyncio
import logging
from test_token_monitoring import load_environment, monitor_token_realtime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test token
TEST_TOKEN = {
    'mint': '7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij',
    'symbol': 'JOJO',
    'name': 'JOJO',
    'dex_id': 'raydium_v4',
    'pair_address': 'GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL'
}

async def quick_test():
    """Quick 5-second test"""
    print("🧪 Quick Blockchain Listener Test")
    print("=" * 40)
    
    try:
        # Run for just 5 seconds
        await monitor_token_realtime(TEST_TOKEN, duration_seconds=5)
        print("✅ Test completed successfully!")
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(quick_test())
    exit(0 if success else 1) 