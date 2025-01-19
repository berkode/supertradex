import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.getenv("LOG_FILE", "trade_validator.log")),
        logging.StreamHandler() if os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true" else None
    ]
)

class TradeValidator:
    def __init__(self):
        # Load thresholds from environment variables
        try:
            self.min_liquidity = float(os.getenv("MIN_LIQUIDITY", 100))
            self.max_liquidity = float(os.getenv("MAX_LIQUIDITY", 10000))
            self.max_gas_fee = float(os.getenv("MAX_GAS_FEE", 0.1))
            self.max_slippage = float(os.getenv("MAX_SLIPPAGE", 0.01))  # 1%
            self.max_spread = float(os.getenv("MAX_SPREAD", 0.02))  # 2%
            self.min_holders = int(os.getenv("MIN_HOLDERS", 100))
        except ValueError as e:
            logging.error(f"Error loading environment variables: {e}")
            raise RuntimeError("Invalid environment variable configuration.") from e

    def validate_slippage(self, expected_price: float, actual_price: float) -> bool:
        """Validate slippage between the expected and actual price."""
        slippage = abs(expected_price - actual_price) / expected_price
        if slippage > self.max_slippage:
            logging.warning(f"Slippage too high: {slippage:.2%} (Max: {self.max_slippage:.2%})")
            return False
        return True

    def validate_liquidity(self, liquidity: float) -> bool:
        """Validate liquidity levels for the token pair."""
        if liquidity < self.min_liquidity:
            logging.warning(f"Liquidity too low: {liquidity} (Min: {self.min_liquidity})")
            return False
        if liquidity > self.max_liquidity:
            logging.warning(f"Liquidity too high: {liquidity} (Max: {self.max_liquidity})")
            return False
        return True

    def validate_gas_fee(self, gas_fee: float) -> bool:
        """Validate gas fees for the trade."""
        if gas_fee > self.max_gas_fee:
            logging.warning(f"Gas fee too high: {gas_fee} (Max: {self.max_gas_fee})")
            return False
        return True

    def validate_spread(self, bid_price: float, ask_price: float) -> bool:
        """Validate the spread between bid and ask prices."""
        spread = (ask_price - bid_price) / bid_price
        if spread > self.max_spread:
            logging.warning(f"Spread too high: {spread:.2%} (Max: {self.max_spread:.2%})")
            return False
        return True

    def validate_token_holders(self, holders: int) -> bool:
        """Validate the minimum number of token holders."""
        if holders < self.min_holders:
            logging.warning(f"Not enough token holders: {holders} (Min: {self.min_holders})")
            return False
        return True

    def validate_trade(self, **trade_params) -> bool:
        """
        Validate all trade parameters before execution.

        Args:
            trade_params (dict): Dictionary containing trade parameters:
                - expected_price (float)
                - actual_price (float)
                - liquidity (float)
                - gas_fee (float)
                - bid_price (float)
                - ask_price (float)
                - holders (int)

        Returns:
            bool: True if all validations pass, otherwise False.
        """
        try:
            return all([
                self.validate_slippage(trade_params["expected_price"], trade_params["actual_price"]),
                self.validate_liquidity(trade_params["liquidity"]),
                self.validate_gas_fee(trade_params["gas_fee"]),
                self.validate_spread(trade_params["bid_price"], trade_params["ask_price"]),
                self.validate_token_holders(trade_params["holders"]),
            ])
        except KeyError as e:
            logging.error(f"Missing required trade parameter: {e}")
            return False


