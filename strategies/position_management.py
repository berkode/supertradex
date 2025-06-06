import logging
from typing import List, Dict, Optional, TYPE_CHECKING
from datetime import datetime

from config import Settings, Thresholds
from utils.logger import get_logger
from wallet.balance_checker import BalanceChecker
from wallet.trade_validator import TradeValidator
from execution.transaction_tracker import TransactionTracker
from execution.order_manager import OrderManager
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType
from data.token_database import TokenDatabase

if TYPE_CHECKING:
    from execution.order_manager import OrderManager as OrderManagerType

logger = get_logger("PositionManagement")


class PositionManagement:
    def __init__(self, 
                 order_manager: 'OrderManagerType',
                 settings: Settings, 
                 thresholds: Thresholds,
                 balance_checker: BalanceChecker,
                 trade_validator: TradeValidator
                 ):
        self.settings = settings
        self.thresholds = thresholds
        self.balance_checker = balance_checker
        self.trade_validator = trade_validator
        self.order_manager = order_manager
        
        # Initialize circuit breaker for position management
        self.circuit_breaker = CircuitBreaker(
            breaker_type=CircuitBreakerType.COMPONENT,
            identifier="position_management",
            max_consecutive_failures=3,
            reset_after_minutes=30,
            on_activate=self._on_circuit_breaker_activate,
            on_reset=self._on_circuit_breaker_reset
        )
        
        # Position state tracking
        self.position_states = {}  # Track position states
        self.position_updates = {}  # Track position updates
        
        logger.info("PositionManagement initialized")

    def _on_circuit_breaker_activate(self) -> None:
        """Callback when circuit breaker activates."""
        logger.error("Circuit breaker activated - position management operations suspended")
        # TODO: Add notification to admin/telegram

    def _on_circuit_breaker_reset(self) -> None:
        """Callback when circuit breaker resets."""
        logger.info("Circuit breaker reset - position management operations resumed")
        # TODO: Add notification to admin/telegram

    async def calculate_position_size(self, 
                                    account_balance: float, 
                                    risk_per_trade: float, 
                                    entry_price: float, 
                                    stop_loss: float,
                                    strategy: str) -> float:
        """
        Calculate position size dynamically based on risk tolerance and trade parameters.
        """
        try:
            # Check circuit breaker
            if self.circuit_breaker.check():
                logger.warning("Circuit breaker active. Skipping position size calculation.")
                return 0
                
            risk_amount = account_balance * risk_per_trade
            stop_loss_distance = abs(entry_price - stop_loss)
            if stop_loss_distance == 0:
                raise ValueError("Stop-loss distance cannot be zero.")
                
            # Apply strategy-specific adjustments
            strategy_multiplier = self.settings.STRATEGY_DEVIATIONS.get(strategy, {}).get("position_size_multiplier", 1.0)
            position_size = (risk_amount / stop_loss_distance) * strategy_multiplier
            
            # Record calculation
            self.position_updates[datetime.now().isoformat()] = {
                "type": "size_calculation",
                "strategy": strategy,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "position_size": position_size
            }
            
            logger.info(f"Calculated position size: {position_size} (Entry: {entry_price}, Stop Loss: {stop_loss}).")
            return position_size
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            self.circuit_breaker.increment_failures()
            return 0

    async def scale_in(self, 
                      symbol: str, 
                      current_price: float, 
                      target_price: float, 
                      max_position_size: float,
                      strategy: str):
        """
        Dynamically scale into a position based on price proximity to the target.
        """
        try:
            # Check circuit breaker
            if self.circuit_breaker.check():
                logger.warning(f"Circuit breaker active. Skipping scale-in for {symbol}.")
                return
                
            scale_factor = (target_price - current_price) / target_price
            additional_size = max_position_size * max(scale_factor, 0)
            
            if additional_size <= 0:
                logger.info(f"Scale-in size for {symbol} is zero or negative. Skipping scale-in.")
                return

            # Execute trade through OrderManager
            trade_id = await self.order_manager.execute_jupiter_swap(
                trade_id=len(self.position_updates) + 1,  # Generate unique ID
                input_mint=str(self.order_manager.SOL_MINT),  # Use SOL for scaling in
                output_mint=symbol,
                input_amount=additional_size,
                input_decimals=9,  # SOL decimals
                slippage_bps=self.settings.SLIPPAGE_BPS
            )
            
            if trade_id:
                # Update position state
                self.position_states[symbol] = {
                    "strategy": strategy,
                    "current_size": self.position_states.get(symbol, {}).get("current_size", 0) + additional_size,
                    "average_price": current_price,
                    "last_update": datetime.now().isoformat()
                }
                
                logger.info(f"Successfully scaled into {symbol}. Trade ID: {trade_id}")
            else:
                self.circuit_breaker.increment_failures()
                
        except Exception as e:
            logger.error(f"Failed to execute scale-in for {symbol}: {e}")
            self.circuit_breaker.increment_failures()

    async def scale_out(self, 
                       symbol: str, 
                       current_price: float, 
                       position_size: float, 
                       scale_out_ratio: float,
                       strategy: str):
        """
        Dynamically scale out of a position by reducing position size proportionally.
        """
        try:
            # Check circuit breaker
            if self.circuit_breaker.check():
                logger.warning(f"Circuit breaker active. Skipping scale-out for {symbol}.")
                return
                
            size_to_scale_out = position_size * scale_out_ratio
            if size_to_scale_out <= 0:
                logger.info(f"Scale-out size for {symbol} is zero or negative. Skipping scale-out.")
                return

            # Execute trade through OrderManager
            trade_id = await self.order_manager.execute_jupiter_swap(
                trade_id=len(self.position_updates) + 1,
                input_mint=symbol,
                output_mint=str(self.order_manager.SOL_MINT),
                input_amount=size_to_scale_out,
                input_decimals=9,  # Assuming token decimals
                slippage_bps=self.settings.SLIPPAGE_BPS
            )
            
            if trade_id:
                # Update position state
                current_state = self.position_states.get(symbol, {})
                new_size = current_state.get("current_size", 0) - size_to_scale_out
                
                if new_size <= 0:
                    del self.position_states[symbol]
                else:
                    self.position_states[symbol] = {
                        "strategy": strategy,
                        "current_size": new_size,
                        "average_price": current_state.get("average_price", current_price),
                        "last_update": datetime.now().isoformat()
                    }
                
                logger.info(f"Successfully scaled out of {symbol}. Trade ID: {trade_id}")
            else:
                self.circuit_breaker.increment_failures()
                
        except Exception as e:
            logger.error(f"Failed to execute scale-out for {symbol}: {e}")
            self.circuit_breaker.increment_failures()

    async def take_partial_profits(self, 
                                 symbol: str, 
                                 current_price: float, 
                                 position_size: float, 
                                 profit_target: float,
                                 strategy: str):
        """
        Take partial profits if the current price meets or exceeds the profit target.
        """
        try:
            # Check circuit breaker
            if self.circuit_breaker.check():
                logger.warning(f"Circuit breaker active. Skipping partial profits for {symbol}.")
                return
                
            if current_price < profit_target:
                logger.debug(f"{symbol}: Current price {current_price} is below profit target {profit_target}. No partial profits taken.")
                return

            partial_size = position_size * self.thresholds.PARTIAL_PROFIT_RATIO
            
            # Execute trade through OrderManager
            trade_id = await self.order_manager.execute_jupiter_swap(
                trade_id=len(self.position_updates) + 1,
                input_mint=symbol,
                output_mint=str(self.order_manager.SOL_MINT),
                input_amount=partial_size,
                input_decimals=9,
                slippage_bps=self.settings.SLIPPAGE_BPS
            )
            
            if trade_id:
                # Update position state
                current_state = self.position_states.get(symbol, {})
                new_size = current_state.get("current_size", 0) - partial_size
                
                if new_size <= 0:
                    del self.position_states[symbol]
                else:
                    self.position_states[symbol] = {
                        "strategy": strategy,
                        "current_size": new_size,
                        "average_price": current_state.get("average_price", current_price),
                        "last_update": datetime.now().isoformat()
                    }
                
                logger.info(f"Partial profits taken for {symbol}. Trade ID: {trade_id}")
            else:
                self.circuit_breaker.increment_failures()
                
        except Exception as e:
            logger.error(f"Failed to execute partial profits for {symbol}: {e}")
            self.circuit_breaker.increment_failures()

    async def rebalance_positions(self, positions: List[Dict], account_balance: float):
        """
        Rebalance positions dynamically to maintain risk and portfolio alignment.
        """
        try:
            # Check circuit breaker
            if self.circuit_breaker.check():
                logger.warning("Circuit breaker active. Skipping position rebalancing.")
                return
                
            for position in positions:
                symbol = position["symbol"]
                strategy = position.get("strategy", "default")
                current_size = position["size"]
                entry_price = position["entry_price"]
                stop_loss = position["stop_loss"]
                current_price = position["current_price"]

                target_size = await self.calculate_position_size(
                    account_balance=account_balance,
                    risk_per_trade=self.settings.RISK_PER_TRADE,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    strategy=strategy
                )

                if current_size < target_size:
                    logger.info(f"{symbol}: Current size {current_size} below target {target_size}. Scaling in.")
                    await self.scale_in(symbol, current_price, entry_price, target_size, strategy)
                elif current_size > target_size:
                    logger.info(f"{symbol}: Current size {current_size} exceeds target {target_size}. Scaling out.")
                    await self.scale_out(symbol, current_price, current_size, 0.5, strategy)
                    
        except Exception as e:
            logger.error(f"Error during position rebalancing: {e}")
            self.circuit_breaker.increment_failures()

    async def manage_positions(self, positions: List[Dict], account_balance: float):
        """
        Manage positions comprehensively, including taking partial profits and rebalancing.
        """
        try:
            # Check circuit breaker
            if self.circuit_breaker.check():
                logger.warning("Circuit breaker active. Skipping position management.")
                return
                
            for position in positions:
                symbol = position["symbol"]
                strategy = position.get("strategy", "default")
                current_price = position["current_price"]
                position_size = position["size"]
                profit_target = position.get("profit_target", current_price * (1 + self.thresholds.GAIN_TARGET_RATIO))

                # Take partial profits
                await self.take_partial_profits(symbol, current_price, position_size, profit_target, strategy)

            # Rebalance positions after taking partial profits
            await self.rebalance_positions(positions, account_balance)
            logger.info("Position management completed successfully.")
            
        except Exception as e:
            logger.error(f"Error during position management: {e}")
            self.circuit_breaker.increment_failures()

    def get_position_state(self, symbol: str) -> Optional[Dict]:
        """Get the current state of a position."""
        return self.position_states.get(symbol)

    def get_position_history(self, symbol: str) -> List[Dict]:
        """Get the history of position updates for a symbol."""
        return [
            update for update in self.position_updates.values()
            if update.get("symbol") == symbol
        ]

