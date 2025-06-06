import os
import logging
from typing import Dict
from config.settings import Settings

logger = logging.getLogger("Config")

class TwitterConfig:
    """Class to manage Twitter API configuration and thresholds."""
    
    def __init__(self, settings: Settings):
        # Twitter API credentials from Settings object
        self.credentials = {
            "username": settings.TWITTER_USER,
            "email": settings.TWITTER_EMAIL,
            "password": settings.TWITTER_PASSWORD
        }
        
        # Twitter follower thresholds by token status
        self.follower_thresholds = {
            "FRESH": int(os.getenv("TWITTER_FRESH_MIN_FOLLOWERS", 1)),
            "NEW": int(os.getenv("TWITTER_NEW_MIN_FOLLOWERS", 2)),
            "FINAL": int(os.getenv("TWITTER_FINAL_MIN_FOLLOWERS", 5)),
            "MIGRATED": int(os.getenv("TWITTER_MIGRATED_MIN_FOLLOWERS", 20)),
            "OLD": int(os.getenv("TWITTER_OLD_MIN_FOLLOWERS", 90))
        }

    def validate_config(self) -> None:
        """Validate Twitter configuration and raise errors for invalid configurations."""
        logger.info("Validating Twitter configuration...")
        # --- DEBUG LOG --- 
        logger.debug(f"DEBUG: Validating credentials - Username: '{self.credentials.get('username')}', Email: '{self.credentials.get('email')}', Password Set: {bool(self.credentials.get('password'))}")
        # --- END DEBUG LOG ---
        errors = []

        # Check if any credentials are provided
        has_credentials = any(self.credentials.values())
        
        # Only validate credentials if any are provided
        if has_credentials:
            # If any credential is provided, all must be provided
            for key, value in self.credentials.items():
                if not value:
                    errors.append(f"Partial Twitter credentials found. If using Twitter API, all credentials (username, email, password) must be provided.")
        else:
            logger.warning("No Twitter credentials provided - will use simplified verification mode")

        # Validate follower thresholds
        for status, threshold in self.follower_thresholds.items():
            if threshold < 0:
                errors.append(f"Invalid {status} follower threshold: {threshold}. Must be non-negative.")

        if errors:
            for error in errors:
                logger.error(error)
            raise ValueError("Invalid Twitter configuration. Check logs for details.")
        logger.info("Twitter configuration validated successfully.")

    def display_config(self) -> None:
        """Display Twitter configuration (masking sensitive data)."""
        logger.info("Twitter Configuration:")
        # Display credentials (masked)
        logger.info(f"Username: {self.credentials['username']}")
        email = self.credentials['email']
        if email:
            masked_email = f"{email[:3]}{'*' * (len(email) - 6)}{email[-3:]}" if len(email) > 6 else "***"
            logger.info(f"Email: {masked_email}")
        else:
            logger.info("Email: Not configured")
        logger.info("Password: ********")
        
        # Display follower thresholds
        logger.info("Follower Thresholds:")
        for status, threshold in self.follower_thresholds.items():
            logger.info(f"  {status}: {threshold} followers")

    def get_follower_threshold(self, status: str) -> int:
        """Get the minimum follower threshold for a given token status."""
        return self.follower_thresholds.get(status, 0)

    def meets_follower_threshold(self, status: str, followers: int) -> bool:
        """Check if the follower count meets the threshold for the given status."""
        threshold = self.get_follower_threshold(status)
        return followers >= threshold 