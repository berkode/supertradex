"""
WebSocket Connection Manager
Handles all WebSocket connection lifecycle, endpoint management, and metrics
"""

import asyncio
import json
import logging
import random
import socket
import time
from typing import Dict, Optional, Tuple, Any
import websockets
from websockets import connect as websockets_connect
from websockets.exceptions import WebSocketException, ConnectionClosed, InvalidStatusCode
from websockets.asyncio.client import ClientConnection as WebSocketCommonProtocol
from websockets.protocol import State
import backoff

from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType
from utils.logger import get_logger
from performance import get_system_monitor, SystemMonitoringMixin
from performance.decorators import monitor_websocket_operation
from performance.system_monitor import record_websocket_connection_time, update_websocket_connections

class WebSocketConnectionManager(SystemMonitoringMixin):
    """
    Manages WebSocket connections for BlockchainListener
    Handles endpoint selection, connection lifecycle, metrics, and circuit breakers
    """
    
    COMPONENT_NAME = "websocket_connection_manager"
    
    def __init__(self, settings, logger: Optional[logging.Logger] = None):
        # Initialize performance monitoring mixin first
        super().__init__()
        
        self.settings = settings
        self.logger = logger or get_logger(__name__)
        
        # Initialize configuration directly from settings
        ws_config = {
            'WEBSOCKET_MAX_RETRIES_PER_ENDPOINT': getattr(settings, 'WEBSOCKET_MAX_RETRIES_PER_ENDPOINT', 3),
            'WEBSOCKET_CONNECT_TIMEOUT': getattr(settings, 'WEBSOCKET_CONNECT_TIMEOUT', 30)
        }
        
        # Initialize performance monitoring for this component
        self._update_health_status("initializing")
        
        # Connection storage
        self.connections: Dict[str, Optional[WebSocketCommonProtocol]] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        
        # Endpoint configuration
        self.primary_websocket_url = self._ensure_valid_ws_url(self.settings.HELIUS_WSS_URL)
        self.fallback_websocket_url = self._ensure_valid_ws_url(self.settings.SOLANA_MAINNET_WSS)
        
        # Endpoint status tracking
        self._endpoint_status = {
            "primary": {
                "url": self.primary_websocket_url,
                "failures": 0,
                "last_failure": 0,
                "is_active": True,
                "connection_attempts": 0,
                "connection_successes": 0,
                "subscription_attempts": 0,
                "subscription_successes": 0,
                "last_success_time": 0
            },
            "fallback": {
                "url": self.fallback_websocket_url,
                "failures": 0,
                "last_failure": 0,
                "is_active": False,
                "connection_attempts": 0,
                "connection_successes": 0,
                "subscription_attempts": 0,
                "subscription_successes": 0,
                "last_success_time": 0
            }
        }
        
        # Connection settings from centralized configuration
        self.MAX_ENDPOINT_FAILURES = ws_config.get('WEBSOCKET_MAX_RETRIES_PER_ENDPOINT', 3)
        self.ENDPOINT_FAILURE_RESET_SECONDS = 300  # 5 minutes
        self.CONNECTION_TIMEOUT = ws_config.get('WEBSOCKET_CONNECT_TIMEOUT', 30)
        
        # Metrics
        self.metrics = {
            "primary": {
                "total_connections": 0,
                "successful_connections": 0,
                "failed_connections": 0,
                "total_subscriptions": 0,
                "successful_subscriptions": 0,
                "failed_subscriptions": 0,
                "last_hour_attempts": 0,
                "last_hour_successes": 0,
                "last_hour_timestamp": time.time()
            },
            "fallback": {
                "total_connections": 0,
                "successful_connections": 0,
                "failed_connections": 0,
                "total_subscriptions": 0,
                "successful_subscriptions": 0,
                "failed_subscriptions": 0,
                "last_hour_attempts": 0,
                "last_hour_successes": 0,
                "last_hour_timestamp": time.time()
            },
            "price_monitor_fallbacks": 0,
            "timestamp": time.time()
        }
        
        # Register health check
        system_monitor = get_system_monitor()
        system_monitor.register_health_check("websocket_manager", self._health_check)
        
        self._update_health_status("healthy", {"initialized_at": time.time()})
        self.logger.info("WebSocketConnectionManager initialized with performance monitoring")
    
    def _ensure_valid_ws_url(self, url: str) -> str:
        """Ensure that a WebSocket URL is properly formatted with scheme and API key"""
        if not url:
            self.logger.error("Empty WebSocket URL provided")
            return "wss://invalid-placeholder"
            
        # Fix URL if it doesn't have the wss:// prefix
        if not url.startswith("wss://"):
            if url.startswith("http://"):
                url = url.replace("http://", "wss://")
            elif url.startswith("https://"):
                url = url.replace("https://", "wss://")
            else:
                url = f"wss://{url}"
        
        # Ensure URL has api-key parameter for Helius endpoints
        if "helius" in url.lower() and "api-key" not in url:
            if "?" in url:
                url = f"{url}&api-key={self.settings.HELIUS_API_KEY}"
            else:
                url = f"{url}?api-key={self.settings.HELIUS_API_KEY}"
        
        return url.strip()
    
    def _mask_url(self, url: str) -> str:
        """Mask API keys in URLs for logging"""
        try:
            from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            if 'api-key' in query_params:
                query_params['api-key'] = ['***']
            new_query = urlencode(query_params, doseq=True)
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        except Exception:
            return url
    
    def _is_connection_open(self, ws) -> bool:
        """Check if WebSocket connection is open"""
        if not ws:
            return False
        
        if hasattr(ws, 'state'):
            return ws.state == State.OPEN
        
        if hasattr(ws, 'open'):
            return ws.open
            
        return False
    
    def _select_endpoint(self, program_id_str: str) -> str:
        """Select the best endpoint for a connection"""
        # Use primary endpoint from settings (which should match primary_websocket_url)
        url_to_use = self.primary_websocket_url
        
        # Check if primary is available, otherwise use fallback
        primary_status = self._endpoint_status.get("primary", {})
        if primary_status.get("failures", 0) >= self.MAX_ENDPOINT_FAILURES:
            self.logger.warning(f"Primary endpoint has too many failures ({primary_status['failures']}), switching to fallback")
            url_to_use = self.fallback_websocket_url
            self._endpoint_status["primary"]["is_active"] = False
            self._endpoint_status["fallback"]["is_active"] = True
        else:
            self._endpoint_status["primary"]["is_active"] = True
            self._endpoint_status["fallback"]["is_active"] = False
        
        if not url_to_use:
            self.logger.error(f"No valid WebSocket URL available for program {program_id_str}")
            return "wss://invalid-empty-url-in-settings"
            
        self.logger.info(f"Selected endpoint for {program_id_str}: {self._mask_url(url_to_use)}")
        return url_to_use
    
    def _update_endpoint_metrics(self, endpoint_key: str, connection_success: bool, subscription_success: bool = None):
        """Update metrics for the specified endpoint"""
        if endpoint_key not in ["primary", "fallback", "unknown"]:
            self.logger.error(f"Invalid endpoint key: {endpoint_key}")
            return
        
        # For unknown endpoints, log but don't update detailed metrics
        if endpoint_key == "unknown":
            self.logger.warning(f"Metrics update for unknown endpoint - connection_success: {connection_success}")
            return
            
        endpoint_status = self._endpoint_status[endpoint_key]
        metrics = self.metrics[endpoint_key]
        
        endpoint_status["connection_attempts"] += 1
        metrics["total_connections"] += 1
        
        current_time = time.time()
        
        # Update hourly metrics
        if current_time - metrics["last_hour_timestamp"] > 3600:
            metrics["last_hour_attempts"] = 1
            metrics["last_hour_successes"] = 1 if connection_success else 0
            metrics["last_hour_timestamp"] = current_time
        else:
            metrics["last_hour_attempts"] += 1
            if connection_success:
                metrics["last_hour_successes"] += 1
        
        if connection_success:
            endpoint_status["connection_successes"] += 1
            metrics["successful_connections"] += 1
            endpoint_status["last_success_time"] = current_time
            endpoint_status["failures"] = 0
        else:
            metrics["failed_connections"] += 1
            endpoint_status["failures"] += 1
            endpoint_status["last_failure"] = current_time
            
        # Update subscription metrics if provided
        if subscription_success is not None:
            endpoint_status["subscription_attempts"] += 1
            metrics["total_subscriptions"] += 1
            
            if subscription_success:
                endpoint_status["subscription_successes"] += 1
                metrics["successful_subscriptions"] += 1
            else:
                metrics["failed_subscriptions"] += 1
    
    def get_connection(self, program_id_str: str) -> Optional[WebSocketCommonProtocol]:
        """Get existing connection for a program ID"""
        return self.connections.get(program_id_str)
    
    def is_connection_open(self, program_id_str: str) -> bool:
        """Check if connection for program ID is open"""
        ws = self.connections.get(program_id_str)
        return self._is_connection_open(ws)
    
    async def ensure_connection(self, program_id_str: str, max_wait_seconds: int = 10) -> Optional[WebSocketCommonProtocol]:
        """Ensure a connection exists and is open for the program ID"""
        # Check existing connection
        ws = self.connections.get(program_id_str)
        if self._is_connection_open(ws):
            return ws
        
        # Create new connection
        return await self.create_connection(program_id_str)
    
    @backoff.on_exception(
        backoff.expo,
        (WebSocketException, ConnectionClosed, InvalidStatusCode, asyncio.TimeoutError, socket.gaierror, OSError),
        max_tries=3,
        on_backoff=lambda details: None,  # Will be handled by caller
        on_giveup=lambda details: None    # Will be handled by caller
    )
    @monitor_websocket_operation("create_connection")
    async def create_connection(self, program_id_str: str) -> Optional[WebSocketCommonProtocol]:
        """Create a new WebSocket connection for a program ID"""
        selected_ws_url = self._select_endpoint(program_id_str)
        
        # Determine endpoint key for metrics
        endpoint_key = "primary"
        if selected_ws_url == self.primary_websocket_url:
            endpoint_key = "primary"
        elif selected_ws_url == self.fallback_websocket_url:
            endpoint_key = "fallback"
        else:
            endpoint_key = "unknown"
        
        try:
            connection_start_time = time.time()
            self.logger.info(f"Creating connection to {self._mask_url(selected_ws_url)} for {program_id_str}")
            
            # Track connection attempt
            self._increment_counter("connection_attempts", labels={"endpoint": endpoint_key, "program": program_id_str})
            
            # **FIXED: Initialize circuit breaker only once per program**
            if program_id_str not in self.circuit_breakers:
                self.circuit_breakers[program_id_str] = CircuitBreaker(
                    breaker_type=CircuitBreakerType.COMPONENT,
                    identifier=f"wss_{program_id_str}",
                    max_consecutive_failures=5,
                    reset_after_minutes=2,  # Reduced from 5 to 2 minutes for faster recovery
                )
                self.logger.info(f"🛡️ Created circuit breaker for {program_id_str}")
            
            # **FIXED: Get circuit breaker and check properly**
            circuit_breaker = self.circuit_breakers[program_id_str]
            is_circuit_open = circuit_breaker.check()  # check() returns True if circuit is OPEN (blocking)
            
            if is_circuit_open:
                self.logger.warning(f"🛡️ Circuit breaker OPEN for {program_id_str}, cannot attempt connection (failures: {circuit_breaker.consecutive_failures}/{circuit_breaker._max_consecutive_failures})")
                self._increment_counter("connection_failures", labels={"endpoint": endpoint_key, "program": program_id_str, "reason": "circuit_breaker_open"})
                return None
            
            self.logger.debug(f"🛡️ Circuit breaker CLOSED for {program_id_str}, proceeding with connection (failures: {circuit_breaker.consecutive_failures}/{circuit_breaker._max_consecutive_failures})")
            
            connect_timeout = getattr(self.settings, 'WEBSOCKET_CONNECTION_TIMEOUT', self.CONNECTION_TIMEOUT)
            
            with self.performance_timer("websocket_connect_time", {"endpoint": endpoint_key, "program": program_id_str}):
                ws_connection = await websockets_connect(
                    selected_ws_url,
                    open_timeout=connect_timeout,
                    ping_interval=getattr(self.settings, 'WEBSOCKET_PING_INTERVAL', 20),
                    ping_timeout=getattr(self.settings, 'WEBSOCKET_PING_TIMEOUT', 20),
                    max_size=getattr(self.settings, 'WEBSOCKET_MAX_MESSAGE_SIZE', None)
                )
            
            # Store connection
            self.connections[program_id_str] = ws_connection
            
            # **FIXED: Reset circuit breaker failures on successful connection**
            circuit_breaker.reset_failures()  # Reset failures on successful connection
            self.logger.info(f"✅ Connection successful for {program_id_str}, circuit breaker reset")
            
            self._update_endpoint_metrics(endpoint_key, connection_success=True)
            
            # Record performance metrics
            connection_duration = time.time() - connection_start_time
            record_websocket_connection_time(connection_duration, endpoint_key)
            self._increment_counter("connection_successes", labels={"endpoint": endpoint_key, "program": program_id_str})
            self._set_gauge("active_connections", len([c for c in self.connections.values() if self._is_connection_open(c)]))
            
            # Update component health
            self._update_health_status("healthy", {
                "active_connections": len(self.connections),
                "last_connection": time.time(),
                "endpoint": endpoint_key
            })
            
            self.logger.info(f"🔗 Successfully connected to {self._mask_url(selected_ws_url)} for {program_id_str}")
            return ws_connection
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create connection for {program_id_str}: {e}")
            self._update_endpoint_metrics(endpoint_key, connection_success=False)
            
            # Record failure metrics
            self._increment_counter("connection_failures", labels={"endpoint": endpoint_key, "program": program_id_str, "error_type": type(e).__name__})
            
            # Update health status
            self._update_health_status("degraded", {
                "last_error": str(e),
                "last_error_time": time.time(),
                "endpoint": endpoint_key
            })
            
            # **FIXED: Only increment circuit breaker failures on actual connection failures**
            if program_id_str in self.circuit_breakers:
                self.circuit_breakers[program_id_str].increment_failures()
                breaker_status = "OPEN" if self.circuit_breakers[program_id_str].is_active else "CLOSED"
                self.logger.warning(f"🛡️ Incremented circuit breaker failures for {program_id_str} (now: {self.circuit_breakers[program_id_str].consecutive_failures}/{self.circuit_breakers[program_id_str]._max_consecutive_failures}, status: {breaker_status})")
            
            raise
    
    async def close_connection(self, program_id_str: str):
        """Close connection for a program ID"""
        ws = self.connections.get(program_id_str)
        if ws and self._is_connection_open(ws):
            try:
                await ws.close()
                self.logger.info(f"Closed connection for {program_id_str}")
            except Exception as e:
                self.logger.error(f"Error closing connection for {program_id_str}: {e}")
        
        # Clean up
        self.connections.pop(program_id_str, None)
    
    async def close_all_connections(self):
        """Close all managed connections"""
        for program_id_str in list(self.connections.keys()):
            await self.close_connection(program_id_str)
    
    def get_endpoint_status(self) -> Dict[str, Any]:
        """Get current endpoint status and metrics"""
        current_time = time.time()
        status = {
            "primary": {
                "url": self._mask_url(self._endpoint_status["primary"]["url"]),
                "failures": self._endpoint_status["primary"]["failures"],
                "last_failure": self._endpoint_status["primary"]["last_failure"],
                "is_active": self._endpoint_status["primary"]["is_active"]
            },
            "fallback": {
                "url": self._mask_url(self._endpoint_status["fallback"]["url"]),
                "failures": self._endpoint_status["fallback"]["failures"],
                "last_failure": self._endpoint_status["fallback"]["last_failure"],
                "is_active": self._endpoint_status["fallback"]["is_active"]
            },
            "current": "primary" if self._endpoint_status["primary"]["is_active"] else "fallback"
        }
        
        # Add connection stats
        status["connections"] = {
            "total": len(self.connections),
            "active": sum(1 for ws in self.connections.values() if ws and self._is_connection_open(ws))
        }
        
        return status
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics for all endpoints"""
        current_time = time.time()
        metrics_copy = self.metrics.copy()
        
        # Add success rates
        for endpoint in ["primary", "fallback"]:
            endpoint_metrics = metrics_copy[endpoint]
            total_connections = endpoint_metrics["total_connections"]
            if total_connections > 0:
                endpoint_metrics["connection_success_rate"] = endpoint_metrics["successful_connections"] / total_connections
            else:
                endpoint_metrics["connection_success_rate"] = 0.0
                
            total_subscriptions = endpoint_metrics["total_subscriptions"]
            if total_subscriptions > 0:
                endpoint_metrics["subscription_success_rate"] = endpoint_metrics["successful_subscriptions"] / total_subscriptions
            else:
                endpoint_metrics["subscription_success_rate"] = 0.0
                
            hourly_attempts = endpoint_metrics["last_hour_attempts"]
            if hourly_attempts > 0:
                endpoint_metrics["hourly_success_rate"] = endpoint_metrics["last_hour_successes"] / hourly_attempts
            else:
                endpoint_metrics["hourly_success_rate"] = 0.0
        
        return metrics_copy
    
    def _health_check(self) -> bool:
        """Health check for WebSocket connection manager"""
        try:
            # Check if we have any active connections when we should
            active_connections = len([c for c in self.connections.values() if self._is_connection_open(c)])
            total_connections = len(self.connections)
            
            # Update connection metrics
            update_websocket_connections(active_connections, total_connections)
            
            # Health criteria:
            # 1. If we have connections configured, at least one should be active
            # 2. No excessive recent failures
            if total_connections > 0:
                connection_health = active_connections > 0
                
                # Check recent failure rate
                current_time = time.time()
                recent_failures = 0
                for endpoint_key in ["primary", "fallback"]:
                    endpoint_status = self._endpoint_status.get(endpoint_key, {})
                    last_failure = endpoint_status.get("last_failure", 0)
                    if current_time - last_failure < 300:  # Last 5 minutes
                        recent_failures += endpoint_status.get("failures", 0)
                
                failure_health = recent_failures < 5  # Less than 5 failures in 5 minutes
                
                overall_health = connection_health and failure_health
                
                # Update detailed health status
                health_details = {
                    "active_connections": active_connections,
                    "total_connections": total_connections,
                    "recent_failures": recent_failures,
                    "connection_health": connection_health,
                    "failure_health": failure_health
                }
                
                if overall_health:
                    self._update_health_status("healthy", health_details)
                else:
                    self._update_health_status("unhealthy", health_details)
                
                return overall_health
            else:
                # No connections configured - that's okay
                self._update_health_status("healthy", {"status": "no_connections_configured"})
                return True
                
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            self._update_health_status("error", {"health_check_error": str(e)})
            return False 