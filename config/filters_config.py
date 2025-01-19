import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging for the module
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FiltersConfig")

class FiltersConfig:
    """Class to define and manage filtering criteria for tokens."""

    # Default filtering criteria
    DEFAULT_CRITERIA = {
        "liquidity_min": 100000,  # Minimum liquidity in USD
        "volume_24h_min": 100000,  # Minimum 24-hour volume in USD
        "gain_24h_min": 0,  # Minimum percentage gain in 24 hours
        "gain_7d_min": 0,  # Minimum percentage gain in 7 days
        "holders_min": 100,  # Minimum number of holders
        "lp_burnt": True,  # Check if LP tokens are burnt
        "minting_allowed": False,  # Disallow tokens with active minting
        "burning_enabled": True,  # Allow tokens with burning mechanisms
        "immutable": True,  # Ensure token contracts are immutable
        "whitelist": [],  # List of token addresses to always include
        "blacklist": [],  # List of token addresses to always exclude
    }

    def __init__(self):
        """Initialize with default criteria, allowing environment variable overrides."""
        self.criteria = self._load_criteria_from_env()

    def _load_criteria_from_env(self):
        """Load criteria from environment variables, falling back to defaults.

        Returns:
            dict: Filtering criteria.
        """
        logger.info("Loading filtering criteria from environment variables.")
        criteria = self.DEFAULT_CRITERIA.copy()
        criteria.update({
            "liquidity_min": int(os.getenv("FILTER_LIQUIDITY_MIN", criteria["liquidity_min"])),
            "volume_24h_min": int(os.getenv("FILTER_VOLUME_24H_MIN", criteria["volume_24h_min"])),
            "gain_24h_min": float(os.getenv("FILTER_GAIN_24H_MIN", criteria["gain_24h_min"])),
            "gain_7d_min": float(os.getenv("FILTER_GAIN_7D_MIN", criteria["gain_7d_min"])),
            "holders_min": int(os.getenv("FILTER_HOLDERS_MIN", criteria["holders_min"])),
            "lp_burnt": os.getenv("FILTER_LP_BURNT", "True").lower() == "true",
            "minting_allowed": os.getenv("FILTER_MINTING_ALLOWED", "False").lower() == "true",
            "burning_enabled": os.getenv("FILTER_BURNING_ENABLED", "True").lower() == "true",
            "immutable": os.getenv("FILTER_IMMUTABLE", "True").lower() == "true",
            "whitelist": os.getenv("FILTER_WHITELIST", "").split(",") if os.getenv("FILTER_WHITELIST") else [],
            "blacklist": os.getenv("FILTER_BLACKLIST", "").split(",") if os.getenv("FILTER_BLACKLIST") else [],
        })
        logger.info(f"Loaded criteria: {criteria}")
        return criteria

    def validate_token(self, token_data):
        """Validate a token against the filtering criteria.

        Args:
            token_data (dict): Token data to validate. Expected keys:
                - liquidity
                - volume_24h
                - gain_24h
                - gain_7d
                - holders
                - lp_burnt
                - minting_allowed
                - burning_enabled
                - immutable
                - address

        Returns:
            bool: True if the token passes all criteria, False otherwise.
        """
        logger.info(f"Validating token: {token_data}")

        # Check whitelist and blacklist
        if token_data["address"] in self.criteria["blacklist"]:
            logger.info(f"Token {token_data['address']} is blacklisted.")
            return False
        if token_data["address"] in self.criteria["whitelist"]:
            logger.info(f"Token {token_data['address']} is whitelisted.")
            return True

        # Validate numeric criteria
        numeric_checks = [
            token_data.get("liquidity", 0) >= self.criteria["liquidity_min"],
            token_data.get("volume_24h", 0) >= self.criteria["volume_24h_min"],
            token_data.get("gain_24h", 0) >= self.criteria["gain_24h_min"],
            token_data.get("gain_7d", 0) >= self.criteria["gain_7d_min"],
            token_data.get("holders", 0) >= self.criteria["holders_min"],
        ]

        # Validate boolean criteria
        boolean_checks = [
            token_data.get("lp_burnt", False) == self.criteria["lp_burnt"],
            token_data.get("minting_allowed", True) == self.criteria["minting_allowed"],
            token_data.get("burning_enabled", False) == self.criteria["burning_enabled"],
            token_data.get("immutable", False) == self.criteria["immutable"],
        ]

        # Combine all checks
        if all(numeric_checks) and all(boolean_checks):
            logger.info(f"Token {token_data['address']} passed validation.")
            return True
        else:
            logger.info(f"Token {token_data['address']} failed validation.")
            return False

if __name__ == "__main__":
    # Example usage of FiltersConfig
    filters = FiltersConfig()

    # Example token data
    token_example = {
        "liquidity": 150000,
        "volume_24h": 200000,
        "gain_24h": 5,
        "gain_7d": 10,
        "holders": 500,
        "lp_burnt": True,
        "minting_allowed": False,
        "burning_enabled": True,
        "immutable": True,
        "address": "0xExampleTokenAddress",
    }

    # Validate token
    is_valid = filters.validate_token(token_example)
    logger.info(f"Is the token valid? {is_valid}")
