import logging
from typing import Dict, Optional, Any, TYPE_CHECKING
import os
from utils.logger import get_logger
from dotenv import load_dotenv
from utils.encryption import encrypt_env_file, get_encryption_password

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Thresholds")

# Import Settings for type hinting only
if TYPE_CHECKING:
    from config.settings import Settings

# Trading Signal Thresholds - Made more sensitive for API price trading
RSI_OVERSOLD = 45  # More sensitive (was 40)
RSI_OVERBOUGHT = 55  # More sensitive (was 60)
ADX_THRESHOLD = 15  # More sensitive (was 20)
MACD_SIGNAL_PERIOD = 7  # Faster signals (was 9)
BOLLINGER_PERIOD = 15  # Faster signals (was 20)

# Volume thresholds - More lenient
MIN_VOLUME_CHANGE_PERCENT = -5.0  # Allow slight volume decreases
VOLUME_SPIKE_THRESHOLD = 1.5  # Lower threshold for volume spikes

# Price movement thresholds - More sensitive
MIN_PRICE_CHANGE_PERCENT = 0.5  # Lower threshold (was 1.0)
PRICE_VOLATILITY_THRESHOLD = 2.0  # Lower threshold (was 3.0)

class Thresholds:
    """Class to manage all trading thresholds and criteria."""
    
    def __init__(self, settings: 'Settings'):
        """Initialize thresholds from environment variables."""
        self.settings = settings
        self.thresholds: Dict[str, Any] = {}
        logger.info("Initializing Thresholds...")
        self._load_thresholds()
        self._validate_thresholds()
        logger.info("Thresholds initialized successfully")
        
    def _load_thresholds(self):
        """Load threshold values from the settings object."""
        logger.debug("Loading thresholds from settings...")
        
        missing_thresholds = []
        loaded_count = 0

        # Automatically discover numeric settings
        for name, val in vars(self.settings).items():
            if isinstance(val, (int, float)):
                self.thresholds[name] = val
                setattr(self, name, val)
                loaded_count += 1
                logger.debug(f"  Loaded threshold {name} = {val}")

        logger.info(f"Loaded {loaded_count} thresholds from settings.")
        
        # Log a single error if any required thresholds were missing
        if missing_thresholds:
            logger.error(f"Missing required threshold(s) in settings: {', '.join(missing_thresholds)}")

    def _validate_thresholds(self):
        """Validate loaded threshold values."""
        logger.debug("Validating loaded thresholds...")
        validation_errors = []
        # Add specific validation rules (e.g., MIN < MAX, positive values)
        # Validation assumes thresholds exist; loading errors handled above.
        
        # Example: Check for positive values where required
        positive_keys = ['MIN_VOLUME_24H', 'MIN_VOLUME_5M', 'MIN_LIQUIDITY', 'MIN_MARKET_CAP', 'MIN_PRICE', 'FRESH_AGE_MAX', 'BBANDS_PERIOD', 'RSI_PERIOD', 'RISK_PER_TRADE']
        for key in positive_keys:
             # Only validate if the key was actually loaded
             if key in self.thresholds:
                 value = self.thresholds.get(key)
                 try:
                     if float(value) <= 0:
                         validation_errors.append(f"Threshold '{key}' ({value}) must be positive.")
                 except (ValueError, TypeError):
                      validation_errors.append(f"Threshold '{key}' ({value}) must be a valid number for positivity check.")
             # else: Logged as missing during load

        # Example: MIN < MAX validation
        min_max_pairs = [
            ('MIN_PRICE', 'MAX_PRICE'),
            ('MIN_LIQUIDITY', 'MAX_LIQUIDITY'),
            ('FRESH_AGE_MIN', 'FRESH_AGE_MAX'),
            ('NEW_AGE_MIN', 'NEW_AGE_MAX'),
            ('FINAL_AGE_MIN', 'FINAL_AGE_MAX')
            # Add other min/max pairs...
        ]
        for min_key, max_key in min_max_pairs:
            # Only validate if both keys were actually loaded
            if min_key in self.thresholds and max_key in self.thresholds:
                min_val = self.thresholds.get(min_key)
                max_val = self.thresholds.get(max_key)
                try:
                    f_min_val = float(min_val)
                    f_max_val = float(max_val)
                    if f_min_val >= f_max_val:
                        validation_errors.append(f"{min_key} ({min_val}) must be less than {max_key} ({max_val}).")
                except (ValueError, TypeError):
                     validation_errors.append(f"Thresholds '{min_key}' ({min_val}) and '{max_key}' ({max_val}) must be valid numbers for comparison.")
            # else: Logged as missing during load

        # ... add more specific validations, checking if key in self.thresholds first ...

        if validation_errors:
            logger.error("Threshold validation failed:")

    def display_thresholds(self):
        """Log the loaded threshold values."""
        logger.info("Current Threshold Settings:")
        if not self.thresholds:
            logger.info("  No thresholds loaded.")
            return
        # Sort keys for consistent output
        for key in sorted(self.thresholds.keys()):
            # Avoid logging potentially sensitive values if any exist here
            logger.info(f"  {key}: {self.thresholds[key]}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a threshold value by key."""
        return self.thresholds.get(key, default)

    def get_all_thresholds(self) -> dict:
        """Get all thresholds as a dictionary."""
        return self.thresholds
                
    def save_thresholds(self, thresholds: Dict[str, str]) -> None:
        """Save thresholds to environment variables."""
        for key, value in thresholds.items():
            os.environ[key] = value
        logger.info("Thresholds saved to environment variables")


