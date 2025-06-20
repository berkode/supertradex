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
- Encryption: Utilities for encrypting sensitive environment variables.
- ColoredFormatter: Utility for adding color to log messages.

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
    get_git_commit_hash,
)
from .exception_handler import ExceptionHandler
from .encryption import (
    generate_key,
    generate_master_key,
    store_encryption_password,
    get_encryption_password,
    encrypt_env_file,
    decrypt_env_file,
    test_encryption,
)
from .colored_formatter import ColoredFormatter

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
    "get_git_commit_hash",
    # Exception Handling
    "ExceptionHandler",
    # Encryption
    "generate_key",
    "generate_master_key",
    "store_encryption_password",
    "get_encryption_password",
    "encrypt_env_file",
    "decrypt_env_file",
    "test_encryption",
    # Formatting
    "ColoredFormatter",
]

# Initialize package-wide logging for utility initialization
logger = get_logger("utils.__init__")
logger.info("Utilities package initialized successfully.")
