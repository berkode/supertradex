import logging
import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.getenv("LOG_FILE", "filtering.log")),
        logging.StreamHandler() if os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true" else None
    ]
)


class Filtering:
    def __init__(self):
        self.dex_screener_api = os.getenv("DEX_SCREENER_API_BASE_URL", "https://api.dexscreener.com")
        self.rug_threshold = float(os.getenv("RUG_THRESHOLD", 0.7))  # Threshold to classify as a rug pull
        self.min_liquidity = float(os.getenv("MIN_LIQUIDITY", 10000))  # Minimum liquidity for token selection
        self.min_volume = float(os.getenv("MIN_VOLUME", 10000))  # Minimum 24h volume for token selection

    def fetch_token_data(self, token_address: str) -> dict:
        """
        Fetch token data from DexScreener.

        Args:
            token_address (str): Token mint address.

        Returns:
            dict: Token data.
        """
        try:
            url = f"{self.dex_screener_api}/latest/dex/pairs/solana/{token_address}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            pairs = data.get("pairs", [])
            if not pairs:
                logging.warning(f"No data found for token: {token_address}")
                return {}

            logging.info(f"Fetched token data for {token_address}")
            return pairs[0]
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error while fetching data for token {token_address}: {e}")
            return {}
        except Exception as e:
            logging.error(f"Unexpected error while fetching data for token {token_address}: {e}")
            return {}

    def calculate_rugpull_score(self, token_data: dict) -> float:
        """
        Calculate a rugpull score based on liquidity, distribution, trading, smart contract, and market metrics.

        Args:
            token_data (dict): Token data from DexScreener.

        Returns:
            float: Rugpull score (0.0 - 1.0).
        """
        score = 0
        total_weight = 10  # Total weight for normalization

        # 1. Liquidity Metrics
        liquidity = float(token_data.get("liquidity", {}).get("usd", 0.0))
        locked_liquidity = float(token_data.get("liquidity", {}).get("locked", 0.0))
        liquidity_score = 1 if liquidity < 10000 or locked_liquidity < 50 else 0
        score += liquidity_score

        # 2. Token Distribution
        holder_concentration = token_data.get("distribution", {}).get("topHoldersPercent", 0.0)
        distribution_score = 1 if holder_concentration > 50 else 0
        score += distribution_score

        # 3. Trading Activity
        buy_sell_ratio = token_data.get("volume", {}).get("buySellRatio", 1.0)
        trading_score = 1 if buy_sell_ratio < 0.5 else 0
        score += trading_score

        # 4. Smart Contract Metrics
        is_audited = token_data.get("contract", {}).get("audited", False)
        blacklist_functions = token_data.get("contract", {}).get("blacklistFunctions", False)
        smart_contract_score = 1 if not is_audited or blacklist_functions else 0
        score += smart_contract_score

        # 5. Market Metrics
        market_cap = float(token_data.get("marketCap", 0.0))
        fdv = float(token_data.get("fdv", 0.0))
        market_score = 1 if (market_cap / liquidity > 10 or fdv / market_cap > 2) else 0
        score += market_score

        rugpull_score = round(score / total_weight, 2)
        logging.info(f"Calculated rugpull score: {rugpull_score}")
        return rugpull_score

    def apply_standard_filters(self, token_data: dict) -> bool:
        """
        Apply standard filtering metrics to a token.

        Args:
            token_data (dict): Token data from DexScreener.

        Returns:
            bool: True if the token passes the filters, False otherwise.
        """
        liquidity = float(token_data.get("liquidity", {}).get("usd", 0.0))
        volume_24h = float(token_data.get("volume", {}).get("usd", 0.0))

        if liquidity < self.min_liquidity:
            logging.info(f"Token failed liquidity filter: {liquidity} < {self.min_liquidity}")
            return False

        if volume_24h < self.min_volume:
            logging.info(f"Token failed volume filter: {volume_24h} < {self.min_volume}")
            return False

        return True

    def apply_filters(self, token_address: str) -> dict:
        """
        Apply both rugpull and standard filters to a token.

        Args:
            token_address (str): Token mint address.

        Returns:
            dict: Token data with rugpull score, filter results, and selection status.
        """
        token_data = self.fetch_token_data(token_address)

        if not token_data:
            logging.warning(f"No data available for token: {token_address}")
            return {"token_address": token_address, "rugpull_score": 1.0, "selected": False}

        rugpull_score = self.calculate_rugpull_score(token_data)
        passes_standard_filters = self.apply_standard_filters(token_data)
        selected = rugpull_score < self.rug_threshold and passes_standard_filters

        return {
            "token_address": token_address,
            "rugpull_score": rugpull_score,
            "selected": selected,
            "liquidity_usd": token_data.get("liquidity", {}).get("usd", 0.0),
            "volume_24h_usd": token_data.get("volume", {}).get("usd", 0.0),
            "market_cap_usd": token_data.get("marketCap", 0.0)
        }

