#!/usr/bin/env python3
"""
Minimal test for Phase 1: Enhanced PriceMonitor core functionality
Tests the key enhancements without requiring full environment setup
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
    
    # Core PriceMonitor settings
    mock_settings.MAX_PRICE_HISTORY = 100
    mock_settings.PRICEMONITOR_INTERVAL = 30
    mock_settings.SOL_PRICE_CACHE_DURATION = 300
    mock_settings.HTTP_TIMEOUT = 30
    mock_settings.SOL_MINT = "So11111111111111111111111111111111111111112"
    mock_settings.SOL_PRICE_UPDATE_INTERVAL = 30
    
    # API endpoints (can be mock)
    mock_settings.SOL_PRICE_API = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
    mock_settings.SOL_PRICE_API_BACKUP = "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"
    
    return mock_settings

def create_mock_dex_api():
    """Create a mock DexScreenerAPI"""
    mock_dex = AsyncMock()
    mock_dex.initialize = AsyncMock(return_value=True)
    mock_dex.close = AsyncMock()
    mock_dex.get_token_details = AsyncMock(return_value={
        "pairs": [{
            "baseToken": {"address": "test_mint"},
            "priceUsd": "100.0"
        }]
    })
    return mock_dex

def create_mock_http_client():
    """Create a mock HTTP client"""
    mock_http = AsyncMock()
    mock_http.aclose = AsyncMock()
    mock_http.get = AsyncMock()
    
    # Mock SOL price response
    mock_response = Mock()
    mock_response.json.return_value = {"solana": {"usd": 150.0}}
    mock_response.raise_for_status = Mock()
    mock_http.get.return_value = mock_response
    
    return mock_http

async def test_phase1_simple():
    """Test Phase 1: Enhanced PriceMonitor core functionality"""
    print("🚀 Testing Phase 1: Enhanced PriceMonitor (Simple Test)")
    print("=" * 60)
    
    try:
        # Import PriceMonitor directly
        from data.price_monitor import PriceMonitor
        
        # Create mock dependencies
        print("1. Creating mock dependencies...")
        mock_settings = create_mock_settings()
        mock_dex_api = create_mock_dex_api()
        mock_http_client = create_mock_http_client()
        print("✅ Mock dependencies created")
        
        # Test PriceMonitor initialization
        print("2. Testing PriceMonitor initialization...")
        pm = PriceMonitor(mock_settings, mock_dex_api, mock_http_client)
        
        # Test that parsers are created
        assert hasattr(pm, 'jupiter_parser'), "Missing jupiter_parser"
        assert hasattr(pm, 'raydium_parser'), "Missing raydium_parser"
        print("✅ PriceMonitor created with parsers")
        
        # Test smart routing logic
        print("3. Testing smart API routing...")
        route1 = pm._determine_api_route('test_mint_1')
        route2 = pm._determine_api_route('test_mint_2', 'raydium_v4')
        route3 = pm._determine_api_route('test_mint_3', 'pumpswap')
        route4 = pm._determine_api_route('test_mint_4', 'raydium_clmm')
        
        print(f"   Default routing: {route1}")
        print(f"   Raydium V4 routing: {route2}")  
        print(f"   PumpSwap routing: {route3}")
        print(f"   Raydium CLMM routing: {route4}")
        
        # Verify routing logic
        assert route2 == 'raydium', f"Expected raydium for raydium_v4, got {route2}"
        assert route4 == 'raydium', f"Expected raydium for raydium_clmm, got {route4}"
        assert route3 == 'jupiter', f"Expected jupiter for pumpswap, got {route3}"
        assert route1 == 'jupiter', f"Expected jupiter for default, got {route1}"
        print("✅ Smart routing working correctly")
        
        # Test new SOL-based method exists
        print("4. Testing get_current_price_sol method...")
        assert hasattr(pm, 'get_current_price_sol'), "Missing get_current_price_sol method"
        
        # Test method signature
        import inspect
        sig = inspect.signature(pm.get_current_price_sol)
        params = list(sig.parameters.keys())
        assert 'mint' in params, "get_current_price_sol missing mint parameter"
        assert 'max_age_seconds' in params, "get_current_price_sol missing max_age_seconds parameter"
        print("✅ get_current_price_sol method exists with correct signature")
        
        # Test pricing statistics
        print("5. Testing pricing statistics...")
        assert hasattr(pm, '_pricing_stats'), "Missing pricing statistics"
        expected_keys = ['jupiter_requests', 'raydium_requests', 'fallback_requests', 
                        'successful_updates', 'failed_updates', 'last_update_time']
        for key in expected_keys:
            assert key in pm._pricing_stats, f"Missing pricing stat: {key}"
        print("✅ Pricing statistics structure correct")
        
        # Test token routing cache
        print("6. Testing token routing cache...")
        assert hasattr(pm, '_token_dex_routing'), "Missing token routing cache"
        
        # Test that routing is cached
        pm._determine_api_route('cache_test', 'raydium_v4')
        assert 'cache_test' in pm._token_dex_routing, "Routing not cached"
        assert pm._token_dex_routing['cache_test'] == 'raydium_v4', "Incorrect routing cached"
        
        # Test cached routing is used
        route_cached = pm._determine_api_route('cache_test')
        assert route_cached == 'raydium', "Cached routing not used"
        print("✅ Token routing cache working")
        
        # Test data structures
        print("7. Testing data structures...")
        required_attrs = [
            '_token_prices', '_token_prices_usd', '_token_data_cache',
            'price_history', 'tokens_being_monitored', 'active_tokens_details'
        ]
        for attr in required_attrs:
            assert hasattr(pm, attr), f"Missing required attribute: {attr}"
        print("✅ All required data structures present")
        
        print("\n🎉 PHASE 1 CORE LOGIC SUCCESSFUL!")
        print("✅ Enhanced PriceMonitor structure complete")
        print("✅ Smart API routing implemented")
        print("✅ get_current_price_sol() method available") 
        print("✅ Token routing cache functional")
        print("✅ Pricing statistics tracking ready")
        print("✅ All data structures initialized")
        
        return True
        
    except Exception as e:
        print(f"\n❌ PHASE 1 TEST FAILED: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_phase1_simple())
    if success:
        print("\n🚀 Phase 1 core logic verified! Ready for Phase 2: SOL-Based Trading Integration")
        print("\n📋 NEXT STEPS:")
        print("  1. Update MarketData to use enhanced PriceMonitor")
        print("  2. Modify trading components to use get_current_price_sol()")
        print("  3. Update paper trading to track SOL P&L")
        print("  4. Test end-to-end SOL-based trading flow")
    else:
        print("\n⚠️ Fix Phase 1 core logic before proceeding")
        sys.exit(1) 