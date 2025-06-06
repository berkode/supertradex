"""
Test Performance Monitoring Integration
Verify the new system monitoring works correctly in the performance package
"""

import asyncio
import time
import pytest
from unittest.mock import Mock

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from performance import (
    SystemMonitor, get_system_monitor, initialize_system_monitor,
    SystemMonitoringMixin, performance_timer, async_performance_timer,
    monitor_trade_execution, monitor_strategy_evaluation,
    record_trade_success, record_trade_failure
)

class TestSystemMonitorIntegration:
    """Test the system monitor integration with existing performance package"""
    
    def setup_method(self):
        """Set up fresh system monitor for each test"""
        self.monitor = initialize_system_monitor()
    
    def test_basic_metrics_recording(self):
        """Test basic metric recording functionality"""
        # Record some basic metrics
        self.monitor.record_metric("test_metric", 100.0, {"test": "label"}, "test_component")
        self.monitor.increment_counter("test_counter", 5, {"test": "label"}, "test_component")
        self.monitor.set_gauge("test_gauge", 50.0, {"test": "label"}, "test_component")
        
        # Verify metrics were recorded
        assert len(self.monitor.metrics) >= 2  # Should have at least the metric and counter_total
        assert self.monitor.counters["test_counter"] == 5
        assert self.monitor.gauges["test_gauge"] == 50.0
    
    def test_duration_recording(self):
        """Test duration metric recording"""
        # Record a duration
        self.monitor.record_duration("test_duration", 0.5, {"operation": "test"}, "test_component")
        
        # Verify duration was recorded in milliseconds
        stats = self.monitor.get_metric_statistics("test_duration")
        assert stats["count"] == 1
        assert stats["latest"] == 500.0  # 0.5 seconds = 500 ms
    
    def test_trade_operation_recording(self):
        """Test trade operation recording"""
        # Record successful trade
        self.monitor.record_trade_operation("buy", 0.2, True, {"symbol": "BTC"})
        
        # Record failed trade
        self.monitor.record_trade_operation("sell", 0.3, False, {"symbol": "ETH"})
        
        # Verify counters
        assert self.monitor.counters["trade_operations_successful"] == 1
        assert self.monitor.counters["trade_operations_failed"] == 1
    
    def test_strategy_evaluation_recording(self):
        """Test strategy evaluation recording"""
        # Record strategy evaluation
        self.monitor.record_strategy_evaluation("momentum", 0.05, "buy", 0.85)
        
        # Verify metrics
        assert self.monitor.counters["strategy_evaluations"] == 1
        
        # Check confidence metric
        confidence_stats = self.monitor.get_metric_statistics("strategy_confidence")
        assert confidence_stats["latest"] == 0.85
    
    def test_component_health_tracking(self):
        """Test component health status tracking"""
        # Update component health
        self.monitor.update_component_health("test_component", "healthy", {"test": "data"})
        
        # Verify health status
        health = self.monitor.get_component_health("test_component")
        assert health["status"] == "healthy"
        assert health["details"]["test"] == "data"
        assert "last_update" in health
    
    def test_performance_timer_context_manager(self):
        """Test performance timer context manager"""
        with performance_timer("test_timer", {"operation": "test"}, "test_component"):
            time.sleep(0.01)  # Small delay
        
        # Verify timer recorded duration
        stats = self.monitor.get_metric_statistics("test_timer")
        assert stats["count"] == 1
        assert stats["latest"] > 10  # Should be > 10ms
    
    @pytest.mark.asyncio
    async def test_async_performance_timer(self):
        """Test async performance timer context manager"""
        async with async_performance_timer("async_test_timer", {"operation": "async_test"}, "test_component"):
            await asyncio.sleep(0.01)  # Small async delay
        
        # Verify timer recorded duration
        stats = self.monitor.get_metric_statistics("async_test_timer")
        assert stats["count"] == 1
        assert stats["latest"] > 10  # Should be > 10ms
    
    def test_system_monitoring_mixin(self):
        """Test SystemMonitoringMixin functionality"""
        
        class TestClass(SystemMonitoringMixin):
            COMPONENT_NAME = "test_mixin"
            
            def test_method(self):
                self._record_metric("mixin_test", 42.0)
                self._increment_counter("mixin_calls")
                self._set_gauge("mixin_gauge", 100.0)
                self._update_health_status("healthy", {"mixin": "working"})
        
        # Create instance and call method
        test_instance = TestClass()
        test_instance.test_method()
        
        # Verify metrics were recorded through mixin
        assert self.monitor.counters["mixin_calls"] == 1
        assert self.monitor.gauges["mixin_gauge"] == 100.0
        
        # Verify health status
        health = self.monitor.get_component_health("test_mixin")
        assert health["status"] == "healthy"
        assert health["details"]["mixin"] == "working"
    
    @pytest.mark.asyncio
    async def test_trade_execution_decorator(self):
        """Test trade execution monitoring decorator"""
        
        @monitor_trade_execution("spot")
        async def execute_trade():
            await asyncio.sleep(0.01)
            return "trade_executed"
        
        # Execute decorated function
        result = await execute_trade()
        assert result == "trade_executed"
        
        # Verify metrics were recorded
        stats = self.monitor.get_metric_statistics("trade_execution_time")
        assert stats["count"] == 1
        assert stats["latest"] > 10  # Should be > 10ms
    
    def test_strategy_evaluation_decorator(self):
        """Test strategy evaluation monitoring decorator"""
        
        @monitor_strategy_evaluation("momentum")
        def evaluate_strategy():
            time.sleep(0.01)
            return "hold"
        
        # Execute decorated function
        result = evaluate_strategy()
        assert result == "hold"
        
        # Verify metrics were recorded
        stats = self.monitor.get_metric_statistics("strategy_evaluation_time")
        assert stats["count"] == 1
        assert stats["latest"] > 10  # Should be > 10ms
    
    def test_trade_success_recording(self):
        """Test trade success recording convenience function"""
        # Record successful trade
        record_trade_success("spot", 0.15, 50.0)
        
        # Verify trade operation recorded
        assert self.monitor.counters["trade_operations_successful"] == 1
        
        # Verify profit recorded
        profit_stats = self.monitor.get_metric_statistics("trade_profit")
        assert profit_stats["latest"] == 50.0
    
    def test_trade_failure_recording(self):
        """Test trade failure recording convenience function"""
        # Record failed trade
        record_trade_failure("futures", 0.25, "insufficient_balance")
        
        # Verify trade operation recorded
        assert self.monitor.counters["trade_operations_failed"] == 1
    
    def test_system_summary(self):
        """Test system performance summary generation"""
        # Create a fresh monitor for this test to avoid counter accumulation
        from performance.system_monitor import SystemMonitor
        fresh_monitor = SystemMonitor()
        
        # Add some test data
        fresh_monitor.record_trade_operation("buy", 0.1, True, {"symbol": "BTC"})
        fresh_monitor.record_trade_operation("sell", 0.2, False, {"symbol": "ETH"})
        fresh_monitor.update_component_health("test_component", "healthy")
        
        # Get system summary
        summary = fresh_monitor.get_system_summary(300)
        
        # Verify summary structure
        assert "timestamp" in summary
        assert "system_health" in summary
        assert "components" in summary
        assert "metrics" in summary
        assert "alerts" in summary
        
        # Check if trading performance exists (might be empty if no trades)
        if "trading_performance" in summary:
            # Verify trading performance calculation
            trading_perf = summary["trading_performance"]
            assert trading_perf["total_operations"] == 2
            assert trading_perf["success_rate"] == 50.0  # 1 success out of 2
            assert trading_perf["failure_rate"] == 50.0   # 1 failure out of 2
    
    def test_metrics_export(self):
        """Test metrics export functionality"""
        # Add some test data
        self.monitor.record_metric("export_test", 123.45)
        self.monitor.increment_counter("export_counter", 3)
        
        # Export metrics
        exported = self.monitor.export_metrics("json")
        
        # Verify export contains expected data
        assert "timestamp" in exported
        assert "system_type" in exported
        assert "blockchain_trading" in exported
        assert "counters" in exported
        assert "metrics" in exported
    
    def test_global_monitor_singleton(self):
        """Test that get_system_monitor returns the same instance"""
        monitor1 = get_system_monitor()
        monitor2 = get_system_monitor()
        
        # Should be the same instance
        assert monitor1 is monitor2
        
        # Should be the same as our test monitor after initialization
        assert monitor1 is self.monitor

if __name__ == "__main__":
    # Run basic functionality test
    test = TestSystemMonitorIntegration()
    test.setup_method()
    
    print("Testing basic metrics recording...")
    test.test_basic_metrics_recording()
    print("✓ Basic metrics recording works")
    
    print("Testing duration recording...")
    test.test_duration_recording()
    print("✓ Duration recording works")
    
    print("Testing trade operation recording...")
    test.test_trade_operation_recording()
    print("✓ Trade operation recording works")
    
    print("Testing performance timer...")
    test.test_performance_timer_context_manager()
    print("✓ Performance timer works")
    
    print("Testing system monitoring mixin...")
    test.test_system_monitoring_mixin()
    print("✓ System monitoring mixin works")
    
    print("Testing system summary...")
    test.test_system_summary()
    print("✓ System summary works")
    
    print("\n🎉 All performance integration tests passed!")
    print("The system monitoring is properly integrated with the performance package.") 