# Synthron Crypto Trader - Utils Documentation

This document provides a detailed overview of the utility modules used in the Synthron Crypto Trader system. These utilities handle logging, validation, exception management, and various helper functions to ensure smooth and robust operations.

---

## Table of Contents

1. Exception Handler
2. Helpers
3. Logger
4. Validation

---

## 1. Exception Handler

File Path: `/utils/exception_handler.py`

The `ExceptionHandler` class provides centralized management of exceptions, including robust retry mechanisms, logging, and fallback execution.

### Features:

- **Handle Exceptions:** Logs detailed error messages and stack traces for debugging.
- **Retry on Exception:** Retries a function on failure with exponential backoff. Configurable for specific exception types and retry limits.
- **Fallback Execution:** Executes fallback logic when a function fails due to a handled exception.

### Example Usage:

```python
@ExceptionHandler.retry_on_exception(retries=3, backoff_factor=0.5, context="API Request")
def fetch_data():
    # Function logic here
    pass

@ExceptionHandler.validate_and_handle(fallback=lambda: "Fallback Value", context="Data Processing")
def process_data():
    # Function logic here
    pass
```

---

## 2. Helpers

File Path: `/utils/helpers.py`

The `helpers` module provides utility functions for date-time conversion, JSON parsing, API request retries, and data processing.

### Key Functions:

- **`convert_timestamp_to_datetime(timestamp, timezone)`**: Converts a Unix timestamp to a human-readable datetime.
- **`convert_datetime_to_timestamp(dt)`**: Converts a datetime object to a Unix timestamp.
- **`parse_json(data)`**: Parses a JSON string into a Python dictionary.
- **`retry_request(url, method, retries, ...)`**: Handles API requests with retry logic and exponential backoff.
- **`flatten_nested_dict(d, parent_key, sep)`**: Flattens a nested dictionary into a single-level dictionary.
- **`is_valid_email(email)`**: Validates an email address using regex.

### Example Usage:

```python
# Convert timestamp
dt = convert_timestamp_to_datetime(1672531200)

# Parse JSON
data = '{"key": "value"}'
parsed_data = parse_json(data)

# Retry API request
response = retry_request("https://api.example.com/data", retries=5)
```

---

## 3. Logger

File Path: `/utils/logger.py`

The `logger` module provides a robust logging system with support for file rotation, console logging, and email alerts for critical issues.

### Features:

- **Rotating File Logging:** Ensures logs are archived based on size, preventing unlimited growth.
- **Console Logging:** Configurable console output for real-time debugging.
- **Email Alerts:** Sends critical error notifications via email.

### Configuration:

Environment variables control the logger's behavior:

| Variable                | Default Value       | Description                          |
|-------------------------|---------------------|--------------------------------------|
| `LOG_FILE`              | `synthron.log`     | Log file name.                       |
| `LOG_LEVEL`             | `INFO`             | Logging level (`DEBUG`, `INFO`, etc.)|
| `MAX_LOG_FILE_SIZE`     | `10 * 1024 * 1024` | Maximum size of each log file.       |
| `BACKUP_COUNT`          | `5`                | Number of backup log files.          |
| `ENABLE_CONSOLE_LOGGING`| `True`             | Enable/disable console logging.      |
| `ENABLE_EMAIL_LOGGING`  | `False`            | Enable/disable email notifications.  |

### Example Usage:

```python
from utils.logger import get_logger

logger = get_logger("MyModule")
logger.info("This is an info message.")
logger.error("This is an error message.")
```

---

## 4. Validation

File Path: `/utils/validation.py`

The `validation` module provides utility functions for validating environment variables, API keys, trading pairs, and threshold values.

### Key Functions:

- **`validate_env_variables(required_vars)`**: Ensures required environment variables are set.
- **`validate_api_key(api_key, api_name)`**: Validates the presence and validity of an API key.
- **`validate_trading_pair(trading_pair, raydium_api_url)`**: Checks if a trading pair exists on Raydium.
- **`validate_thresholds(threshold_name, value, min_value, max_value)`**: Ensures a threshold value is within an acceptable range.
- **`validate_liquidity(min_liquidity, trading_pair, raydium_api_url)`**: Validates if a trading pair meets the minimum liquidity requirement.

### Example Usage:

```python
# Validate environment variables
validate_env_variables(["DEXSCREENER_API_URL", "RAYDIUM_API_KEY"])

# Validate API key
validate_api_key("my-api-key", "Raydium")

# Validate trading pair
is_valid = validate_trading_pair("SOL-USDC", "https://api.raydium.io")

# Validate thresholds
validate_thresholds("Minimum Liquidity", 1000, 500, 10000)

# Validate liquidity for a trading pair
is_sufficient = validate_liquidity(1000, "SOL-USDC", "https://api.raydium.io")
```

---

This documentation is designed for developers working on the Synthron Crypto Trader system, providing a comprehensive reference for the utility modules and their integration within the larger ecosystem.
