import os
import requests
import logging
from typing import List, Optional

# Configure logger
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO) # Removed hardcoded level
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass

def validate_env_variables(required_vars: List[str]) -> None:
    """
    Validate the presence of required environment variables.
    
    Args:
        required_vars (List[str]): List of required environment variables.
    
    Raises:
        ValidationError: If any required variable is missing.
    """
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        raise ValidationError(f"Missing required environment variables: {', '.join(missing_vars)}")
    logger.info("All required environment variables are set.")

def validate_api_key(api_key: Optional[str], api_name: str) -> None:
    """
    Validate if an API key is provided and non-empty.
    
    Args:
        api_key (Optional[str]): The API key to validate.
        api_name (str): Name of the API for logging.
    
    Raises:
        ValidationError: If the API key is missing or empty.
    """
    if not api_key:
        logger.error(f"API key for {api_name} is missing or invalid.")
        raise ValidationError(f"API key for {api_name} is missing or invalid.")
    logger.info(f"API key for {api_name} is valid.")

def validate_trading_pair(trading_pair: str, raydium_api_url: str) -> bool:
    """
    Validate if a trading pair exists on Raydium.
    
    Args:
        trading_pair (str): The trading pair to validate (e.g., 'SOL-USDC').
        raydium_api_url (str): Base URL for Raydium API.
    
    Returns:
        bool: True if the trading pair exists, False otherwise.
    
    Raises:
        ValidationError: If the API request fails.
    """
    try:
        logger.info(f"Validating trading pair: {trading_pair} on Raydium.")
        response = requests.get(f"{raydium_api_url}/pairs")
        response.raise_for_status()
        pairs = response.json().get("pairs", [])  # Assuming API returns a JSON with 'pairs' key
        if trading_pair in pairs:
            logger.info(f"Trading pair {trading_pair} exists on Raydium.")
            return True
        else:
            logger.warning(f"Trading pair {trading_pair} does not exist on Raydium.")
            return False
    except requests.RequestException as e:
        logger.error(f"Failed to fetch trading pairs from Raydium: {e}")
        raise ValidationError(f"Failed to fetch trading pairs from Raydium: {e}")

def validate_thresholds(threshold_name: str, value: float, min_value: float, max_value: float) -> None:
    """
    Validate if a threshold value falls within the allowed range.
    
    Args:
        threshold_name (str): Name of the threshold for logging purposes.
        value (float): The threshold value to validate.
        min_value (float): Minimum allowed value.
        max_value (float): Maximum allowed value.
    
    Raises:
        ValidationError: If the threshold value is out of bounds.
    """
    if not (min_value <= value <= max_value):
        logger.error(f"{threshold_name} value {value} is out of bounds. Allowed range: [{min_value}, {max_value}].")
        raise ValidationError(f"{threshold_name} value {value} is out of bounds. Allowed range: [{min_value}, {max_value}].")
    logger.info(f"{threshold_name} value {value} is within the allowed range.")

def validate_liquidity(min_liquidity: float, trading_pair: str, raydium_api_url: str) -> bool:
    """
    Validate if a trading pair meets the minimum liquidity requirement.
    
    Args:
        min_liquidity (float): Minimum liquidity threshold.
        trading_pair (str): Trading pair to check liquidity for.
        raydium_api_url (str): Base URL for Raydium API.
    
    Returns:
        bool: True if liquidity is sufficient, False otherwise.
    
    Raises:
        ValidationError: If the API request fails.
    """
    try:
        logger.info(f"Checking liquidity for trading pair: {trading_pair}.")
        response = requests.get(f"{raydium_api_url}/pair/{trading_pair}")
        response.raise_for_status()
        pair_data = response.json()  # Assuming API returns JSON with liquidity info
        liquidity = pair_data.get("liquidity", 0)
        if liquidity >= min_liquidity:
            logger.info(f"Trading pair {trading_pair} meets the minimum liquidity requirement: {liquidity}.")
            return True
        else:
            logger.warning(f"Trading pair {trading_pair} does not meet the minimum liquidity requirement: {liquidity}.")
            return False
    except requests.RequestException as e:
        logger.error(f"Failed to fetch liquidity data for {trading_pair}: {e}")
        raise ValidationError(f"Failed to fetch liquidity data for {trading_pair}: {e}")
