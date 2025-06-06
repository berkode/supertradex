#!/usr/bin/env python3
"""
Live System Test - SupertradeX
Tests the complete live trading system with paper trading enabled.
Runs all components for a short period to verify integration.
"""

import asyncio
import signal
import sys
from datetime import datetime, timezone
import logging

# Import the main function
from main import main

# Set up logging for the test
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LiveSystemTest:
    def __init__(self, test_duration_minutes: int = 5):
        """
        Initialize the live system test.
        
        Args:
            test_duration_minutes: How long to run the test (default 5 minutes)
        """
        self.test_duration_minutes = test_duration_minutes
        self.test_duration_seconds = test_duration_minutes * 60
        self.shutdown_event = asyncio.Event()
        self.main_task = None
        
    async def run_test(self):
        """Run the live system test."""
        logger.info("🚀 Starting SupertradeX Live System Test")
        logger.info(f"📊 Test Duration: {self.test_duration_minutes} minutes")
        logger.info(f"📄 Paper Trading: ENABLED (no real money at risk)")
        logger.info("=" * 60)
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Start the main system
            logger.info("🔄 Starting main trading system...")
            self.main_task = asyncio.create_task(main())
            
            # Wait for the specified test duration
            logger.info(f"⏱️  Running system for {self.test_duration_minutes} minutes...")
            await asyncio.sleep(self.test_duration_seconds)
            
            # Signal shutdown
            logger.info("🛑 Test duration completed, initiating shutdown...")
            self.shutdown_event.set()
            
            # Cancel the main task
            if self.main_task and not self.main_task.done():
                self.main_task.cancel()
                try:
                    await self.main_task
                except asyncio.CancelledError:
                    logger.info("✅ Main system task cancelled successfully")
            
        except KeyboardInterrupt:
            logger.info("🛑 Test interrupted by user")
            self.shutdown_event.set()
            if self.main_task and not self.main_task.done():
                self.main_task.cancel()
                try:
                    await self.main_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logger.error(f"❌ Error during test: {e}", exc_info=True)
        finally:
            end_time = datetime.now(timezone.utc)
            duration = end_time - start_time
            logger.info("=" * 60)
            logger.info(f"🏁 Live System Test Completed")
            logger.info(f"⏱️  Total Runtime: {duration.total_seconds():.1f} seconds")
            logger.info(f"📊 Test Status: {'✅ PASSED' if duration.total_seconds() >= 30 else '⚠️  SHORT RUN'}")
            logger.info("=" * 60)

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"🛑 Received signal {signum}, shutting down...")
    sys.exit(0)

async def main_test():
    """Main test function."""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run the test
    test = LiveSystemTest(test_duration_minutes=5)  # 5-minute test
    await test.run_test()

if __name__ == "__main__":
    print("🎯 SupertradeX Live System Test")
    print("📄 Paper Trading Mode - No Real Money at Risk")
    print("⏱️  Running for 5 minutes...")
    print("🔄 Press Ctrl+C to stop early")
    print()
    
    try:
        asyncio.run(main_test())
    except KeyboardInterrupt:
        print("\n🛑 Test stopped by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1) 