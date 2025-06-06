#!/usr/bin/env python3
"""
Test Hybrid Monitoring System
Demonstrates the hybrid monitoring approach with different priority levels:
- BONK: HIGH priority (direct account subscriptions)
- Another popular token: MEDIUM priority (program logs)
- Low activity token: LOW priority (API polling)
"""

import asyncio
import sys
import os
from typing import Dict, Any

# Add the project directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.settings import Settings
from data.market_data import MarketData
from data.token_database import TokenDatabase
from data.blockchain_listener import BlockchainListener
from data.hybrid_monitoring_manager import HybridMonitoringManager, TokenPriority
from utils.logger import get_logger

logger = get_logger(__name__)

# Known token configurations for testing
TEST_TOKENS = {
    "BONK": {
        "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "symbol": "BONK",
        "priority": TokenPriority.HIGH,
        "pool_address": "8BnEgHoWFysVcuFFX7QztDmzuH8r5ZFvyP3sYwn1XTh6",  # Raydium V4 BONK/SOL
        "dex_id": "raydium_v4"
    },
    "SAPHI": {
        "mint": "8kb6YDFfr5kFP6nHGp1Bhm4hKtdUmkLnX9TRVKo5wPEE",
        "symbol": "SAPHI",
        "priority": TokenPriority.MEDIUM,
        "dex_id": "pumpswap"
    },
    "EXAMPLE_LOW": {
        "mint": "So11111111111111111111111111111111111111112",  # Wrapped SOL as example
        "symbol": "WSOL",
        "priority": TokenPriority.LOW
    }
}

