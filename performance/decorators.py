"""
Performance Monitoring Decorators for Trading System
Easy-to-use utilities for adding performance tracking to trading operations
"""

import time
import asyncio
import functools
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager, asynccontextmanager

from performance.system_monitor import get_system_monitor, ComponentType

class PerformanceTimer:
    """Context manager for timing code execution"""
    
    def __init__(self, metric_name: str, labels: Optional[Dict[str, str]] = None,
                 component: Optional[str] = None, logger: Optional = None):
        self.metric_name = metric_name
        self.labels = labels or {}
        self.component = component
        self.logger = logger
        self.start_time = None
        self.end_time = None
        self.duration = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        
        # Record the metric
        monitor = get_system_monitor()
        monitor.record_duration(self.metric_name, self.duration, self.labels, self.component)
        
        # Log if logger provided
        if self.logger:
            self.logger.debug(f"{self.metric_name}: {self.duration*1000:.2f}ms")

class AsyncPerformanceTimer:
    """Async context manager for timing async code execution"""
    
    def __init__(self, metric_name: str, labels: Optional[Dict[str, str]] = None,
                 component: Optional[str] = None, logger: Optional = None):
        self.metric_name = metric_name
        self.labels = labels or {}
        self.component = component
        self.logger = logger
        self.start_time = None
        self.end_time = None
        self.duration = None
    
    async def __aenter__(self):
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        
        # Record the metric
        monitor = get_system_monitor()
        monitor.record_duration(self.metric_name, self.duration, self.labels, self.component)
        
        # Log if logger provided
        if self.logger:
            self.logger.debug(f"{self.metric_name}: {self.duration*1000:.2f}ms")

def measure_performance(metric_name: str, labels: Optional[Dict[str, str]] = None,
                       component: Optional[str] = None, log_result: bool = True):
    """
    Decorator to measure function execution time
    
    Args:
        metric_name: Name of the metric to record
        labels: Optional labels for the metric
        component: Component name for categorization
        log_result: Whether to log the execution time
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                
                # Record metric
                monitor = get_system_monitor()
                monitor.record_duration(metric_name, duration, labels, component)
                
                # Increment call counter
                counter_name = f"{metric_name}_calls"
                monitor.increment_counter(counter_name, labels=labels, component=component)
                
                if log_result:
                    func_name = getattr(func, '__name__', 'unknown')
                    print(f"Performance: {func_name} took {duration*1000:.2f}ms")
        
        return wrapper
    return decorator

def measure_async_performance(metric_name: str, labels: Optional[Dict[str, str]] = None,
                             component: Optional[str] = None, log_result: bool = True):
    """
    Decorator to measure async function execution time
    
    Args:
        metric_name: Name of the metric to record
        labels: Optional labels for the metric
        component: Component name for categorization
        log_result: Whether to log the execution time
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                
                # Record metric
                monitor = get_system_monitor()
                monitor.record_duration(metric_name, duration, labels, component)
                
                # Increment call counter
                counter_name = f"{metric_name}_calls"
                monitor.increment_counter(counter_name, labels=labels, component=component)
                
                if log_result:
                    func_name = getattr(func, '__name__', 'unknown')
                    print(f"Performance: {func_name} took {duration*1000:.2f}ms")
        
        return wrapper
    return decorator

def count_calls(metric_name: str, labels: Optional[Dict[str, str]] = None,
               component: Optional[str] = None):
    """
    Decorator to count function calls
    
    Args:
        metric_name: Name of the counter metric
        labels: Optional labels for the metric
        component: Component name for categorization
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Increment counter before function execution
            monitor = get_system_monitor()
            monitor.increment_counter(metric_name, labels=labels, component=component)
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator

def count_async_calls(metric_name: str, labels: Optional[Dict[str, str]] = None,
                     component: Optional[str] = None):
    """
    Decorator to count async function calls
    
    Args:
        metric_name: Name of the counter metric
        labels: Optional labels for the metric
        component: Component name for categorization
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Increment counter before function execution
            monitor = get_system_monitor()
            monitor.increment_counter(metric_name, labels=labels, component=component)
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

