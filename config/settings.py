import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Settings")

class Settings:
    """Class to manage global settings for the trading system."""

    # Risk and trade management
    RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", 0.01))  # Default: 1% of account balance per trade
    SLIPPAGE_TOLERANCE = float(os.getenv("SLIPPAGE_TOLERANCE", 0.005))  # Default: 0.5% slippage tolerance
    TRADE_SIZE = float(os.getenv("TRADE_SIZE", 100))  # Default: $100 per trade
    
    # Strategy-specific Gain Targets and Max Position Loss
    BREAKOUT_POSITION_GAIN_TARGET = float(os.getenv("BREAKOUT_POSITION_GAIN_TARGET", 0.02))  # 2%
    TREND_FOLLOWING_POSITION_GAIN_TARGET = float(os.getenv("TREND_FOLLOWING_POSITION_GAIN_TARGET", 0.02))  # 2%
    MEAN_REVERSION_POSITION_GAIN_TARGET = float(os.getenv("MEAN_REVERSION_POSITION_GAIN_TARGET", 0.02))  # 2%
    MOMENTUM_STRATEGY_POSITION_GAIN_TARGET = float(os.getenv("MOMENTUM_STRATEGY_POSITION_GAIN_TARGET", 0.02))  # 2%
    BUYING_ON_UNTOUCHED_SUPPORT_POSITION_GAIN_TARGET = float(os.getenv("BUYING_ON_UNTOUCHED_SUPPORT_POSITION_GAIN_TARGET", 0.02))  # 2%
    SNIPING_NEW_MEME_COINS_POSITION_GAIN_TARGET = float(os.getenv("SNIPING_NEW_MEME_COINS_POSITION_GAIN_TARGET", 0.02))  # 2%
    COPY_TRADING_POSITION_GAIN_TARGET = float(os.getenv("COPY_TRADING_POSITION_GAIN_TARGET", 0.02))  # 2%

    # Strategy-specific Max Position Loss
    BREAKOUT_MAX_POSITION_LOSS = float(os.getenv("BREAKOUT_MAX_POSITION_LOSS", -0.02))  # -2%
    TREND_FOLLOWING_MAX_POSITION_LOSS = float(os.getenv("TREND_FOLLOWING_MAX_POSITION_LOSS", -0.02))  # -2%
    MEAN_REVERSION_MAX_POSITION_LOSS = float(os.getenv("MEAN_REVERSION_MAX_POSITION_LOSS", -0.02))  # -2%
    MOMENTUM_STRATEGY_MAX_POSITION_LOSS = float(os.getenv("MOMENTUM_STRATEGY_MAX_POSITION_LOSS", -0.02))  # -2%
    BUYING_ON_UNTOUCHED_SUPPORT_MAX_POSITION_LOSS = float(os.getenv("BUYING_ON_UNTOUCHED_SUPPORT_MAX_POSITION_LOSS", -0.02))  # -2%
    SNIPING_NEW_MEME_COINS_MAX_POSITION_LOSS = float(os.getenv("SNIPING_NEW_MEME_COINS_MAX_POSITION_LOSS", -0.02))  # -2%
    COPY_TRADING_MAX_POSITION_LOSS = float(os.getenv("COPY_TRADING_MAX_POSITION_LOSS", -0.02))  # -2%

    # Maximum Token Trades at a Time
    MAX_TOKEN_TRADES = int(os.getenv("MAX_TOKEN_TRADES", 5))  # Default: Max 5 tokens traded at a time

    # Maximum Active Trades
    MAX_TRADES = int(os.getenv("MAX_TRADES", 20))  # Default: Max 20 trades active at a time

    # Logging and notifications
    ENABLE_NOTIFICATIONS = os.getenv("ENABLE_NOTIFICATIONS", "False").lower() == "true"  # Notifications for critical events

    # Additional settings
    BASE_CURRENCY = os.getenv("BASE_CURRENCY", "USD")  # Default base currency
    DEFAULT_LEVERAGE = float(os.getenv("DEFAULT_LEVERAGE", 1))  # Default leverage for trades (1x = no leverage)

    # Safety limits
    DAILY_MAX_RISK = float(os.getenv("DAILY_MAX_RISK", 0.1))  # Default: 10% daily risk
    WEEKLY_MAX_RISK = float(os.getenv("WEEKLY_MAX_RISK", 0.2))  # Default: 20% weekly risk

    @classmethod
    def validate_settings(cls):
        """Validate critical settings and raise errors for misconfigurations."""
        logger.info("Validating settings...")
        errors = []

        if not (0 < cls.RISK_PER_TRADE <= 0.05):  # Risk per trade should be between 0 and 5% of balance
            errors.append(f"Invalid RISK_PER_TRADE: {cls.RISK_PER_TRADE}. Must be between 0 and 0.05.")

        if cls.SLIPPAGE_TOLERANCE <= 0 or cls.SLIPPAGE_TOLERANCE > 0.02:  # Slippage tolerance should be sensible
            errors.append(f"Invalid SLIPPAGE_TOLERANCE: {cls.SLIPPAGE_TOLERANCE}. Must be between 0 and 0.02.")

        if cls.TRADE_SIZE <= 0:  # Trade size should be positive
            errors.append(f"Invalid TRADE_SIZE: {cls.TRADE_SIZE}. Must be a positive value.")

        if cls.MAX_LOSS > 0:  # Maximum loss should be negative or zero
            errors.append(f"Invalid MAX_LOSS: {cls.MAX_LOSS}. Must be zero or negative.")

        if cls.MAX_TOKEN_TRADES <= 0 or cls.MAX_TRADES <= 0:  # Trade limits must be positive
            errors.append("MAX_TOKEN_TRADES and MAX_TRADES must be positive integers.")

        if cls.DEFAULT_LEVERAGE < 1:  # Leverage should be at least 1x
            errors.append(f"Invalid DEFAULT_LEVERAGE: {cls.DEFAULT_LEVERAGE}. Must be at least 1.")

        if not (0 < cls.DAILY_MAX_RISK <= 1):  # Daily risk must be between 0 and 100%
            errors.append(f"Invalid DAILY_MAX_RISK: {cls.DAILY_MAX_RISK}. Must be between 0 and 1.")

        if not (0 < cls.WEEKLY_MAX_RISK <= 1):  # Weekly risk must be between 0 and 100%
            errors.append(f"Invalid WEEKLY_MAX_RISK: {cls.WEEKLY_MAX_RISK}. Must be between 0 and 1.")

        if errors:
            for error in errors:
                logger.error(error)
            raise ValueError("Invalid settings configuration. Check logs for details.")
        logger.info("All settings validated successfully.")

    @classmethod
    def display_settings(cls):
        """Log the current settings for debugging purposes."""
        logger.info("Global Trading System Settings:")
        for attribute in dir(cls):
            if not attribute.startswith("__") and not callable(getattr(cls, attribute)):
                logger.info(f"{attribute}: {getattr(cls, attribute)}")