class HybridMonitoringTester:
    def __init__(self):
        self.settings = Settings()
        self.token_db = TokenDatabase()
        self.market_data = None
        self.blockchain_listener = None
        self.hybrid_manager = None
        
        self.test_metrics = {
            "high_priority_updates": 0,
            "medium_priority_updates": 0,
            "low_priority_updates": 0,
            "total_events": 0,
            "start_time": None
        }

    async def initialize(self):
        """Initialize all components."""
        try:
            logger.info("🚀 Initializing Hybrid Monitoring Test System...")
            
            # Initialize components
            self.market_data = MarketData(self.settings, self.token_db)
            await self.market_data.initialize()
            
            self.blockchain_listener = BlockchainListener(self.settings)
            await self.blockchain_listener.initialize()
            
            # Initialize hybrid monitoring manager
            self.hybrid_manager = HybridMonitoringManager(
                self.settings,
                self.blockchain_listener,
                self.market_data,
                self.token_db,
                logger
            )
            
            # Set up blockchain event callback
            self.blockchain_listener.set_callback(self._handle_blockchain_event)
            
            logger.info("✅ All components initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing components: {e}", exc_info=True)
            return False

    async def _handle_blockchain_event(self, event_data: Dict[str, Any]):
        """Handle blockchain events and route to hybrid manager."""
        try:
            self.test_metrics["total_events"] += 1
            
            # Route to hybrid manager
            await self.hybrid_manager.handle_blockchain_event(event_data)
            
            # Track updates by priority level
            if event_data.get("type") == "account_update":
                self.test_metrics["high_priority_updates"] += 1
            elif event_data.get("type") == "blockchain_event":
                self.test_metrics["medium_priority_updates"] += 1
                
        except Exception as e:
            logger.error(f"Error handling blockchain event: {e}")

    async def setup_monitoring_tokens(self):
        """Set up different tokens with different priority levels."""
        try:
            logger.info("🎯 Setting up tokens with different priority levels...")
            
            # Add HIGH priority token (BONK with account subscription)
            bonk_config = TEST_TOKENS["BONK"]
            success = await self.hybrid_manager.add_high_priority_token(
                bonk_config["mint"],
                bonk_config["symbol"],
                bonk_config["pool_address"],
                bonk_config["dex_id"]
            )
            
            if success:
                logger.info(f"✅ BONK added as HIGH priority with account subscription")
            else:
                logger.error("❌ Failed to add BONK as high priority")
                return False
            
            # Add MEDIUM priority token (SAPHI with program logs only)
            saphi_config = TEST_TOKENS["SAPHI"]
            success = await self.hybrid_manager.add_medium_priority_token(
                saphi_config["mint"],
                saphi_config["symbol"],
                saphi_config["dex_id"]
            )
            
            if success:
                logger.info(f"✅ SAPHI added as MEDIUM priority with program logs")
            else:
                logger.warning("⚠️ Failed to add SAPHI as medium priority")
            
            # Add LOW priority token (WSOL with API polling only)
            wsol_config = TEST_TOKENS["EXAMPLE_LOW"]
            success = await self.hybrid_manager.add_low_priority_token(
                wsol_config["mint"],
                wsol_config["symbol"]
            )
            
            if success:
                logger.info(f"✅ WSOL added as LOW priority with API polling")
            else:
                logger.warning("⚠️ Failed to add WSOL as low priority")
            
            logger.info("🎯 Hybrid monitoring setup complete!")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up monitoring tokens: {e}", exc_info=True)
            return False

    async def run_monitoring_test(self, duration_minutes: int = 3):
        """Run the hybrid monitoring test for specified duration."""
        try:
            import time
            
            logger.info(f"🏃 Starting {duration_minutes}-minute hybrid monitoring test...")
            self.test_metrics["start_time"] = time.time()
            
            # Start blockchain listener
            blockchain_task = asyncio.create_task(self.blockchain_listener.run_forever())
            
            # Start periodic status reports
            status_task = asyncio.create_task(self._periodic_status_reports())
            
            # Wait for test duration
            await asyncio.sleep(duration_minutes * 60)
            
            # Stop tasks
            self.blockchain_listener._stop_event.set()
            status_task.cancel()
            
            try:
                await blockchain_task
            except asyncio.CancelledError:
                pass
                
            try:
                await status_task
            except asyncio.CancelledError:
                pass
            
            logger.info(f"✅ {duration_minutes}-minute hybrid monitoring test completed")
            
        except Exception as e:
            logger.error(f"Error running monitoring test: {e}", exc_info=True)

    async def _periodic_status_reports(self):
        """Generate periodic status reports during testing."""
        try:
            report_count = 0
            while True:
                await asyncio.sleep(30)  # Report every 30 seconds
                report_count += 1
                
                logger.info(f"📊 STATUS REPORT #{report_count}")
                await self.hybrid_manager.print_status_report()
                
                # Print test metrics
                logger.info("🧪 TEST METRICS:")
                logger.info(f"   Total Blockchain Events: {self.test_metrics['total_events']}")
                logger.info(f"   High Priority Updates: {self.test_metrics['high_priority_updates']}")
                logger.info(f"   Medium Priority Updates: {self.test_metrics['medium_priority_updates']}")
                logger.info(f"   Low Priority Updates: {self.test_metrics['low_priority_updates']}")
                
        except asyncio.CancelledError:
            logger.info("Status reporting cancelled")

    async def cleanup(self):
        """Clean up all resources."""
        try:
            logger.info("🧹 Cleaning up resources...")
            
            if self.hybrid_manager:
                await self.hybrid_manager.close()
            
            if self.blockchain_listener:
                await self.blockchain_listener.close()
            
            if self.market_data:
                await self.market_data.close()
            
            logger.info("✅ Cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

async def main():
    """Main test function."""
    tester = HybridMonitoringTester()
    
    try:
        logger.info("🔬 HYBRID MONITORING SYSTEM TEST")
        logger.info("=" * 50)
        logger.info("This test demonstrates:")
        logger.info("🔥 HIGH PRIORITY: BONK with direct account subscriptions")
        logger.info("📡 MEDIUM PRIORITY: SAPHI with program logs only")
        logger.info("⏱️ LOW PRIORITY: WSOL with API polling only")
        logger.info("=" * 50)
        
        # Initialize system
        if not await tester.initialize():
            logger.error("❌ Failed to initialize system")
            return
        
        # Set up monitoring tokens
        if not await tester.setup_monitoring_tokens():
            logger.error("❌ Failed to set up monitoring tokens")
            return
        
        # Run the test
        await tester.run_monitoring_test(duration_minutes=3)
        
        # Final status report
        logger.info("📈 FINAL HYBRID MONITORING REPORT")
        await tester.hybrid_manager.print_status_report()
        
        # Test summary
        runtime = (time.time() - tester.test_metrics["start_time"]) / 60
        logger.info("🏁 HYBRID MONITORING TEST SUMMARY")
        logger.info(f"   Runtime: {runtime:.1f} minutes")
        logger.info(f"   Total Events: {tester.test_metrics['total_events']}")
        logger.info(f"   Account Subscription Updates: {tester.test_metrics['high_priority_updates']}")
        logger.info(f"   Program Log Updates: {tester.test_metrics['medium_priority_updates']}")
        logger.info(f"   API Polling Updates: {tester.test_metrics['low_priority_updates']}")
        
        if tester.test_metrics['total_events'] > 0:
            logger.info("✅ Hybrid monitoring system working successfully!")
        else:
            logger.warning("⚠️ No blockchain events received during test")
        
    except KeyboardInterrupt:
        logger.info("🛑 Test interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
    finally:
        await tester.cleanup()

if __name__ == "__main__":
    asyncio.run(main()) 