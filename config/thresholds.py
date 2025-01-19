import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Thresholds")

class Thresholds:
    """Class to define and manage trading thresholds."""

    # Trading thresholds with default values
    MIN_VOLUME = float(os.getenv("MIN_VOLUME", 1000))  # Minimum trading volume in USD
    MAX_VOLUME = float(os.getenv("MAX_VOLUME", 1_000_000))  # Maximum trading volume in USD
    MIN_PRICE = float(os.getenv("MIN_PRICE", 0.01))  # Minimum price of a token in USD
    MAX_PRICE = float(os.getenv("MAX_PRICE", 1000))  # Maximum price of a token in USD
    MAX_GAS_FEE = float(os.getenv("MAX_GAS_FEE", 50))  # Maximum acceptable gas fee in USD
    MIN_LIQUIDITY = float(os.getenv("MIN_LIQUIDITY", 10_000))  # Minimum liquidity in USD
    MAX_LIQUIDITY = float(os.getenv("MAX_LIQUIDITY", 1_000_000))  # Maximum liquidity in USD
    MIN_HOLDERS = int(os.getenv("MIN_HOLDERS", 100))  # Minimum number of token holders
    MAX_SLIPPAGE = float(os.getenv("MAX_SLIPPAGE", 0.01))  # Maximum slippage (1% default)
    MAX_SPREAD = float(os.getenv("MAX_SPREAD", 0.02))  # Maximum spread (2% default)

    @classmethod
    def validate_thresholds(cls):
        """Validate trading thresholds to ensure they are configured correctly."""
        logger.info("Validating thresholds...")
        errors = []

        threshold_checks = {
            "MIN_VOLUME": cls.MIN_VOLUME > 0,
            "MAX_VOLUME": cls.MAX_VOLUME > cls.MIN_VOLUME,
            "MIN_PRICE": cls.MIN_PRICE > 0,
            "MAX_PRICE": cls.MAX_PRICE > cls.MIN_PRICE,
            "MAX_GAS_FEE": cls.MAX_GAS_FEE > 0,
            "MIN_LIQUIDITY": cls.MIN_LIQUIDITY > 0,
            "MAX_LIQUIDITY": cls.MAX_LIQUIDITY > cls.MIN_LIQUIDITY,
            "MIN_HOLDERS": cls.MIN_HOLDERS > 0,
            "MAX_SLIPPAGE": 0 <= cls.MAX_SLIPPAGE <= 0.05,
            "MAX_SPREAD": 0 <= cls.MAX_SPREAD <= 0.1,
        }

        for key, is_valid in threshold_checks.items():
            if not is_valid:
                errors.append(f"Invalid {key}: {getattr(cls, key)}")

        if errors:
            for error in errors:
                logger.error(error)
            raise ValueError("Threshold validation failed. Check logs for details.")

        logger.info("All thresholds validated successfully.")

    @classmethod
    def update_threshold(cls, key, value):
        """Update a specific threshold dynamically.

        Args:
            key (str): The threshold key to update.
            value (any): The new value for the threshold.

        Raises:
            KeyError: If the key is not a valid threshold.
            ValueError: If the new value is invalid for the key.
        """
        if not hasattr(cls, key):
            raise KeyError(f"Invalid threshold key: {key}")

        try:
            value_type = type(getattr(cls, key))
            setattr(cls, key, value_type(value))
            logger.info(f"Threshold updated: {key} = {value_type(value)}")
            cls.validate_thresholds()  # Re-validate after update
        except Exception as e:
            raise ValueError(f"Failed to update threshold {key}: {e}")

    @classmethod
    def display_thresholds(cls):
        """Log the current thresholds for debugging purposes."""
        logger.info("Current Trading Thresholds:")
        for attribute in dir(cls):
            if not attribute.startswith("__") and not callable(getattr(cls, attribute)):
                logger.info(f"{attribute}: {getattr(cls, attribute)}")


