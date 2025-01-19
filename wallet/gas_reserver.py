import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

class GasReserver:
    def __init__(self):
        self.default_gas_price = float(os.getenv("DEFAULT_GAS_PRICE", 0.00001))  # Default gas price if less than 25 trades
        self.gas_buffer = float(os.getenv("GAS_BUFFER_PERCENT", 3)) / 100  # 3% buffer
        self.trade_history = []  # Stores gas prices of the last 25 trades

    def calculate_average_gas_price(self) -> float:
        """
        Calculate the average gas price from the last 25 trades.
        If fewer than 25 trades exist, use the default gas price.

        Returns:
            float: The average gas price in SOL.
        """
        if len(self.trade_history) < 25:
            return self.default_gas_price
        return sum(self.trade_history[-25:]) / min(len(self.trade_history), 25)

    def add_gas_price(self, gas_price: float):
        """
        Add a gas price to the trade history. Ensures a maximum of 25 entries.

        Args:
            gas_price (float): Gas price of a trade in SOL.
        """
        self.trade_history.append(gas_price)
        if len(self.trade_history) > 25:
            self.trade_history.pop(0)

    def calculate_gas_reserve(self, max_tokens_to_hold: int) -> float:
        """
        Calculate the total gas reserve needed for swaps.

        Args:
            max_tokens_to_hold (int): Maximum number of tokens the wallet can hold.

        Returns:
            float: The total SOL required for gas reserves, including buffer.
        """
        average_gas_price = self.calculate_average_gas_price()
        total_gas = max_tokens_to_hold * average_gas_price * 2  # Multiply by 2 for swap-to-token and swap-back
        total_gas_with_buffer = total_gas * (1 + self.gas_buffer)
        return round(total_gas_with_buffer, 8)

    def ensure_gas_reserve(self, wallet_balance: float, max_tokens_to_hold: int) -> bool:
        """
        Validate if the wallet has sufficient SOL for gas reserves.

        Args:
            wallet_balance (float): Current SOL balance in the wallet.
            max_tokens_to_hold (int): Maximum number of tokens the wallet can hold.

        Returns:
            bool: True if wallet balance is sufficient, False otherwise.
        """
        required_gas_reserve = self.calculate_gas_reserve(max_tokens_to_hold)
        if wallet_balance < required_gas_reserve:
            print(f"Insufficient SOL balance: {wallet_balance} SOL (Required: {required_gas_reserve} SOL)")
            return False
        return True

