import os
import statistics
from dotenv import load_dotenv
import requests
import time

# Load environment variables from .env
load_dotenv()

class GasManager:
    def __init__(self):
        # Configurable thresholds
        self.default_gas_price = float(os.getenv("DEFAULT_GAS_PRICE", 0.00001))  # Default gas price in SOL
        self.max_gas_price = float(os.getenv("MAX_GAS_PRICE", 0.0001))  # Maximum gas price allowed in SOL
        self.min_gas_price = float(os.getenv("MIN_GAS_PRICE", 0.000005))  # Minimum gas price allowed in SOL
        self.api_endpoint = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")  # RPC endpoint
        self.network_poll_interval = int(os.getenv("NETWORK_POLL_INTERVAL", 10))  # Seconds between network checks
        self.gas_price_history = []  # Store historical gas prices

    def fetch_current_gas_price(self) -> float:
        """
        Fetch the current gas price from the Solana network.
        This uses the `getRecentBlockhash` RPC call to estimate gas fees.

        Returns:
            float: Current gas price in SOL.
        """
        try:
            response = requests.post(
                self.api_endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getFeeCalculatorForBlockhash",
                    "params": [self._get_recent_blockhash()]
                },
            )
            response_data = response.json()
            if "error" in response_data:
                raise RuntimeError(f"RPC Error: {response_data['error']['message']}")

            fee_calculator = response_data["result"]["value"]
            if fee_calculator is None:
                raise RuntimeError("Fee calculator unavailable.")

            lamports_per_signature = fee_calculator["feeCalculator"]["lamportsPerSignature"]
            return lamports_per_signature / 10**9  # Convert lamports to SOL
        except Exception as e:
            print(f"Error fetching current gas price: {e}")
            return self.default_gas_price

    def _get_recent_blockhash(self) -> str:
        """
        Get the most recent blockhash from the Solana network.

        Returns:
            str: A recent blockhash.
        """
        response = requests.post(
            self.api_endpoint,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentBlockhash",
            },
        )
        response_data = response.json()
        if "error" in response_data:
            raise RuntimeError(f"RPC Error: {response_data['error']['message']}")
        return response_data["result"]["value"]["blockhash"]

    def update_gas_price_history(self, gas_price: float):
        """
        Update the gas price history with the latest gas price.

        Args:
            gas_price (float): Current gas price in SOL.
        """
        self.gas_price_history.append(gas_price)
        if len(self.gas_price_history) > 25:
            self.gas_price_history.pop(0)

    def get_optimized_gas_price(self) -> float:
        """
        Calculate an optimized gas price based on network conditions and historical averages.

        Returns:
            float: Optimized gas price in SOL.
        """
        current_gas_price = self.fetch_current_gas_price()
        self.update_gas_price_history(current_gas_price)

        # Use historical data if available, otherwise fall back to the default gas price
        if len(self.gas_price_history) > 0:
            average_gas_price = statistics.mean(self.gas_price_history)
            optimized_gas_price = max(self.min_gas_price, min(average_gas_price, self.max_gas_price))
        else:
            optimized_gas_price = self.default_gas_price

        print(f"Optimized Gas Price: {optimized_gas_price:.8f} SOL")
        return optimized_gas_price

    def monitor_network_conditions(self):
        """
        Continuously monitor network conditions and optimize gas fees.
        """
        try:
            while True:
                optimized_gas_price = self.get_optimized_gas_price()
                print(f"Current optimized gas price: {optimized_gas_price:.8f} SOL")
                time.sleep(self.network_poll_interval)
        except KeyboardInterrupt:
            print("Gas Manager stopped.")

