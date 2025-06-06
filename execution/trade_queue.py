import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable, TYPE_CHECKING
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType

logger = get_logger(__name__)

class TradePriority(Enum):
    HIGH = 3
    MEDIUM = 2
    LOW = 1

@dataclass
class TradeRequest:
    token_address: str
    amount: float
    is_buy: bool
    priority: TradePriority
    strategy_id: str
    timestamp: datetime
    metadata: Dict[str, Any]
    callback: Optional[Callable] = None

class TradeQueue:
    """
    Manages a prioritized queue of trade requests with proper execution handling.
    """
    
    def __init__(self, order_manager: 'OrderManager'):
        """
        Initialize the trade queue.
        
        Args:
            order_manager: OrderManager instance for executing trades
        """
        self.order_manager = order_manager
        self.queue: List[TradeRequest] = []
        self.processing = False
        self.circuit_breaker = CircuitBreaker(
            breaker_type=CircuitBreakerType.COMPONENT,
            identifier="trade_queue",
            on_activate=self._on_circuit_breaker_activate,
            on_reset=self._on_circuit_breaker_reset
        )
        
        # Metrics
        self.metrics = {
            "total_trades": 0,
            "successful_trades": 0,
            "failed_trades": 0,
            "queue_size": 0,
            "avg_processing_time": 0,
            "total_processing_time": 0
        }
        
        # Strategy-specific circuit breakers
        self.strategy_circuit_breakers: Dict[str, CircuitBreaker] = {}
        
        # Token-specific circuit breakers
        self.token_circuit_breakers: Dict[str, CircuitBreaker] = {}
        
        logger.info("TradeQueue initialized")
    
    def _on_circuit_breaker_activate(self) -> None:
        """Callback when main circuit breaker activates."""
        logger.error("Main circuit breaker activated - trade queue paused")
        self._notify_admin("Circuit breaker activated - trade queue paused")
    
    def _on_circuit_breaker_reset(self) -> None:
        """Callback when main circuit breaker resets."""
        logger.info("Main circuit breaker reset - trade queue resumed")
        self._notify_admin("Circuit breaker reset - trade queue resumed")
    
    def _get_strategy_circuit_breaker(self, strategy_id: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a specific strategy."""
        if strategy_id not in self.strategy_circuit_breakers:
            self.strategy_circuit_breakers[strategy_id] = CircuitBreaker(
                breaker_type=CircuitBreakerType.OPERATION,
                identifier=strategy_id,
                on_activate=lambda: self._on_strategy_circuit_breaker_activate(strategy_id),
                on_reset=lambda: self._on_strategy_circuit_breaker_reset(strategy_id)
            )
        return self.strategy_circuit_breakers[strategy_id]
    
    def _get_token_circuit_breaker(self, token_address: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a specific token."""
        if token_address not in self.token_circuit_breakers:
            self.token_circuit_breakers[token_address] = CircuitBreaker(
                breaker_type=CircuitBreakerType.TOKEN,
                identifier=token_address,
                on_activate=lambda: self._on_token_circuit_breaker_activate(token_address),
                on_reset=lambda: self._on_token_circuit_breaker_reset(token_address)
            )
        return self.token_circuit_breakers[token_address]
    
    def _on_strategy_circuit_breaker_activate(self, strategy_id: str) -> None:
        """Callback when strategy-specific circuit breaker activates."""
        logger.error(f"Circuit breaker activated for strategy {strategy_id}")
        self._notify_admin(f"Circuit breaker activated for strategy {strategy_id}")
    
    def _on_strategy_circuit_breaker_reset(self, strategy_id: str) -> None:
        """Callback when strategy-specific circuit breaker resets."""
        logger.info(f"Circuit breaker reset for strategy {strategy_id}")
        self._notify_admin(f"Circuit breaker reset for strategy {strategy_id}")
    
    def _on_token_circuit_breaker_activate(self, token_address: str) -> None:
        """Callback when token-specific circuit breaker activates."""
        logger.error(f"Circuit breaker activated for token {token_address}")
        self._notify_admin(f"Circuit breaker activated for token {token_address}")
    
    def _on_token_circuit_breaker_reset(self, token_address: str) -> None:
        """Callback when token-specific circuit breaker resets."""
        logger.info(f"Circuit breaker reset for token {token_address}")
        self._notify_admin(f"Circuit breaker reset for token {token_address}")
    
    def _notify_admin(self, message: str) -> None:
        """Notify admin of important events."""
        # TODO: Implement admin notification (e.g., Telegram, email)
        logger.info(f"Admin notification: {message}")
    
    async def add_trade(self, trade_request: TradeRequest) -> bool:
        """
        Add a trade request to the queue.
        
        Args:
            trade_request: Trade request to add
            
        Returns:
            bool: True if trade was added successfully
        """
        try:
            # Check circuit breakers
            if self.circuit_breaker.check():
                logger.warning("Main circuit breaker active, rejecting trade request")
                return False
            
            strategy_cb = self._get_strategy_circuit_breaker(trade_request.strategy_id)
            if strategy_cb.check():
                logger.warning(f"Strategy circuit breaker active for {trade_request.strategy_id}, rejecting trade")
                return False
            
            token_cb = self._get_token_circuit_breaker(trade_request.token_address)
            if token_cb.check():
                logger.warning(f"Token circuit breaker active for {trade_request.token_address}, rejecting trade")
                return False
            
            # Add to queue
            self.queue.append(trade_request)
            self.queue.sort(key=lambda x: (x.priority.value, -x.timestamp.timestamp()), reverse=True)
            self.metrics["queue_size"] = len(self.queue)
            
            logger.info(f"Added trade request to queue: {trade_request}")
            
            # Start processing if not already running
            if not self.processing:
                asyncio.create_task(self._process_queue())
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding trade to queue: {e}", exc_info=True)
            return False
    
    async def _process_queue(self):
        """Process the trade queue."""
        if self.processing:
            return
        
        self.processing = True
        logger.info("Starting trade queue processing")
        
        try:
            while self.queue:
                # Check main circuit breaker
                if self.circuit_breaker.check():
                    logger.warning("Main circuit breaker active, pausing queue processing")
                    break
                
                trade_request = self.queue[0]
                
                # Check strategy and token circuit breakers
                strategy_cb = self._get_strategy_circuit_breaker(trade_request.strategy_id)
                token_cb = self._get_token_circuit_breaker(trade_request.token_address)
                
                if strategy_cb.check() or token_cb.check():
                    logger.warning(f"Skipping trade due to circuit breaker: {trade_request}")
                    self.queue.pop(0)
                    continue
                
                # Process trade
                start_time = datetime.now()
                success = await self._execute_trade(trade_request)
                
                # Update metrics
                processing_time = (datetime.now() - start_time).total_seconds()
                self.metrics["total_processing_time"] += processing_time
                self.metrics["total_trades"] += 1
                if success:
                    self.metrics["successful_trades"] += 1
                else:
                    self.metrics["failed_trades"] += 1
                
                self.metrics["avg_processing_time"] = (
                    self.metrics["total_processing_time"] / self.metrics["total_trades"]
                )
                
                # Remove processed trade
                self.queue.pop(0)
                self.metrics["queue_size"] = len(self.queue)
                
                # Notify callback if provided
                if trade_request.callback:
                    try:
                        await trade_request.callback(success)
                    except Exception as e:
                        logger.error(f"Error in trade callback: {e}", exc_info=True)
                
                # Small delay between trades
                await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Error processing trade queue: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
        
        finally:
            self.processing = False
            logger.info("Trade queue processing completed")
    
    async def _execute_trade(self, trade_request: TradeRequest) -> bool:
        """
        Execute a single trade request.
        
        Args:
            trade_request: Trade request to execute
            
        Returns:
            bool: True if trade was successful
        """
        try:
            # Check circuit breakers again before execution
            if (self.circuit_breaker.check() or
                self._get_strategy_circuit_breaker(trade_request.strategy_id).check() or
                self._get_token_circuit_breaker(trade_request.token_address).check()):
                return False
            
            # Execute trade
            if trade_request.is_buy:
                result = await self.order_manager.execute_buy(
                    token_address=trade_request.token_address,
                    amount_usd=trade_request.amount,
                    metadata=trade_request.metadata
                )
            else:
                result = await self.order_manager.execute_sell(
                    token_address=trade_request.token_address,
                    amount_usd=trade_request.amount,
                    metadata=trade_request.metadata
                )
            
            if result:
                logger.info(f"Trade executed successfully: {trade_request}")
                return True
            else:
                logger.warning(f"Trade execution failed: {trade_request}")
                self._get_strategy_circuit_breaker(trade_request.strategy_id).increment_failures()
                self._get_token_circuit_breaker(trade_request.token_address).increment_failures()
                return False
            
        except Exception as e:
            logger.error(f"Error executing trade: {e}", exc_info=True)
            self._get_strategy_circuit_breaker(trade_request.strategy_id).increment_failures()
            self._get_token_circuit_breaker(trade_request.token_address).increment_failures()
            return False
    
    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current status of the trade queue.
        
        Returns:
            Dictionary with queue status information
        """
        return {
            "queue_size": len(self.queue),
            "processing": self.processing,
            "metrics": self.metrics,
            "circuit_breaker_status": {
                "main": self.circuit_breaker.is_active(),
                "strategies": {
                    strategy_id: cb.is_active()
                    for strategy_id, cb in self.strategy_circuit_breakers.items()
                },
                "tokens": {
                    token_address: cb.is_active()
                    for token_address, cb in self.token_circuit_breakers.items()
                }
            }
        }
    
    def clear_queue(self) -> None:
        """Clear all pending trades from the queue."""
        self.queue.clear()
        self.metrics["queue_size"] = 0
        logger.info("Trade queue cleared")
    
    async def close(self) -> None:
        """Close the trade queue and clean up resources."""
        logger.info("Closing trade queue")
        self.clear_queue()
        self.processing = False 