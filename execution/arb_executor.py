import logging
import os
from typing import Dict, Optional, Tuple
import requests
from dotenv import load_dotenv
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

# Load environment variables from .env
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ArbExecutor")

class ArbExecutor:
    """
    Class to execute arbitrage opportunities across supported markets.
    """
    def __init__(self):
        """
        Initialize the ArbExecutor with environment configurations.
        """
        self.raydium_api_url = os.getenv("RAYDIUM_API_URL", "https://api.raydium.io/v1/orders")
        self.wallet_address = os.getenv("WALLET_ADDRESS")
        self.private_key_hex = os.getenv("PRIVATE_KEY")  # Hex-encoded private key
        self.slippage_tolerance = float(os.getenv("SLIPPAGE_TOLERANCE", 0.5))  # Default: 0.5%
        self.default_gas_limit = int(os.getenv("DEFAULT_GAS_LIMIT", 200000))
        self.arbitrage_threshold = float(os.getenv("ARBITRAGE_THRESHOLD", 0.2))  # Minimum profit threshold in %
        logger.info("ArbExecutor initialized for wallet: %s", self.wallet_address)

        # Ensure wallet and private key are set
        if not self.wallet_address or not self.private_key_hex:
            logger.error("WALLET_ADDRESS and PRIVATE_KEY must be set in the .env file.")
            raise ValueError("WALLET_ADDRESS and PRIVATE_KEY are required for ArbExecutor.")

        # Load signing key
        self.signing_key = SigningKey(self.private_key_hex, encoder=HexEncoder)

    def _sign_transaction(self, payload: Dict) -> Dict:
        """
        Sign the transaction payload using the private key.

        Args:
            payload (Dict): The transaction data.

        Returns:
            Dict: The signed transaction.
        """
        try:
            # Convert the payload to a string and encode it
            payload_str = str(payload).encode('utf-8')

            # Generate the signature
            signature = self.signing_key.sign(payload_str).signature.hex()

            # Add the signature to the payload
            payload["signature"] = signature
            logger.debug("Transaction signed for payload: %s", payload)
            return payload
        except Exception as e:
            logger.error("Failed to sign transaction: %s", str(e))
            raise

    def _calculate_arbitrage_profit(self, buy_price: float, sell_price: float, fees: float = 0.003) -> float:
        """
        Calculate arbitrage profit after accounting for fees.

        Args:
            buy_price (float): Price to buy the asset.
            sell_price (float): Price to sell the asset.
            fees (float): Total trading fees as a percentage (default 0.3%).

        Returns:
            float: Net profit percentage.
        """
        gross_profit = (sell_price - buy_price) / buy_price * 100
        net_profit = gross_profit - (fees * 100)
        logger.debug(
            "Arbitrage profit calculation: buy_price=%.4f, sell_price=%.4f, gross_profit=%.2f%%, net_profit=%.2f%%",
            buy_price, sell_price, gross_profit, net_profit
        )
        return net_profit

    def execute_arbitrage(
        self, buy_market: str, sell_market: str, buy_price: float, sell_price: float, quantity: float
    ) -> bool:
        """
        Execute an arbitrage trade if the profit meets the threshold.

        Args:
            buy_market (str): Market symbol to buy the asset (e.g., "SOL/USDC").
            sell_market (str): Market symbol to sell the asset (e.g., "SOL/USDT").
            buy_price (float): Price to buy the asset.
            sell_price (float): Price to sell the asset.
            quantity (float): Quantity to trade.

        Returns:
            bool: True if arbitrage was executed, False otherwise.
        """
        logger.info(
            "Evaluating arbitrage opportunity: buy_market=%s, sell_market=%s, buy_price=%.4f, sell_price=%.4f, quantity=%.4f",
            buy_market, sell_market, buy_price, sell_price, quantity
        )

        # Calculate potential arbitrage profit
        profit = self._calculate_arbitrage_profit(buy_price, sell_price)
        if profit < self.arbitrage_threshold:
            logger.info(
                "Arbitrage opportunity skipped: Net profit (%.2f%%) below threshold (%.2f%%).",
                profit, self.arbitrage_threshold
            )
            return False

        try:
            # Place buy order
            buy_payload = {
                "market": buy_market,
                "side": "buy",
                "price": buy_price,
                "quantity": quantity,
                "wallet": self.wallet_address,
                "slippage_tolerance": self.slippage_tolerance,
                "gas_limit": self.default_gas_limit,
            }
            signed_buy_payload = self._sign_transaction(buy_payload)
            buy_response = requests.post(f"{self.raydium_api_url}/place", json=signed_buy_payload)
            buy_response.raise_for_status()
            logger.info("Buy order placed successfully: %s", buy_response.json())

            # Place sell order
            sell_payload = {
                "market": sell_market,
                "side": "sell",
                "price": sell_price,
                "quantity": quantity,
                "wallet": self.wallet_address,
                "slippage_tolerance": self.slippage_tolerance,
                "gas_limit": self.default_gas_limit,
            }
            signed_sell_payload = self._sign_transaction(sell_payload)
            sell_response = requests.post(f"{self.raydium_api_url}/place", json=signed_sell_payload)
            sell_response.raise_for_status()
            logger.info("Sell order placed successfully: %s", sell_response.json())

            logger.info(
                "Arbitrage executed successfully: buy_market=%s, sell_market=%s, profit=%.2f%%",
                buy_market, sell_market, profit
            )
            return True
        except requests.RequestException as e:
            logger.error("Failed to execute arbitrage: %s", str(e))
            return False

    def monitor_and_execute_arbitrage(self, opportunities: Dict[str, Tuple[str, float, float, float]]):
        """
        Monitor and execute arbitrage opportunities.

        Args:
            opportunities (Dict[str, Tuple[str, float, float, float]]): 
                Dictionary of opportunities where key is the opportunity name and value is a tuple:
                (sell_market, buy_price, sell_price, quantity).
        """
        for opportunity, details in opportunities.items():
            buy_market, sell_market, buy_price, sell_price, quantity = details
            logger.info("Monitoring opportunity: %s", opportunity)
            self.execute_arbitrage(buy_market, sell_market, buy_price, sell_price, quantity)

