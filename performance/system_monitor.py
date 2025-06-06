"""
System Performance Monitoring and Metrics
Real-time system performance tracking for blockchain trading operations
"""

import time
import asyncio
import threading
import statistics
from typing import Dict, List, Any, Optional, Union, Callable
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum
import json
from datetime import datetime, timezone
import logging

from utils.logger import get_logger

class MetricType(str, Enum):
    """Types of metrics supported by the system monitor"""
    COUNTER = "counter"          # Incrementing values (e.g., total messages)
    GAUGE = "gauge"             # Current values (e.g., active connections) 
    HISTOGRAM = "histogram"      # Distribution of values (e.g., response times)
    RATE = "rate"               # Rate per time period (e.g., messages per second)
    DURATION = "duration"        # Time-based measurements (e.g., processing time)

class ComponentType(str, Enum):
    """System components being monitored"""
    WEBSOCKET = "websocket"
    BLOCKCHAIN_LISTENER = "blockchain_listener"
    MESSAGE_DISPATCHER = "message_dispatcher"
    EVENT_HANDLER = "event_handler"
    PARSER = "parser"
    PRICE_MONITOR = "price_monitor"
    CONFIGURATION = "configuration"
    CIRCUIT_BREAKER = "circuit_breaker"
    HTTP_CLIENT = "http_client"
    DATABASE = "database"
    TRADING = "trading"
    STRATEGY = "strategy"
    EXECUTION = "execution"

@dataclass
class MetricValue:
    """Individual metric measurement"""
    timestamp: float
    value: Union[int, float]
    labels: Dict[str, str] = field(default_factory=dict)
    component: Optional[str] = None
    
