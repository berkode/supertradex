#!/usr/bin/env python3
"""
Hybrid Monitoring Manager
Implements different monitoring strategies based on token priority levels:
- HIGH priority: Direct account subscriptions + program logs
- MEDIUM priority: Program logs only  
- LOW priority: API polling fallback
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger
from config.blockchain_logging import setup_blockchain_logger

# Priority levels for token monitoring
class TokenPriority(Enum):
    HIGH = "high"      # Direct account subscriptions + program logs
    MEDIUM = "medium"  # Program logs only
    LOW = "low"        # API polling fallback

@dataclass
class MonitoredToken:
    mint: str
    symbol: str
    priority: TokenPriority
    pool_address: Optional[str] = None
    dex_id: Optional[str] = None
    account_subscription_id: Optional[int] = None
    logs_subscription_id: Optional[int] = None
    last_price_update: Optional[float] = None
    last_update_time: Optional[float] = None
    price_source: Optional[str] = None

class HybridMonitoringManager:
    """
    Manages hybrid monitoring approach with different strategies per priority level.
    """
    
    def __init__(self, settings, blockchain_listener, market_data, token_db, logger=None):
        self.settings = settings
        self.blockchain_listener = blockchain_listener
        self.market_data = market_data
        self.token_db = token_db
        self.logger = logger or get_logger(__name__)
        self.blockchain_logger = setup_blockchain_logger("HybridMonitoring")
        
        # Token tracking
        self.monitored_tokens: Dict[str, MonitoredToken] = {}
        self.priority_queues = {
            TokenPriority.HIGH: set(),
            TokenPriority.MEDIUM: set(),
            TokenPriority.LOW: set()
        }
        
        # Performance tracking
        self.performance_metrics = {
            "high_priority_subscriptions": 0,
            "medium_priority_subscriptions": 0,
            "low_priority_tokens": 0,
            "total_price_updates": 0,
            "account_subscription_updates": 0,
            "program_log_updates": 0,
            "api_fallback_updates": 0,
            "last_report_time": time.time()
        }
        
        # Background tasks
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.api_polling_task: Optional[asyncio.Task] = None
        
        self.blockchain_logger.info("HybridMonitoringManager initialized")

    async def add_high_priority_token(self, mint: str, symbol: str, pool_address: str, dex_id: str) -> bool:
        """
        Add a token to high-priority monitoring with direct account subscriptions.
        
        Args:
            mint: Token mint address
            symbol: Token symbol
            pool_address: Pool address for account subscription
            dex_id: DEX identifier
            
        Returns:
            bool: True if successfully added and subscribed
        """
        try:
            self.blockchain_logger.info(f"🎯 Adding HIGH priority token: {symbol} ({mint[:8]}...)")
            
            # Create monitored token object
            token = MonitoredToken(
                mint=mint,
                symbol=symbol,
                priority=TokenPriority.HIGH,
                pool_address=pool_address,
                dex_id=dex_id
            )
            
            # Subscribe to pool account updates for immediate price changes
            success = await self.blockchain_listener.subscribe_to_pool_account(pool_address, dex_id)
            if not success:
                self.blockchain_logger.error(f"Failed to establish account subscription for {symbol}")
                return False
            
            # Store token and add to high priority queue
            self.monitored_tokens[mint] = token
            self.priority_queues[TokenPriority.HIGH].add(mint)
            
            # Update metrics
            self.performance_metrics["high_priority_subscriptions"] += 1
            
            self.logger.info(f"✅ HIGH priority monitoring active for {symbol} - Direct account subscription enabled")
            return True
            
        except Exception as e:
            self.blockchain_logger.error(f"Error adding high priority token {symbol}: {e}", exc_info=True)
            return False

    async def add_medium_priority_token(self, mint: str, symbol: str, dex_id: str = None) -> bool:
        """
        Add a token to medium-priority monitoring (program logs only).
        
        Args:
            mint: Token mint address
            symbol: Token symbol
            dex_id: Optional DEX identifier
            
        Returns:
            bool: True if successfully added
        """
        try:
            self.blockchain_logger.info(f"📡 Adding MEDIUM priority token: {symbol} ({mint[:8]}...)")
            
            # Create monitored token object
            token = MonitoredToken(
                mint=mint,
                symbol=symbol,
                priority=TokenPriority.MEDIUM,
                dex_id=dex_id
            )
            
            # Store token and add to medium priority queue
            self.monitored_tokens[mint] = token
            self.priority_queues[TokenPriority.MEDIUM].add(mint)
            
            # Add to blockchain listener for program-level monitoring
            await self.blockchain_listener.add_token_to_monitor(mint)
            
            # Update metrics
            self.performance_metrics["medium_priority_subscriptions"] += 1
            
            self.logger.info(f"✅ MEDIUM priority monitoring active for {symbol} - Program logs subscription")
            return True
            
        except Exception as e:
            self.blockchain_logger.error(f"Error adding medium priority token {symbol}: {e}", exc_info=True)
            return False

    async def add_low_priority_token(self, mint: str, symbol: str) -> bool:
        """
        Add a token to low-priority monitoring (API polling only).
        
        Args:
            mint: Token mint address
            symbol: Token symbol
            
        Returns:
            bool: True if successfully added
        """
        try:
            self.blockchain_logger.info(f"⏱️ Adding LOW priority token: {symbol} ({mint[:8]}...)")
            
            # Create monitored token object
            token = MonitoredToken(
                mint=mint,
                symbol=symbol,
                priority=TokenPriority.LOW
            )
            
            # Store token and add to low priority queue
            self.monitored_tokens[mint] = token
            self.priority_queues[TokenPriority.LOW].add(mint)
            
            # Start API polling task if not already running
            if not self.api_polling_task:
                self.api_polling_task = asyncio.create_task(self._api_polling_loop())
            
            # Update metrics
            self.performance_metrics["low_priority_tokens"] += 1
            
            self.logger.info(f"✅ LOW priority monitoring active for {symbol} - API polling fallback")
            return True
            
        except Exception as e:
            self.blockchain_logger.error(f"Error adding low priority token {symbol}: {e}", exc_info=True)
            return False

    async def remove_token(self, mint: str) -> bool:
        """Remove a token from monitoring."""
        try:
            if mint not in self.monitored_tokens:
                self.blockchain_logger.warning(f"Token {mint[:8]}... not found in monitoring")
                return False
                
            token = self.monitored_tokens[mint]
            
            # Unsubscribe based on priority level
            if token.priority == TokenPriority.HIGH and token.pool_address:
                await self.blockchain_listener.unsubscribe_from_pool_data(token.pool_address)
                self.performance_metrics["high_priority_subscriptions"] -= 1
                
            elif token.priority == TokenPriority.MEDIUM:
                await self.blockchain_listener.remove_token_from_monitor(mint)
                self.performance_metrics["medium_priority_subscriptions"] -= 1
                
            elif token.priority == TokenPriority.LOW:
                self.performance_metrics["low_priority_tokens"] -= 1
            
            # Remove from tracking
            self.priority_queues[token.priority].remove(mint)
            del self.monitored_tokens[mint]
            
            self.logger.info(f"🗑️ Removed {token.symbol} from {token.priority.value} priority monitoring")
            return True
            
        except Exception as e:
            self.blockchain_logger.error(f"Error removing token {mint}: {e}", exc_info=True)
            return False

    async def handle_blockchain_event(self, event_data: Dict[str, Any]):
        """Handle blockchain events and route to appropriate tokens."""
        try:
            event_type = event_data.get("type")
            
            if event_type == "account_update":
                # High priority account updates
                await self._handle_account_update(event_data)
                
            elif event_type == "blockchain_event":
                # Medium priority program log updates
                await self._handle_program_log_update(event_data)
                
        except Exception as e:
            self.blockchain_logger.error(f"Error handling blockchain event: {e}")

    async def _handle_account_update(self, event_data: Dict[str, Any]):
        """Handle direct account updates for high priority tokens."""
        try:
            account_address = event_data.get("account_address")
            if not account_address:
                return
                
            # Find token by pool address
            token = None
            for mint, monitored_token in self.monitored_tokens.items():
                if (monitored_token.priority == TokenPriority.HIGH and 
                    monitored_token.pool_address == account_address):
                    token = monitored_token
                    break
                    
            if token:
                # Process account data to extract price
                price = await self._extract_price_from_account_data(event_data, token)
                if price:
                    await self._update_token_price(token, price, "account_subscription")
                    self.performance_metrics["account_subscription_updates"] += 1
                    
        except Exception as e:
            self.blockchain_logger.error(f"Error handling account update: {e}")

    async def _handle_program_log_update(self, event_data: Dict[str, Any]):
        """Handle program log updates for medium priority tokens."""
        try:
            logs = event_data.get("logs", [])
            program_id = event_data.get("program_id")
            
            # Check if any medium priority tokens are affected
            for mint in self.priority_queues[TokenPriority.MEDIUM]:
                token = self.monitored_tokens[mint]
                
                # Check if logs mention this token
                if self._logs_mention_token(logs, mint):
                    # Extract price from logs
                    price = await self._extract_price_from_logs(logs, token)
                    if price:
                        await self._update_token_price(token, price, "program_logs")
                        self.performance_metrics["program_log_updates"] += 1
                        
        except Exception as e:
            self.blockchain_logger.error(f"Error handling program log update: {e}")

    async def _api_polling_loop(self):
        """Background loop for API polling of low priority tokens."""
        try:
            while self.priority_queues[TokenPriority.LOW]:
                try:
                    for mint in list(self.priority_queues[TokenPriority.LOW]):
                        token = self.monitored_tokens.get(mint)
                        if not token:
                            continue
                            
                        # Get price from API
                        price_data = await self.market_data.get_token_price(mint, force_refresh=True)
                        if price_data and price_data.get("price"):
                            price = float(price_data["price"])
                            await self._update_token_price(token, price, "api_polling")
                            self.performance_metrics["api_fallback_updates"] += 1
                    
                    # Wait before next polling cycle
                    await asyncio.sleep(30)  # Poll every 30 seconds for low priority
                    
                except Exception as e:
                    self.blockchain_logger.error(f"Error in API polling loop: {e}")
                    await asyncio.sleep(10)  # Shorter wait on error
                    
        except asyncio.CancelledError:
            self.blockchain_logger.info("API polling loop cancelled")

    async def _update_token_price(self, token: MonitoredToken, price: float, source: str):
        """Update token price and log the update."""
        try:
            previous_price = token.last_price_update
            token.last_price_update = price
            token.last_update_time = time.time()
            token.price_source = source
            
            # Calculate price change
            change_text = ""
            if previous_price:
                change = ((price - previous_price) / previous_price) * 100
                change_text = f" ({change:+.2f}%)"
            
            # Log update with priority-specific emoji
            priority_emoji = {"high": "🔥", "medium": "📡", "low": "⏱️"}
            emoji = priority_emoji.get(token.priority.value, "📊")
            
            self.logger.info(f"{emoji} {token.priority.value.upper()} PRIORITY UPDATE: "
                           f"{token.symbol} = ${price:.8f}{change_text} (via {source})")
                           
            # Update performance metrics
            self.performance_metrics["total_price_updates"] += 1
            
        except Exception as e:
            self.blockchain_logger.error(f"Error updating token price: {e}")

    async def _extract_price_from_account_data(self, event_data: Dict[str, Any], token: MonitoredToken) -> Optional[float]:
        """Extract price from account data."""
        try:
            # This would parse the specific account data format for the DEX
            # For now, return a placeholder
            return None
        except Exception as e:
            self.blockchain_logger.error(f"Error extracting price from account data: {e}")
            return None

    async def _extract_price_from_logs(self, logs: List[str], token: MonitoredToken) -> Optional[float]:
        """Extract price from program logs."""
        try:
            # Use the existing parsers to extract price from logs
            if token.dex_id and hasattr(self.blockchain_listener, 'parsers'):
                parser = self.blockchain_listener.parsers.get(token.dex_id)
                if parser:
                    swap_data = parser.parse_swap_logs(logs, "hybrid_monitoring")
                    if swap_data and swap_data.get("price_usd"):
                        return float(swap_data["price_usd"])
            return None
        except Exception as e:
            self.blockchain_logger.error(f"Error extracting price from logs: {e}")
            return None

    def _logs_mention_token(self, logs: List[str], mint: str) -> bool:
        """Check if logs mention a specific token."""
        try:
            logs_text = " ".join(logs)
            return mint in logs_text
        except Exception as e:
            return False

    async def get_monitoring_status(self) -> Dict[str, Any]:
        """Get current monitoring status and metrics."""
        try:
            current_time = time.time()
            
            status = {
                "total_tokens": len(self.monitored_tokens),
                "high_priority_tokens": len(self.priority_queues[TokenPriority.HIGH]),
                "medium_priority_tokens": len(self.priority_queues[TokenPriority.MEDIUM]),
                "low_priority_tokens": len(self.priority_queues[TokenPriority.LOW]),
                "performance_metrics": self.performance_metrics.copy(),
                "active_tokens": {}
            }
            
            # Add details for each monitored token
            for mint, token in self.monitored_tokens.items():
                status["active_tokens"][mint] = {
                    "symbol": token.symbol,
                    "priority": token.priority.value,
                    "last_price": token.last_price_update,
                    "last_update": token.last_update_time,
                    "price_source": token.price_source,
                    "seconds_since_update": current_time - token.last_update_time if token.last_update_time else None
                }
            
            return status
            
        except Exception as e:
            self.blockchain_logger.error(f"Error getting monitoring status: {e}")
            return {"error": str(e)}

    async def print_status_report(self):
        """Print a detailed status report."""
        try:
            status = await self.get_monitoring_status()
            
            self.logger.info("=" * 60)
            self.logger.info("🎯 HYBRID MONITORING STATUS REPORT")
            self.logger.info("=" * 60)
            
            self.logger.info(f"📊 Total Tokens: {status['total_tokens']}")
            self.logger.info(f"🔥 High Priority: {status['high_priority_tokens']} (account subscriptions)")
            self.logger.info(f"📡 Medium Priority: {status['medium_priority_tokens']} (program logs)")
            self.logger.info(f"⏱️ Low Priority: {status['low_priority_tokens']} (API polling)")
            
            metrics = status['performance_metrics']
            self.logger.info(f"📈 Total Price Updates: {metrics['total_price_updates']}")
            self.logger.info(f"   - Account Subscription Updates: {metrics['account_subscription_updates']}")
            self.logger.info(f"   - Program Log Updates: {metrics['program_log_updates']}")
            self.logger.info(f"   - API Fallback Updates: {metrics['api_fallback_updates']}")
            
            self.logger.info("=" * 60)
            
        except Exception as e:
            self.blockchain_logger.error(f"Error printing status report: {e}")

    async def close(self):
        """Clean up resources."""
        try:
            self.blockchain_logger.info("Closing HybridMonitoringManager...")
            
            # Cancel API polling task
            if self.api_polling_task:
                self.api_polling_task.cancel()
                try:
                    await self.api_polling_task
                except asyncio.CancelledError:
                    pass
            
            # Unsubscribe from all high priority tokens
            for mint in list(self.priority_queues[TokenPriority.HIGH]):
                await self.remove_token(mint)
            
            self.blockchain_logger.info("HybridMonitoringManager closed")
            
        except Exception as e:
            self.blockchain_logger.error(f"Error closing HybridMonitoringManager: {e}") 