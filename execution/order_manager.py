import logging
import os
from typing import Optional, Dict
import requests
from dotenv import load_dotenv
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

# Load environment variables from .env
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("OrderManager")


class OrderManager:
    """
    Class to manage orders (place, cancel, modify) on Raydium, supporting market symbols and token addresses.
    """
    def __init__(self):
        """
        Initialize the OrderManager with environment configurations.
        """
        self.raydium_api_url = os.getenv("RAYDIUM_API_URL", "https://api.raydium.io/v1/orders")
        self.wallet_address = os.getenv("WALLET_ADDRESS")
        self.private_key_hex = os.getenv("PRIVATE_KEY")  # Hex-encoded private key
        self.slippage_tolerance = float(os.getenv("SLIPPAGE_TOLERANCE", 0.5))  # Default: 0.5%
        self.default_gas_limit = int(os.getenv("DEFAULT_GAS_LIMIT", 200000))

        # Load the private key for signing
        if not self.wallet_address or not self.private_key_hex:
            logger.error("WALLET_ADDRESS and PRIVATE_KEY must be set in the .env file.")
            raise ValueError("WALLET_ADDRESS and PRIVATE_KEY are required for OrderManager.")
        
        self.signing_key = SigningKey(self.private_key_hex, encoder=HexEncoder)
        logger.info("OrderManager initialized for wallet: %s", self.wallet_address)

    def _sign_transaction(self, payload: Dict) -> Dict:
        """
        Sign the transaction payload using the private key.

        Args:
            payload (Dict): The transaction data.

        Returns:
            Dict: The signed transaction.
        """
        try:
            payload_str = str(payload).encode('utf-8')
            signature = self.signing_key.sign(payload_str).signature.hex()
            payload["signature"] = signature
            logger.debug("Transaction signed for payload: %s", payload)
            return payload
        except Exception as e:
            logger.error("Failed to sign transaction: %s", str(e))
            raise

    def place_order(
        self, market: Optional[str], side: str, price: float, quantity: float, token_address: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Place a new order on Raydium, supporting market symbols or token addresses.

        Args:
            market (Optional[str]): Market symbol (e.g., "SOL/USDC"). Use None if token_address is specified.
            side (str): Order side ("buy" or "sell").
            price (float): Price at which to place the order.
            quantity (float): Quantity to trade.
            token_address (Optional[str]): Token address for direct trades.

        Returns:
            Optional[Dict]: API response if successful, None otherwise.
        """
        if not market and not token_address:
            logger.error("Either market or token_address must be specified to place an order.")
            return None

        logger.info("Placing order: market=%s, token_address=%s, side=%s, price=%.2f, quantity=%.4f",
                    market, token_address, side, price, quantity)
        try:
            order_payload = {
                "market": market,
                "token_address": token_address,
                "side": side,
                "price": price,
                "quantity": quantity,
                "wallet": self.wallet_address,
                "slippage_tolerance": self.slippage_tolerance,
                "gas_limit": self.default_gas_limit,
            }

            # Filter out None values for unused fields
            order_payload = {k: v for k, v in order_payload.items() if v is not None}

            # Sign the transaction
            signed_payload = self._sign_transaction(order_payload)

            # Send the order request
            response = requests.post(f"{self.raydium_api_url}/place", json=signed_payload)
            response.raise_for_status()

            logger.info("Order placed successfully. Response: %s", response.json())
            return response.json()
        except requests.RequestException as e:
            logger.error("Failed to place order: %s", str(e))
            return None

    def cancel_order(self, order_id: str) -> Optional[Dict]:
        """
        Cancel an existing order on Raydium.

        Args:
            order_id (str): The unique ID of the order to cancel.

        Returns:
            Optional[Dict]: API response if successful, None otherwise.
        """
        logger.info("Canceling order with ID: %s", order_id)
        try:
            cancel_payload = {"order_id": order_id, "wallet": self.wallet_address}

            # Sign the transaction
            signed_payload = self._sign_transaction(cancel_payload)

            # Send the cancel request
            response = requests.post(f"{self.raydium_api_url}/cancel", json=signed_payload)
            response.raise_for_status()

            logger.info("Order canceled successfully. Response: %s", response.json())
            return response.json()
        except requests.RequestException as e:
            logger.error("Failed to cancel order: %s", str(e))
            return None

    def modify_order(self, order_id: str, price: Optional[float] = None, quantity: Optional[float] = None) -> Optional[Dict]:
        """
        Modify an existing order on Raydium.

        Args:
            order_id (str): The unique ID of the order to modify.
            price (Optional[float]): New price for the order (if modifying price).
            quantity (Optional[float]): New quantity for the order (if modifying quantity).

        Returns:
            Optional[Dict]: API response if successful, None otherwise.
        """
        logger.info("Modifying order with ID: %s, price=%.2f, quantity=%.4f", order_id, price or 0, quantity or 0)
        try:
            modify_payload = {
                "order_id": order_id,
                "wallet": self.wallet_address,
                "price": price,
                "quantity": quantity,
            }

            # Filter out None values
            modify_payload = {k: v for k, v in modify_payload.items() if v is not None}

            # Sign the transaction
            signed_payload = self._sign_transaction(modify_payload)

            # Send the modify request
            response = requests.post(f"{self.raydium_api_url}/modify", json=signed_payload)
            response.raise_for_status()

            logger.info("Order modified successfully. Response: %s", response.json())
            return response.json()
        except requests.RequestException as e:
            logger.error("Failed to modify order: %s", str(e))
            return None


