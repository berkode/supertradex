import logging
from typing import Tuple, Optional

# Import necessary components
from wallet.balance_checker import BalanceChecker
from config.settings import Settings
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType
from utils.logger import get_logger

# Configure logging
logger = get_logger(__name__)

class TradeValidator:
    def __init__(self, 
                 balance_checker: BalanceChecker, 
                 settings: Settings):
        """Initialize TradeValidator with BalanceChecker and Settings."""
        self.balance_checker = balance_checker
        self.settings = settings
        
        # Initialize circuit breaker with settings
        self.circuit_breaker = CircuitBreaker(
            breaker_type=CircuitBreakerType.COMPONENT,
            identifier="trade_validator",
            on_activate=self._on_circuit_breaker_activate,
            on_reset=self._on_circuit_breaker_reset
        )
        
        # Load thresholds from Settings object
        self.min_position_size_usd = settings.MIN_POSITION_SIZE_USD
        self.max_position_size_usd = settings.MAX_POSITION_SIZE_USD
        self.max_position_size_pct = settings.MAX_POSITION_SIZE_PCT
        # Use MAX_SLIPPAGE_PCT instead of MAX_SLIPPAGE
        self.max_slippage_percent = self.settings.MAX_SLIPPAGE_PCT * 100  # Convert decimal to percent
        self.min_price = settings.MIN_PRICE
        self.max_price = settings.MAX_PRICE

        logger.info(f"TradeValidator initialized. Max Slippage: {self.max_slippage_percent}%")
        
    def _on_circuit_breaker_activate(self) -> None:
        """Callback when circuit breaker activates."""
        logger.error("Circuit breaker activated - trade validation operations suspended")
        # TODO: Add notification to admin/telegram

    def _on_circuit_breaker_reset(self) -> None:
        """Callback when circuit breaker resets."""
        logger.info("Circuit breaker reset - trade validation operations resumed")
        # TODO: Add notification to admin/telegram
        
    async def _check_balance(self, token_mint: str, required_amount: float) -> Tuple[bool, str]:
        """Check if we have sufficient balance for a token."""
        if self.circuit_breaker.check():
            msg = "Circuit breaker active. Skipping balance check."
            logger.warning(msg)
            return False, msg
            
        logger.debug(f"Checking balance for {token_mint}, need {required_amount}")
        try:
            current_balance = await self.balance_checker.get_token_balance(token_mint)
            
            if current_balance is None:
                msg = f"Failed to fetch balance for {token_mint}"
                logger.error(msg)
                self.circuit_breaker.increment_failures()
                return False, msg
            
            if current_balance < required_amount:
                msg = f"Insufficient balance for {token_mint}. Have: {current_balance}, Need: {required_amount}"
                logger.warning(msg)
                return False, msg
            
            logger.debug(f"Balance sufficient for {token_mint}. Have: {current_balance}, Need: {required_amount}")
            self.circuit_breaker.reset()  # Reset on successful balance check
            return True, "Balance sufficient"
            
        except Exception as e:
            msg = f"Error checking balance for {token_mint}: {e}"
            logger.error(msg, exc_info=True)
            self.circuit_breaker.increment_failures()
            return False, msg

    async def validate_trade_params(
        self,
        input_mint: str,
        output_mint: str,
        amount_atomic: int,
        slippage_bps: Optional[int] = None
    ) -> bool:
        """
        Validates trade parameters before executing a trade.
        This is the main method called by OrderManager.
        """
        if self.circuit_breaker.check():
            msg = "Circuit breaker active. Skipping trade parameter validation."
            logger.warning(msg)
            return False
            
        try:
            # Convert atomic units to standard units for balance check
            decimals = await self.balance_checker.get_token_decimals(input_mint)
            if decimals is None:
                msg = f"Failed to get decimals for token {input_mint}"
                logger.error(msg)
                self.circuit_breaker.increment_failures()
                return False
                
            input_amount = amount_atomic / (10 ** decimals)
            
            # Validate using pre_swap check
            is_valid, msg = await self.validate_pre_swap(
                input_mint=input_mint,
                output_mint=output_mint,
                input_amount=input_amount,
                input_decimals=decimals
            )
            
            if not is_valid:
                logger.warning(f"Trade validation failed: {msg}")
                return False
                
            # Check slippage if provided
            if slippage_bps is not None:
                max_slippage_bps = int(self.max_slippage_percent * 100)  # Convert percent to bps
                if slippage_bps > max_slippage_bps:
                    msg = f"Slippage {slippage_bps} bps exceeds maximum {max_slippage_bps} bps"
                    logger.warning(msg)
                    return False
            
            self.circuit_breaker.reset()  # Reset on successful validation
            return True
            
        except Exception as e:
            msg = f"Error in trade parameter validation: {e}"
            logger.error(msg, exc_info=True)
            self.circuit_breaker.increment_failures()
            return False

    async def validate_pre_swap(
        self,
        input_mint: str,
        output_mint: str,
        input_amount: float,
        input_decimals: int
        ) -> Tuple[bool, str]:
        """
        Performs pre-swap validation checks.
        Currently focuses on input token balance.
        """
        if self.circuit_breaker.check():
            msg = "Circuit breaker active. Skipping pre-swap validation."
            logger.warning(msg)
            return False, msg
            
        try:
            # 1. Check Balance
            balance_ok, balance_msg = await self._check_balance(input_mint, input_amount)
            if not balance_ok:
                return False, balance_msg
                
            # 2. Add other pre-swap checks here if needed:
            # - Check against blacklists/whitelists (might need access to filter lists)
            # - Check against global risk limits (might need RiskManager)
            # - Basic sanity checks on amounts/mints
            
            logger.info(f"Pre-swap validation successful for {input_amount} {input_mint} -> {output_mint}")
            self.circuit_breaker.reset()  # Reset on successful validation
            return True, "Validation successful"
            
        except Exception as e:
            msg = f"Error in pre-swap validation: {e}"
            logger.error(msg, exc_info=True)
            self.circuit_breaker.increment_failures()
            return False, msg

    # Removed validate_trade as its parameters don't fit pre-swap checks easily.
    # Post-quote validation is largely handled by Jupiter API's slippage settings.