def track_errors(metric_name: str, labels: Optional[Dict[str, str]] = None,
                component: Optional[str] = None, reraise: bool = True):
    """
    Decorator to track function errors and exceptions
    
    Args:
        metric_name: Name of the error metric
        labels: Optional labels for the metric
        component: Component name for categorization
        reraise: Whether to reraise caught exceptions
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Record error metric
                monitor = get_system_monitor()
                error_labels = {**(labels or {}), "error_type": type(e).__name__}
                monitor.increment_counter(metric_name, labels=error_labels, component=component)
                
                if reraise:
                    raise
                
        return wrapper
    return decorator

def track_async_errors(metric_name: str, labels: Optional[Dict[str, str]] = None,
                      component: Optional[str] = None, reraise: bool = True):
    """
    Decorator to track async function errors and exceptions
    
    Args:
        metric_name: Name of the error metric
        labels: Optional labels for the metric
        component: Component name for categorization
        reraise: Whether to reraise caught exceptions
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # Record error metric
                monitor = get_system_monitor()
                error_labels = {**(labels or {}), "error_type": type(e).__name__}
                monitor.increment_counter(metric_name, labels=error_labels, component=component)
                
                if reraise:
                    raise
                
        return wrapper
    return decorator

@contextmanager
def performance_timer(metric_name: str, labels: Optional[Dict[str, str]] = None,
                     component: Optional[str] = None, logger: Optional = None):
    """
    Context manager for timing code blocks
    
    Usage:
        with performance_timer("database_query_time", {"table": "users"}):
            # Database query code here
            pass
    """
    timer = PerformanceTimer(metric_name, labels, component, logger)
    with timer:
        yield timer

@asynccontextmanager
async def async_performance_timer(metric_name: str, labels: Optional[Dict[str, str]] = None,
                                 component: Optional[str] = None, logger: Optional = None):
    """
    Async context manager for timing async code blocks
    
    Usage:
        async with async_performance_timer("async_operation_time", {"operation": "fetch"}):
            # Async operation code here
            await some_async_function()
    """
    timer = AsyncPerformanceTimer(metric_name, labels, component, logger)
    async with timer:
        yield timer

