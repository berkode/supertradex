"""
Utilities Package for Synthron Crypto Trader.

This package contains reusable utility modules and functions designed to enhance the reliability, 
scalability, and maintainability of the trading system.

Modules Included:
- Logger: Centralized logging system with support for file rotation and console output.
- Validation: Functions for environment variable validation, API key verification, 
  trading pair existence checks, and threshold validations.
- Helpers: Common utilities such as timestamp conversion, JSON parsing, API retry logic, 
  and dictionary manipulation.
- Exception Handler: Centralized exception handling with support for retries, fallbacks, 
  and detailed error logging.

Each utility module is built to adhere to production-level standards for security, performance, 
and ease of integration.
"""

# Import utility modules and functions
from .logger import get_logger
from .validation import (
    validate_env_variables,
    validate_api_key,
    validate_trading_pair,
    validate_thresholds,
    validate_liquidity,
)
from .helpers import (
    convert_timestamp_to_datetime,
    convert_datetime_to_timestamp,
    parse_json,
    retry_request,
    flatten_nested_dict,
    is_valid_email,
)
from .exception_handler import ExceptionHandler

# Expose specific utilities for external use
__all__ = [
    # Logger
    "get_logger",
    # Validation
    "validate_env_variables",
    "validate_api_key",
    "validate_trading_pair",
    "validate_thresholds",
    "validate_liquidity",
    # Helpers
    "convert_timestamp_to_datetime",
    "convert_datetime_to_timestamp",
    "parse_json",
    "retry_request",
    "flatten_nested_dict",
    "is_valid_email",
    # Exception Handling
    "ExceptionHandler",
]

# Initialize package-wide logging for utility initialization
logger = get_logger("utils.__init__")
logger.info("Utilities package initialized successfully.")