class MetricSeries:
    """Time series data for a metric"""
    
    def __init__(self, metric_type: MetricType, max_size: int = 1000):
        self.metric_type = metric_type
        self.values: deque = deque(maxlen=max_size)
        self.total_samples = 0
        self._lock = threading.Lock()
    
    def add_value(self, value: Union[int, float], timestamp: Optional[float] = None, 
                 labels: Optional[Dict[str, str]] = None, component: Optional[str] = None):
        """Add a new metric value"""
        if timestamp is None:
            timestamp = time.time()
        
        metric_value = MetricValue(
            timestamp=timestamp,
            value=value,
            labels=labels or {},
            component=component
        )
        
        with self._lock:
            self.values.append(metric_value)
            self.total_samples += 1
    
    def get_latest(self, count: int = 1) -> List[MetricValue]:
        """Get the latest N values"""
        with self._lock:
            return list(self.values)[-count:]
    
    def get_range(self, start_time: float, end_time: Optional[float] = None) -> List[MetricValue]:
        """Get values within a time range"""
        if end_time is None:
            end_time = time.time()
        
        with self._lock:
            return [v for v in self.values if start_time <= v.timestamp <= end_time]
    
    def get_statistics(self, window_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Get statistical summary of the metric"""
        if window_seconds:
            cutoff_time = time.time() - window_seconds
            values = [v.value for v in self.values if v.timestamp >= cutoff_time]
        else:
            values = [v.value for v in self.values]
        
        if not values:
            return {"count": 0}
        
        stats = {
            "count": len(values),
            "total_samples": self.total_samples,
            "latest": values[-1] if values else None,
            "min": min(values),
            "max": max(values),
            "mean": statistics.mean(values)
        }
        
        if len(values) > 1:
            stats["median"] = statistics.median(values)
            stats["stdev"] = statistics.stdev(values)
        
        # Type-specific statistics
        if self.metric_type == MetricType.RATE and len(values) >= 2:
            # Calculate rate over time window
            time_span = self.values[-1].timestamp - self.values[0].timestamp
            if time_span > 0:
                stats["rate_per_second"] = len(values) / time_span
        
        if self.metric_type == MetricType.HISTOGRAM:
            values_sorted = sorted(values)
            stats["p50"] = statistics.median(values_sorted)
            if len(values_sorted) >= 4:
                stats["p95"] = values_sorted[int(0.95 * len(values_sorted))]
                stats["p99"] = values_sorted[int(0.99 * len(values_sorted))]
        
        return stats

class SystemMonitor:
    """
    System performance monitoring for blockchain trading operations
    
    Integrates with existing performance package for comprehensive monitoring:
    - Real-time system performance tracking
    - Component health monitoring  
    - Trading operation metrics
    - Integration with existing trading metrics
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or get_logger(__name__)
        
        # Metric storage
        self.metrics: Dict[str, MetricSeries] = {}
        self.counters: Dict[str, int] = defaultdict(int)
        self.gauges: Dict[str, float] = {}
        
        # Component health tracking
        self.component_health: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self.health_checks: Dict[str, Callable] = {}
        
        # System performance thresholds
        self.thresholds = {
            "websocket_connection_time_ms": 5000,  # 5 seconds max
            "message_processing_time_ms": 100,     # 100ms max per message
            "event_processing_time_ms": 50,        # 50ms max per event
            "price_update_latency_ms": 200,        # 200ms max price latency
            "circuit_breaker_failure_rate": 0.1,   # 10% max failure rate
            "memory_usage_mb": 1000,               # 1GB max memory
            "cpu_usage_percent": 80,               # 80% max CPU
            "trade_execution_time_ms": 500,        # 500ms max trade execution
            "strategy_evaluation_time_ms": 100     # 100ms max strategy evaluation
        }
        
        # Monitoring state
        self._monitoring_active = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._last_report_time = time.time()
        self._report_interval = 60  # Report every 60 seconds
        
        # Performance history for trending
        self.performance_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        
        # Integration with existing performance metrics
        self.trading_metrics_integration = True
        
        self.logger.info("SystemMonitor initialized for blockchain trading performance tracking")
    
    def register_metric(self, name: str, metric_type: MetricType, max_size: int = 1000):
        """Register a new metric for tracking"""
        if name not in self.metrics:
            self.metrics[name] = MetricSeries(metric_type, max_size)
            self.logger.debug(f"Registered system metric: {name} ({metric_type.value})")
    
    def register_health_check(self, component: str, check_function: Callable):
        """Register a health check function for a component"""
        self.health_checks[component] = check_function
        self.logger.debug(f"Registered health check for component: {component}")
    
    def record_metric(self, name: str, value: Union[int, float], 
                     labels: Optional[Dict[str, str]] = None,
                     component: Optional[str] = None):
        """Record a metric value"""
        if name not in self.metrics:
            # Auto-register as counter if not explicitly registered
            self.register_metric(name, MetricType.COUNTER)
        
        self.metrics[name].add_value(value, labels=labels, component=component)
    
    def increment_counter(self, name: str, amount: int = 1, 
                         labels: Optional[Dict[str, str]] = None,
                         component: Optional[str] = None):
        """Increment a counter metric"""
        self.counters[name] += amount
        self.record_metric(f"{name}_total", self.counters[name], labels, component)
    
    def set_gauge(self, name: str, value: Union[int, float],
                 labels: Optional[Dict[str, str]] = None,
                 component: Optional[str] = None):
        """Set a gauge metric value"""
        self.gauges[name] = value
        self.record_metric(name, value, labels, component)
    
    def record_duration(self, name: str, duration_seconds: float,
                       labels: Optional[Dict[str, str]] = None,
                       component: Optional[str] = None):
        """Record a duration metric"""
        if name not in self.metrics:
            self.register_metric(name, MetricType.DURATION)
        
        duration_ms = duration_seconds * 1000
        self.record_metric(name, duration_ms, labels, component)
    
    def record_trade_operation(self, operation_type: str, duration_seconds: float, 
                              success: bool, labels: Optional[Dict[str, str]] = None):
        """Record trading operation metrics"""
        base_labels = {"operation": operation_type, "success": str(success)}
        if labels:
            base_labels.update(labels)
        
        # Record duration
        self.record_duration(f"trade_operation_time_ms", duration_seconds, base_labels, "trading")
        
        # Record success/failure counters
        if success:
            self.increment_counter("trade_operations_successful", labels=base_labels, component="trading")
        else:
            self.increment_counter("trade_operations_failed", labels=base_labels, component="trading")
    
    def record_strategy_evaluation(self, strategy_name: str, duration_seconds: float,
                                  decision: str, confidence: float):
        """Record strategy evaluation metrics"""
        labels = {"strategy": strategy_name, "decision": decision}
        
        self.record_duration("strategy_evaluation_time_ms", duration_seconds, labels, "strategy")
        self.record_metric("strategy_confidence", confidence, labels, "strategy")
        self.increment_counter("strategy_evaluations", labels=labels, component="strategy")
    
    def update_component_health(self, component: str, status: str, 
                              details: Optional[Dict[str, Any]] = None):
        """Update health status for a component"""
        self.component_health[component].update({
            "status": status,
            "last_update": time.time(),
            "details": details or {}
        })
    
    def get_metric_statistics(self, name: str, window_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Get statistics for a metric"""
        if name not in self.metrics:
            return {"error": f"Metric {name} not found"}
        
        return self.metrics[name].get_statistics(window_seconds)
    
    def get_component_health(self, component: Optional[str] = None) -> Dict[str, Any]:
        """Get health status for components"""
        if component:
            return self.component_health.get(component, {"status": "unknown"})
        return dict(self.component_health)
    
    def get_system_summary(self, window_seconds: int = 300) -> Dict[str, Any]:
        """Get comprehensive system performance summary"""
        current_time = time.time()
        
        summary = {
            "timestamp": current_time,
            "window_seconds": window_seconds,
            "system_health": "healthy",
            "components": {},
            "metrics": {},
            "trading_performance": {},
            "alerts": []
        }
        
        # Component health summary
        for component, health in self.component_health.items():
            summary["components"][component] = {
                "status": health.get("status", "unknown"),
                "last_update": health.get("last_update", 0),
                "age_seconds": current_time - health.get("last_update", current_time)
            }
            
            # Check for stale health updates
            if summary["components"][component]["age_seconds"] > 300:  # 5 minutes
                summary["alerts"].append(f"Component {component} health data is stale")
                summary["system_health"] = "warning"
        
        # Key system metrics
        system_metrics = [
            "websocket_connections_active",
            "messages_processed_total", 
            "events_processed_total",
            "price_updates_total",
            "trade_operations_successful_total",
            "trade_operations_failed_total",
            "message_processing_time_ms",
            "trade_operation_time_ms",
            "strategy_evaluation_time_ms"
        ]
        
        for metric_name in system_metrics:
            if metric_name in self.metrics:
                stats = self.get_metric_statistics(metric_name, window_seconds)
                summary["metrics"][metric_name] = stats
                
                # Check thresholds
                if metric_name in self.thresholds:
                    threshold = self.thresholds[metric_name]
                    latest_value = stats.get("latest")
                    
                    if latest_value and latest_value > threshold:
                        summary["alerts"].append(f"{metric_name} ({latest_value}) exceeds threshold ({threshold})")
                        summary["system_health"] = "critical" if latest_value > threshold * 1.5 else "warning"
        
        # Trading performance summary
        successful = self.counters.get("trade_operations_successful", 0)
        failed = self.counters.get("trade_operations_failed", 0)
        total = successful + failed
        
        if total > 0:
            summary["trading_performance"] = {
                "total_operations": total,
                "success_rate": (successful / total * 100) if total > 0 else 0,
                "failure_rate": (failed / total * 100) if total > 0 else 0
            }
        
        return summary
    
    async def run_health_checks(self) -> Dict[str, Any]:
        """Run all registered health checks"""
        results = {}
        
        for component, check_function in self.health_checks.items():
            try:
                if asyncio.iscoroutinefunction(check_function):
                    result = await check_function()
                else:
                    result = check_function()
                
                results[component] = {
                    "status": "healthy" if result else "unhealthy",
                    "result": result,
                    "timestamp": time.time()
                }
                
            except Exception as e:
                results[component] = {
                    "status": "error",
                    "error": str(e),
                    "timestamp": time.time()
                }
                self.logger.error(f"Health check failed for {component}: {e}")
        
        return results
    
    def start_monitoring(self, report_interval: int = 60):
        """Start the system monitoring background task"""
        if self._monitoring_active:
            self.logger.warning("System monitoring already active")
            return
        
        self._report_interval = report_interval
        self._monitoring_active = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        self.logger.info(f"System monitoring started (reporting every {report_interval}s)")
    
    async def stop_monitoring(self):
        """Stop the system monitoring background task"""
        if not self._monitoring_active:
            return
        
        self._monitoring_active = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("System monitoring stopped")
    
    async def _monitoring_loop(self):
        """Background monitoring loop"""
        try:
            while self._monitoring_active:
                try:
                    # Generate system performance report
                    await self._generate_system_report()
                    
                    # Run health checks
                    health_results = await self.run_health_checks()
                    
                    # Update component health based on health check results
                    for component, result in health_results.items():
                        self.update_component_health(
                            component,
                            result["status"],
                            {"health_check_result": result.get("result")}
                        )
                    
                    # Sleep until next report
                    await asyncio.sleep(self._report_interval)
                    
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                    await asyncio.sleep(10)  # Short sleep on error
                    
        except asyncio.CancelledError:
            self.logger.info("Monitoring loop cancelled")
        except Exception as e:
            self.logger.error(f"Monitoring loop error: {e}", exc_info=True)
    
    async def _generate_system_report(self):
        """Generate and log system performance report"""
        try:
            summary = self.get_system_summary(self._report_interval)
            
            # Store in performance history
            self.performance_history["summary"].append({
                "timestamp": summary["timestamp"],
                "system_health": summary["system_health"],
                "alert_count": len(summary["alerts"]),
                "component_count": len(summary["components"]),
                "metric_count": len(summary["metrics"])
            })
            
            # Log summary
            self.logger.info(
                f"System Performance Report - Health: {summary['system_health']}, "
                f"Components: {len(summary['components'])}, "
                f"Alerts: {len(summary['alerts'])}"
            )
            
            # Log alerts if any
            for alert in summary["alerts"]:
                self.logger.warning(f"System Alert: {alert}")
            
            # Log key metrics
            for metric_name, stats in summary["metrics"].items():
                if stats.get("count", 0) > 0:
                    self.logger.info(
                        f"System Metric {metric_name}: count={stats['count']}, "
                        f"latest={stats.get('latest', 'N/A')}, "
                        f"mean={stats.get('mean', 'N/A'):.2f}"
                    )
            
            # Log trading performance
            if summary["trading_performance"]:
                perf = summary["trading_performance"]
                self.logger.info(
                    f"Trading Performance: {perf['total_operations']} operations, "
                    f"{perf['success_rate']:.1f}% success rate"
                )
            
            self._last_report_time = time.time()
            
        except Exception as e:
            self.logger.error(f"Error generating system report: {e}", exc_info=True)
    
    def export_metrics(self, format_type: str = "json") -> str:
        """Export all system metrics in specified format"""
        export_data = {
            "timestamp": time.time(),
            "system_type": "blockchain_trading",
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "component_health": dict(self.component_health),
            "metrics": {}
        }
        
        # Export metric statistics
        for name, series in self.metrics.items():
            export_data["metrics"][name] = {
                "type": series.metric_type.value,
                "statistics": series.get_statistics(),
                "recent_values": [
                    {"timestamp": v.timestamp, "value": v.value, "labels": v.labels}
                    for v in series.get_latest(10)
                ]
            }
        
        if format_type.lower() == "json":
            return json.dumps(export_data, indent=2, default=str)
        else:
            return str(export_data)
    
    def get_trends(self, window_hours: int = 24) -> Dict[str, Any]:
        """Get system performance trends over time"""
        cutoff_time = time.time() - (window_hours * 3600)
        
        trends = {
            "window_hours": window_hours,
            "summary_trend": [],
            "metric_trends": {}
        }
        
        # Get summary trend
        recent_summaries = [
            s for s in self.performance_history["summary"] 
            if s["timestamp"] >= cutoff_time
        ]
        trends["summary_trend"] = recent_summaries
        
        # Get metric trends
        for metric_name, series in self.metrics.items():
            recent_values = series.get_range(cutoff_time)
            if recent_values:
                trends["metric_trends"][metric_name] = {
                    "count": len(recent_values),
                    "trend_direction": self._calculate_trend([v.value for v in recent_values]),
                    "values": [{"timestamp": v.timestamp, "value": v.value} for v in recent_values[-20:]]
                }
        
        return trends
    
    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction for a series of values"""
        if len(values) < 2:
            return "stable"
        
        first_half = values[:len(values)//2]
        second_half = values[len(values)//2:]
        
        if not first_half or not second_half:
            return "stable"
        
        first_avg = statistics.mean(first_half)
        second_avg = statistics.mean(second_half)
        
        if second_avg > first_avg * 1.1:
            return "increasing"
        elif second_avg < first_avg * 0.9:
            return "decreasing"
        else:
            return "stable"

# Global system monitor instance
_system_monitor: Optional[SystemMonitor] = None

def get_system_monitor() -> SystemMonitor:
    """Get or create the global system monitor instance"""
    global _system_monitor
    if _system_monitor is None:
        _system_monitor = SystemMonitor()
    return _system_monitor

def initialize_system_monitor() -> SystemMonitor:
    """Initialize the global system monitor"""
    global _system_monitor
    _system_monitor = SystemMonitor()
    return _system_monitor

# Convenience functions for system metrics
def record_websocket_connection_time(duration_seconds: float, endpoint: str = ""):
    """Record WebSocket connection establishment time"""
    monitor = get_system_monitor()
    monitor.record_duration(
        "websocket_connection_time_ms",
        duration_seconds,
        labels={"endpoint": endpoint},
        component="websocket"
    )

def record_message_processing_time(duration_seconds: float, message_type: str = ""):
    """Record message processing time"""
    monitor = get_system_monitor()
    monitor.record_duration(
        "message_processing_time_ms",
        duration_seconds,
        labels={"message_type": message_type},
        component="message_dispatcher"
    )

def record_event_processing_time(duration_seconds: float, event_type: str = ""):
    """Record event processing time"""
    monitor = get_system_monitor()
    monitor.record_duration(
        "event_processing_time_ms",
        duration_seconds,
        labels={"event_type": event_type},
        component="event_handler"
    )

def record_price_update(latency_seconds: float, source: str = "", dex: str = ""):
    """Record price update metrics"""
    monitor = get_system_monitor()
    monitor.increment_counter(
        "price_updates",
        labels={"source": source, "dex": dex},
        component="price_monitor"
    )
    monitor.record_duration(
        "price_update_latency_ms",
        latency_seconds,
        labels={"source": source, "dex": dex},
        component="price_monitor"
    )

def record_trade_execution(duration_seconds: float, success: bool, trade_type: str = ""):
    """Record trade execution metrics"""
    monitor = get_system_monitor()
    monitor.record_trade_operation("execution", duration_seconds, success, {"trade_type": trade_type})

def record_strategy_decision(strategy_name: str, duration_seconds: float, decision: str, confidence: float):
    """Record strategy evaluation metrics"""
    monitor = get_system_monitor()
    monitor.record_strategy_evaluation(strategy_name, duration_seconds, decision, confidence)

def update_websocket_connections(active_count: int, total_count: int):
    """Update WebSocket connection metrics"""
    monitor = get_system_monitor()
    monitor.set_gauge("websocket_connections_active", active_count, component="websocket")
    monitor.set_gauge("websocket_connections_total", total_count, component="websocket")

def record_circuit_breaker_event(component: str, event_type: str):
    """Record circuit breaker events"""
    monitor = get_system_monitor()
    monitor.increment_counter(
        f"circuit_breaker_{event_type}",
        labels={"component": component},
        component="circuit_breaker"
    ) 