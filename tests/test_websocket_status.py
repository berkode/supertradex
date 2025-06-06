#!/usr/bin/env python3
"""
Test WebSocket connections and subscription status for all DEX protocols.
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.settings import Settings
from data.market_data import MarketData

async def test_websocket_connections():
    """Test WebSocket connections and subscription status"""
    
    print("🔌 TESTING WEBSOCKET CONNECTIONS\n")
    
    try:
        # Initialize with proper settings
        settings = Settings()
        market_data = MarketData(settings)
        
        # Initialize the system
        await market_data.initialize()
        
        # Check blockchain listener status
        if market_data.blockchain_listener:
            print("✅ Blockchain Listener initialized")
            
            # Get listener metrics
            metrics = await market_data.get_blockchain_listener_metrics()
            
            print("\n📊 WEBSOCKET STATUS:")
            print(f"Active WebSockets: {metrics.get('active_websockets', 0)}")
            print(f"Total Events Processed: {metrics.get('total_events_processed', 0)}")
            print(f"Events by DEX: {metrics.get('events_by_dex', {})}")
            print(f"WebSocket Health: {metrics.get('websocket_health', {})}")
            
            # Check specific program subscriptions
            print("\n🔍 PROGRAM SUBSCRIPTIONS:")
            
            # Check each DEX program
            dex_programs = {
                'pumpfun': settings.PUMPFUN_PROGRAM_ID,
                'pumpswap': settings.PUMPSWAP_PROGRAM_ID, 
                'raydium_v4': settings.RAYDIUM_V4_PROGRAM_ID,
                'raydium_clmm': settings.RAYDIUM_CLMM_PROGRAM_ID
            }
            
            for dex_name, program_id in dex_programs.items():
                print(f"{dex_name.upper()}: {program_id}")
                
                # Check if WebSocket is active for this program
                health = metrics.get('websocket_health', {})
                ws_status = health.get(program_id, {})
                
                if ws_status:
                    print(f"  Status: {ws_status.get('status', 'unknown')}")
                    print(f"  Connected: {ws_status.get('connected', False)}")
                    print(f"  Last Event: {ws_status.get('last_event_time', 'never')}")
                else:
                    print(f"  Status: ❌ No WebSocket found")
                    
            return True
            
        else:
            print("❌ Blockchain Listener not initialized")
            return False
            
    except Exception as e:
        print(f"❌ Error testing WebSocket connections: {e}")
        return False
    finally:
        if 'market_data' in locals():
            await market_data.close()

async def test_subscription_setup():
    """Test setting up subscriptions for a test token"""
    
    print("\n🧪 TESTING SUBSCRIPTION SETUP\n")
    
    try:
        settings = Settings()
        market_data = MarketData(settings)
        await market_data.initialize()
        
        # Test token from your logs
        test_mint = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
        
        print(f"Testing subscription setup for: {test_mint}")
        
        # Try to start monitoring
        print("🔄 Starting monitoring...")
        success = await market_data.add_token_for_monitoring(
            mint=test_mint,
            dex_id='pumpswap'
        )
        
        if success:
            print("✅ Monitoring setup successful")
            
            # Check actively streamed mints
            active_mints = market_data.actively_streamed_mints
            print(f"Active streamed mints: {len(active_mints)}")
            for mint in active_mints:
                print(f"  - {mint}")
                
            # Wait a moment for events
            print("\n⏳ Waiting for events (5 seconds)...")
            await asyncio.sleep(5)
            
            # Check for any new events
            metrics = await market_data.get_blockchain_listener_metrics()
            events_by_dex = metrics.get('events_by_dex', {})
            
            print(f"\n📈 Events received:")
            for dex, count in events_by_dex.items():
                print(f"  {dex}: {count} events")
                
        else:
            print("❌ Monitoring setup failed")
            
        return success
        
    except Exception as e:
        print(f"❌ Error testing subscription setup: {e}")
        return False
    finally:
        if 'market_data' in locals():
            await market_data.close()

async def main():
    """Main test function"""
    
    print("🚀 WEBSOCKET & SUBSCRIPTION DIAGNOSTIC\n")
    
    # Test 1: WebSocket Connections
    ws_test = await test_websocket_connections()
    
    # Test 2: Subscription Setup
    sub_test = await test_subscription_setup()
    
    print(f"\n📊 TEST RESULTS:")
    print(f"WebSocket Connections: {'✅' if ws_test else '❌'}")
    print(f"Subscription Setup: {'✅' if sub_test else '❌'}")
    
    if ws_test and sub_test:
        print("\n✅ ALL SYSTEMS OPERATIONAL")
        print("Ready for live trading with all DEX protocols!")
    else:
        print("\n❌ ISSUES DETECTED")
        print("Need to fix WebSocket/subscription problems before trading")

if __name__ == "__main__":
    asyncio.run(main()) 