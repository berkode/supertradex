import time
import datetime
import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import requests
import json
import os # Import os for path operations
from pathlib import Path # Import Path
import re
import subprocess

# Import Settings for type hinting only
if TYPE_CHECKING:
    from config.settings import Settings

# Initialize logger
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO) # Removed hardcoded level

# Formatter for logging
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Function to ensure a directory exists
def ensure_directory_exists(dir_path: Path):
    """Creates a directory if it doesn't exist."""
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured directory exists: {dir_path}")
    except Exception as e:
        logger.error(f"Failed to create directory {dir_path}: {e}")
        raise # Re-raise the error as directory creation is often critical

# Function to setup all necessary output directories based on settings
def setup_output_dirs(settings: 'Settings'):
    """Creates necessary output subdirectories based on paths in settings."""
    logger.info("Setting up output directories...")
    # List of setting attributes that contain file paths whose parent dirs need to exist
    path_keys = [
        'LOG_FILE', 
        'WHITELIST_FILE',
        'PRICE_HISTORY_PATH', # Assuming this is a directory path itself
        'TRANSACTION_CSV_PATH',
        # Add any other setting keys that represent output file/directory paths
    ]
    
    created_dirs = set()

    for key in path_keys:
        try:
            path_value = getattr(settings, key, None)
            if path_value:
                # Convert to Path object
                p = Path(path_value)
                # Get the parent directory
                dir_to_create = p if p.suffix == '' else p.parent # If key represents a dir, use it directly
                
                # Avoid redundant checks/creation
                if dir_to_create not in created_dirs:
                    ensure_directory_exists(dir_to_create)
                    created_dirs.add(dir_to_create)
            else:
                logger.warning(f"Setting key '{key}' not found or is None, skipping directory setup for it.")
        except AttributeError:
             logger.warning(f"Setting key '{key}' not found, skipping directory setup.") # Should not happen if keys are correct
        except Exception as e:
             logger.error(f"Error setting up directory for setting '{key}' (path: {path_value}): {e}")
             # Decide if we should continue or raise

    logger.info("Output directories setup complete.")


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
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$"
    result = bool(re.match(pattern, email))
    logger.debug(f"Email validation for '{email}': {result}")
    return result


def get_git_commit_hash() -> Optional[str]:
    """Gets the short git commit hash of the current HEAD.

    Returns:
        Optional[str]: The short commit hash, or None if git command fails.
    """
    try:
        # Ensure command runs in the project root (adjust if necessary)
        # Assumes the script is run from a location within the git repo
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], 
            stderr=subprocess.STDOUT,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)) # Run git in the utils directory
        ).strip()
        logger.debug(f"Retrieved git commit hash: {commit_hash}")
        return commit_hash
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to get git commit hash. Is this a git repository? Error: {e.output.strip()}")
        return None
    except FileNotFoundError:
        logger.warning("Failed to get git commit hash. 'git' command not found.")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while getting git commit hash: {e}")
        return None
