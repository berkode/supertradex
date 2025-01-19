import time
import datetime
import logging
from typing import Any, Callable, Dict, List, Optional
import requests
import json

# Initialize logger
logger = logging.getLogger("utils.helpers")
logger.setLevel(logging.INFO)

# Formatter for logging
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


def convert_timestamp_to_datetime(timestamp: int, timezone: Optional[str] = "UTC") -> datetime.datetime:
    """
    Convert a Unix timestamp to a human-readable datetime object.

    Args:
        timestamp (int): The Unix timestamp to convert.
        timezone (Optional[str]): Timezone for the conversion. Defaults to 'UTC'.
    
    Returns:
        datetime.datetime: The converted datetime object.
    """
    try:
        dt = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
        logger.debug(f"Converted timestamp {timestamp} to datetime {dt}.")
        return dt
    except Exception as e:
        logger.error(f"Failed to convert timestamp {timestamp}: {e}")
        raise


def convert_datetime_to_timestamp(dt: datetime.datetime) -> int:
    """
    Convert a datetime object to a Unix timestamp.

    Args:
        dt (datetime.datetime): The datetime object to convert.
    
    Returns:
        int: The Unix timestamp.
    """
    try:
        timestamp = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
        logger.debug(f"Converted datetime {dt} to timestamp {timestamp}.")
        return timestamp
    except Exception as e:
        logger.error(f"Failed to convert datetime {dt}: {e}")
        raise


def parse_json(data: str) -> Dict:
    """
    Safely parse a JSON string into a Python dictionary.

    Args:
        data (str): JSON string to parse.
    
    Returns:
        Dict: Parsed JSON as a dictionary.
    """
    try:
        result = json.loads(data)
        logger.debug("JSON string parsed successfully.")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON data: {e}")
        raise ValueError("Invalid JSON data.") from e


def retry_request(
    url: str,
    method: str = "GET",
    retries: int = 3,
    backoff_factor: float = 0.3,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict] = None,
    data: Optional[Any] = None,
    timeout: int = 10,
) -> requests.Response:
    """
    Retry logic for failed API requests with exponential backoff.

    Args:
        url (str): The API endpoint URL.
        method (str): HTTP method ('GET', 'POST', etc.). Defaults to 'GET'.
        retries (int): Number of retry attempts. Defaults to 3.
        backoff_factor (float): Backoff factor for exponential delay. Defaults to 0.3.
        headers (Optional[Dict[str, str]]): HTTP headers. Defaults to None.
        params (Optional[Dict]): Query parameters. Defaults to None.
        data (Optional[Any]): Request body for POST requests. Defaults to None.
        timeout (int): Request timeout in seconds. Defaults to 10.
    
    Returns:
        requests.Response: HTTP response object.
    
    Raises:
        requests.RequestException: If all retries fail.
    """
    attempt = 0
    while attempt < retries:
        try:
            logger.info(f"Attempt {attempt + 1} for {method} request to {url}")
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=data,
                timeout=timeout,
            )
            response.raise_for_status()
            logger.info(f"Request to {url} succeeded.")
            return response
        except requests.RequestException as e:
            attempt += 1
            wait_time = backoff_factor * (2 ** (attempt - 1))
            logger.warning(f"Request failed ({e}). Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
    logger.error(f"Request to {url} failed after {retries} attempts.")
    raise requests.RequestException(f"Failed to complete request to {url} after {retries} retries.") from e


def flatten_nested_dict(d: Dict, parent_key: str = "", sep: str = ".") -> Dict:
    """
    Flatten a nested dictionary.

    Args:
        d (Dict): Dictionary to flatten.
        parent_key (str): Prefix for keys. Defaults to ''.
        sep (str): Separator between nested keys. Defaults to '.'.
    
    Returns:
        Dict: Flattened dictionary.
    """
    try:
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(flatten_nested_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        flattened = dict(items)
        logger.debug(f"Flattened dictionary: {flattened}")
        return flattened
    except Exception as e:
        logger.error(f"Failed to flatten dictionary: {e}")
        raise


def is_valid_email(email: str) -> bool:
    """
    Validate an email address.

    Args:
        email (str): Email address to validate.
    
    Returns:
        bool: True if the email is valid, False otherwise.
    """
    import re
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    result = bool(re.match(pattern, email))
    logger.debug(f"Email validation for '{email}': {result}")
    return result
