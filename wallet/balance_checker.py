import os
import logging
from solana.publickey import PublicKey
from solana.rpc.api import Client
from dotenv import load_dotenv
import requests

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("balance_checker.log"),
        logging.StreamHandler()
    ]
)


class BalanceChecker:
    def __init__(self):
        self.rpc_endpoint = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.client = Client(self.rpc_endpoint)
        self.wallet_address = os.getenv("WALLET_ADDRESS")
        self.dex_screener_api = os.getenv("DEX_SCREENER_API_BASE_URL", "https://api.dexscreener.com")
        self.sol_price_api = os.getenv("SOL_PRICE_API", "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")

        if not self.wallet_address:
            raise ValueError("WALLET_ADDRESS must be set in the .env file.")

    def fetch_sol_price(self) -> float:
        """
        Fetch the current price of SOL in USD.

        Returns:
            float: Price of SOL in USD.
        """
        try:
            response = requests.get(self.sol_price_api)
            response.raise_for_status()
            data = response.json()
            sol_price = data["solana"]["usd"]
            logging.info(f"Fetched SOL price: ${sol_price}")
            return sol_price
        except Exception as e:
            logging.error(f"Error fetching SOL price: {e}")
            return 0.0

    def fetch_token_metadata_from_dexscreener(self, token_address: str) -> dict:
        """
        Fetch token metadata (price, symbol, name) from DexScreener.

        Args:
            token_address (str): Token mint address.

        Returns:
            dict: Token metadata including price, symbol, and name.
        """
        try:
            url = f"{self.dex_screener_api}/latest/dex/pairs/solana/{token_address}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            pairs = data.get("pairs", [])
            if not pairs:
                logging.warning(f"No price data found for token: {token_address}")
                return {"priceUsd": 0.0, "symbol": "UNKNOWN", "name": "Unknown Token"}

            pair_data = pairs[0]
            metadata = {
                "priceUsd": float(pair_data.get("priceUsd", 0.0)),
                "symbol": pair_data.get("baseToken", {}).get("symbol", "UNKNOWN"),
                "name": pair_data.get("baseToken", {}).get("name", "Unknown Token")
            }
            logging.info(f"Fetched metadata for token {token_address}: {metadata}")
            return metadata
        except Exception as e:
            logging.error(f"Error fetching metadata for token {token_address}: {e}")
            return {"priceUsd": 0.0, "symbol": "UNKNOWN", "name": "Unknown Token"}

    def get_sol_balance(self) -> float:
        """
        Get the SOL balance of the wallet.

        Returns:
            float: SOL balance of the wallet.
        """
        try:
            balance = self.client.get_balance(PublicKey(self.wallet_address))
            sol_balance = balance["result"]["value"] / 10**9  # Convert lamports to SOL
            logging.info(f"Fetched SOL balance: {sol_balance} SOL")
            return sol_balance
        except Exception as e:
            logging.error(f"Error fetching SOL balance: {e}")
            return 0.0

    def get_token_balances(self) -> dict:
        """
        Fetch token balances for the wallet.

        Returns:
            dict: A dictionary with token addresses as keys and balances as values in token units.
        """
        try:
            response = self.client.get_token_accounts_by_owner(
                PublicKey(self.wallet_address),
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}
            )
            token_balances = {}
            for account in response["result"]["value"]:
                token_address = account["account"]["data"]["parsed"]["info"]["mint"]
                balance = account["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
                token_balances[token_address] = balance
            logging.info(f"Fetched token balances: {token_balances}")
            return token_balances
        except Exception as e:
            logging.error(f"Error fetching token balances: {e}")
            return {}

    def calculate_total_holdings(self) -> dict:
        """
        Calculate total holdings in SOL and USD, including individual token holdings.

        Returns:
            dict: A dictionary with total holdings in SOL, USD, and per-token holdings.
        """
        sol_balance = self.get_sol_balance()
        sol_price = self.fetch_sol_price()
        token_balances = self.get_token_balances()

        total_holdings_in_sol = sol_balance
        total_holdings_in_usd = sol_balance * sol_price
        individual_holdings = {}

        for token_address, token_balance in token_balances.items():
            token_metadata = self.fetch_token_metadata_from_dexscreener(token_address)
            token_price_usd = token_metadata.get("priceUsd", 0.0)
            token_symbol = token_metadata.get("symbol", "UNKNOWN")
            token_name = token_metadata.get("name", "Unknown Token")

            token_value_in_usd = token_balance * token_price_usd
            token_value_in_sol = token_value_in_usd / sol_price if sol_price > 0 else 0.0

            individual_holdings[token_address] = {
                "symbol": token_symbol,
                "name": token_name,
                "balance": token_balance,
                "value_in_sol": token_value_in_sol,
                "value_in_usd": token_value_in_usd
            }

            total_holdings_in_sol += token_value_in_sol
            total_holdings_in_usd += token_value_in_usd

        logging.info(f"Total holdings calculated: {total_holdings_in_usd} USD, {total_holdings_in_sol} SOL")
        return {
            "total_holdings_in_sol": total_holdings_in_sol,
            "total_holdings_in_usd": total_holdings_in_usd,
            "individual_holdings": individual_holdings
        }
