import os
import logging
from utils.logger import get_logger
from config.settings import Settings
from config.thresholds import Thresholds
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FiltersConfig")

class FiltersConfig:
    """Class to define and manage filtering criteria for tokens."""

    def __init__(self, settings: Optional[Settings] = None, thresholds: Optional[Thresholds] = None):
        self.logger = get_logger("FiltersConfig")
        self.settings = settings or Settings()
        if thresholds is None:
            self.logger.error("FiltersConfig initialized without a Thresholds instance! Filters might not work correctly.")
            self.thresholds = thresholds
        else:
            self.thresholds = thresholds
        self.criteria = self._load_criteria()

    def _load_criteria(self) -> dict:
        """
        Load filter criteria from configuration classes
        """
        try:
            return {
                'min_volume': self.thresholds.MIN_VOLUME_24H,
                'min_liquidity': self.thresholds.MIN_LIQUIDITY,
                'max_rugcheck_score': getattr(self.settings, 'MAX_RUGCHECK_SCORE', 55),
                'min_solsniffer_score': getattr(self.settings, 'MIN_SOLSNIFFER_SCORE', 61),
                'whitelist': set()  # Initialize empty whitelist
            }
        except AttributeError as e:
            self.logger.error(f"AttributeError loading filter criteria: {e}. Check Thresholds/Settings definitions.")
            return {}
        except Exception as e:
            self.logger.error(f"Error loading filter criteria: {e}")
            return {}

    def validate(self) -> bool:
        """
        Validate the filter configuration.
        
        Returns:
            bool: True if validation passes, False otherwise
        """
        try:
            self.logger.info("Validating filter configuration...")
            
            # Check if criteria is loaded
            if not self.criteria:
                self.logger.error("No filter criteria loaded")
                return False
                
            # Validate required thresholds
            required_thresholds = [
                'min_volume',
                'min_liquidity',
                'max_rugcheck_score',
                'min_solsniffer_score'
            ]
            
            for threshold in required_thresholds:
                if threshold not in self.criteria:
                    self.logger.error(f"Missing required threshold: {threshold}")
                    return False
                if not isinstance(self.criteria[threshold], (int, float)):
                    self.logger.error(f"Invalid threshold type for {threshold}: {type(self.criteria[threshold])}")
                    return False
                if self.criteria[threshold] <= 0:
                    self.logger.error(f"Invalid threshold value for {threshold}: {self.criteria[threshold]}")
                    return False
                    
            self.logger.info("Filter configuration validated successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating filter configuration: {e}")
            return False

    def _safe_float(self, value, default=0.0):
        """Safely convert value to float."""
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            logger.warning(f"Could not convert {value} to float, using default {default}")
            return default

    def _safe_int(self, value, default=0):
        """Safely convert value to integer."""
        try:
            return int(value) if value is not None else default
        except (ValueError, TypeError):
            logger.warning(f"Could not convert {value} to integer, using default {default}")
            return default

    def validate_token(self, token_data: dict) -> bool:
        """
        Validates if a token meets the filtering criteria
        
        Args:
            token_data: Dictionary containing token information
        Returns:
            bool indicating if token passes validation
        """
        try:
            # Check required fields
            required_fields = ['mint', 'symbol', 'volume24h', 'marketCap']
            if not all(field in token_data for field in required_fields):
                self.logger.debug(f"Token missing required fields: {token_data.get('mint', 'Unknown')}")
                return False

            # Apply filter criteria
            if not self.criteria:
                self.logger.warning("No filter criteria available")
                return False

            # Volume check
            if token_data['volume24h'] < self.criteria.get('min_volume', 0):
                return False
                
            # Market cap check
            if token_data['marketCap'] < self.criteria.get('min_market_cap', 0):
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating token: {e}")
            return False

if __name__ == "__main__":
    # Example usage of FiltersConfig
    filters = FiltersConfig()

    # Example token data
    token_example = {
        "mint": "ExampleTokenMint",
        "symbol": "ETK",
        "volume24h": 200000,
        "marketCap": 500000,
        "liquidity": 150000,
        "gain_24h": 5,
        "gain_7d": 10,
        "holders": 500,
        "lp_burnt": True,
        "minting_allowed": False,
        "burning_enabled": True,
        "immutable": True,
    }

    # Validate token
    is_valid = filters.validate_token(token_example)
    logger.info(f"Is the token valid? {is_valid}")