class SystemMonitoringMixin:
    """
    Mixin class that provides system monitoring capabilities to any trading class
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._system_monitor = get_system_monitor()
        self._component_name = getattr(self, 'COMPONENT_NAME', self.__class__.__name__.lower())
    
    def _record_metric(self, metric_name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a metric for this component"""
        self._system_monitor.record_metric(
            metric_name, value, labels, self._component_name
        )
    
    def _increment_counter(self, counter_name: str, amount: int = 1, labels: Optional[Dict[str, str]] = None):
        """Increment a counter for this component"""
        self._system_monitor.increment_counter(
            counter_name, amount, labels, self._component_name
        )
    
    def _set_gauge(self, gauge_name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Set a gauge value for this component"""
        self._system_monitor.set_gauge(
            gauge_name, value, labels, self._component_name
        )
    
    def _record_duration(self, metric_name: str, duration_seconds: float, labels: Optional[Dict[str, str]] = None):
        """Record a duration metric for this component"""
        self._system_monitor.record_duration(
            metric_name, duration_seconds, labels, self._component_name
        )
    
    def _record_trade_operation(self, operation_type: str, duration_seconds: float, success: bool, labels: Optional[Dict[str, str]] = None):
        """Record a trading operation for this component"""
        self._system_monitor.record_trade_operation(
            operation_type, duration_seconds, success, labels
        )
    
    def _record_strategy_evaluation(self, strategy_name: str, duration_seconds: float, decision: str, confidence: float):
        """Record a strategy evaluation for this component"""
        self._system_monitor.record_strategy_evaluation(
            strategy_name, duration_seconds, decision, confidence
        )
    
    def _update_health_status(self, status: str, details: Optional[Dict[str, Any]] = None):
        """Update health status for this component"""
        self._system_monitor.update_component_health(
            self._component_name, status, details
        )
    
    def performance_timer(self, metric_name: str, labels: Optional[Dict[str, str]] = None):
        """Get a performance timer context manager for this component"""
        return performance_timer(metric_name, labels, self._component_name)
    
    def async_performance_timer(self, metric_name: str, labels: Optional[Dict[str, str]] = None):
        """Get an async performance timer context manager for this component"""
        return async_performance_timer(metric_name, labels, self._component_name)

# Trading-specific decorators

def monitor_trade_execution(trade_type: str = ""):
    """Decorator specifically for trade execution operations"""
    return measure_async_performance(
        "trade_execution_time",
        labels={"trade_type": trade_type} if trade_type else None,
        component="execution",
        log_result=True
    )

def monitor_strategy_evaluation(strategy_name: str = ""):
    """Decorator for strategy evaluation operations"""
    labels = {"strategy": strategy_name} if strategy_name else None
    return measure_performance(
        "strategy_evaluation_time",
        labels=labels,
        component="strategy",
        log_result=True
    )

def monitor_price_operation(source: str = "", dex: str = ""):
    """Decorator for price monitoring operations"""
    labels = {}
    if source:
        labels["source"] = source
    if dex:
        labels["dex"] = dex
    
    return measure_async_performance(
        "price_operation_time",
        labels=labels,
        component="price_monitor",
        log_result=True
    )

def monitor_websocket_operation(operation_name: str):
    """Decorator specifically for WebSocket operations"""
    return measure_async_performance(
        f"websocket_{operation_name}_time",
        component="websocket",
        log_result=True
    )

def monitor_message_processing(message_type: str = ""):
    """Decorator for message processing operations"""
    labels = {"message_type": message_type} if message_type else None
    return measure_async_performance(
        "message_processing_time",
        labels=labels,
        component="message_dispatcher",
        log_result=True
    )

def monitor_event_handling(event_type: str = ""):
    """Decorator for event handling operations"""
    labels = {"event_type": event_type} if event_type else None
    return measure_async_performance(
        "event_processing_time",
        labels=labels,
        component="event_handler",
        log_result=True
    )

def monitor_parser_operation(dex_id: str = "", operation: str = ""):
    """Decorator for parser operations"""
    labels = {}
    if dex_id:
        labels["dex_id"] = dex_id
    if operation:
        labels["operation"] = operation
    
    return measure_performance(
        "parser_operation_time",
        labels=labels,
        component="parser",
        log_result=True
    )

# Trading operation tracking helpers

def record_trade_success(trade_type: str, duration_seconds: float, profit: float):
    """Record successful trade execution"""
    monitor = get_system_monitor()
    monitor.record_trade_operation("execution", duration_seconds, True, {"trade_type": trade_type})
    monitor.record_metric("trade_profit", profit, {"trade_type": trade_type}, "trading")

def record_trade_failure(trade_type: str, duration_seconds: float, reason: str):
    """Record failed trade execution"""
    monitor = get_system_monitor()
    monitor.record_trade_operation("execution", duration_seconds, False, {"trade_type": trade_type, "failure_reason": reason})

def record_strategy_decision(strategy_name: str, duration_seconds: float, decision: str, confidence: float):
    """Record strategy evaluation decision"""
    monitor = get_system_monitor()
    monitor.record_strategy_evaluation(strategy_name, duration_seconds, decision, confidence)

def record_portfolio_update(portfolio_value: float, profit_loss: float):
    """Record portfolio performance metrics"""
    monitor = get_system_monitor()
    monitor.set_gauge("portfolio_value", portfolio_value, component="trading")
    monitor.record_metric("portfolio_pnl", profit_loss, component="trading")

# Circuit breaker monitoring helpers

def record_circuit_breaker_state_change(component: str, old_state: str, new_state: str):
    """Record circuit breaker state changes"""
    monitor = get_system_monitor()
    monitor.increment_counter(
        "circuit_breaker_state_changes",
        labels={"component": component, "from_state": old_state, "to_state": new_state},
        component="circuit_breaker"
    )

def record_circuit_breaker_trip(component: str, reason: str = ""):
    """Record circuit breaker trips"""
    monitor = get_system_monitor()
    labels = {"component": component}
    if reason:
        labels["reason"] = reason
    
    monitor.increment_counter(
        "circuit_breaker_trips",
        labels=labels,
        component="circuit_breaker"
    )

# Health check utilities

def create_health_check(component_name: str, check_function: Callable):
    """Create and register a health check for a component"""
    monitor = get_system_monitor()
    monitor.register_health_check(component_name, check_function)
    
    # Also create a decorator that can be used on methods
    def health_check_decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                monitor.update_component_health(component_name, "healthy", {"last_check": time.time()})
                return result
            except Exception as e:
                monitor.update_component_health(component_name, "unhealthy", {"error": str(e), "last_check": time.time()})
                raise
        return wrapper
    
    return health_check_decorator 