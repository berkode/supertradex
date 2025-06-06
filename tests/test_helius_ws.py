import asyncio
import websockets
import json
import logging
import os
import io # Added
from pathlib import Path # Added
from dotenv import dotenv_values, load_dotenv # Added

# Attempt to import Settings and encryption utils
try:
    from config.settings import Settings, EncryptionSettings # Modified
    from utils.encryption import get_encryption_password, decrypt_env_file # Added
    # Assuming PROJECT_ROOT is needed for path definitions similar to main.py
    PROJECT_ROOT = Path(__file__).parent.parent
except ImportError as e:
    logging.error(f"Failed to import necessary modules. Ensure PYTHONPATH or run from root: {e}")
    Settings = None # Ensure it's None if imports fail
    EncryptionSettings = None
    get_encryption_password = None
    decrypt_env_file = None
    PROJECT_ROOT = Path.cwd() # Fallback, might not be correct

# Configure basic logging for the test script
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Environment Variable Loading Logic (adapted from main.py) ---
def setup_test_environment():
    if not all([EncryptionSettings, get_encryption_password, decrypt_env_file]):
        logger.error("Encryption utilities not loaded, cannot setup test environment.")
        return False

    logger.info("--- Loading Environment Variables for Test ---")
    
    ENV_DIR = PROJECT_ROOT / "config"
    ENV_PLAIN_PATH = ENV_DIR / ".env"
    ENV_ENCRYPTED_PATH = ENV_DIR / ".env.encrypted"

    # Helper to update os.environ, simplified for test
    def update_os_environ(env_vars: dict, override: bool = False):
        updated_count = 0
        for key, value in env_vars.items():
            if value is None: continue
            value_str = str(value)
            if override or key not in os.environ:
                os.environ[key] = value_str
                updated_count += 1
        logger.debug(f"Updated {updated_count} OS environment variables from stream.")

    password = None
    try:
        # Attempt to get ENCRYPTION_KEY_PATH using EncryptionSettings
        # This ensures .env is read for ENCRYPTION_KEY_PATH if not already set
        key_settings = EncryptionSettings() 
        logger.info(f"Using key filename for password retrieval: {key_settings.ENCRYPTION_KEY_PATH}")
    except Exception as e:
        logger.warning(f"Could not initialize EncryptionSettings (e.g., .env missing or ENCRYPTION_KEY_PATH not in it): {e}")
        # If EncryptionSettings fails, get_encryption_password might still work if key_path is default or ENCRYPTION_KEY_PATH is already in os.environ
        logger.info("Attempting get_encryption_password with default key path or existing env var for key path.")


    try:
        password = get_encryption_password()
        if password:
            logger.info("Successfully retrieved encryption password.")
        else:
            password = os.getenv("ENCRYPTION_PASSWORD")
            if password:
                logger.info("Using ENCRYPTION_PASSWORD from OS environment.")
            else:
                logger.info("No stored or OS environment encryption password found.")
    except Exception as e:
        logger.error(f"Error retrieving encryption password: {e}")

    if ENV_ENCRYPTED_PATH.exists():
        logger.info(f"Found encrypted environment file: {ENV_ENCRYPTED_PATH}")
        if password:
            logger.info("Attempting decryption...")
            try:
                decrypted_content = decrypt_env_file(ENV_ENCRYPTED_PATH, password)
                if decrypted_content:
                    loaded_vars = dotenv_values(stream=io.StringIO(decrypted_content))
                    update_os_environ(loaded_vars, override=False) # Non-override from encrypted
                    logger.info(f"Environment updated with {len(loaded_vars)} vars from decrypted file.")
                else:
                    logger.warning(f"Failed to decrypt {ENV_ENCRYPTED_PATH} or content was empty.")
            except Exception as e:
                logger.error(f"Error decrypting/loading {ENV_ENCRYPTED_PATH}: {e}")
        else:
            logger.warning(f"Encrypted file {ENV_ENCRYPTED_PATH} exists, but no password available.")
    else:
        logger.info(f"Encrypted environment file not found: {ENV_ENCRYPTED_PATH}")

    if ENV_PLAIN_PATH.exists():
        logger.info(f"Loading plain environment file (with override): {ENV_PLAIN_PATH}")
        try:
            # load_dotenv from file will directly update os.environ
            # For Pydantic Settings, it will also re-read this .env file if it's specified as env_file
            # The Pydantic Settings class for this project points to config/.env
            # So, this load_dotenv call primarily ensures OS env is set before Pydantic tries.
            # Pydantic's own .env loading will then take effect.
            if load_dotenv(dotenv_path=ENV_PLAIN_PATH, override=True):
                 logger.info(f"Successfully loaded/overridden variables from plain file: {ENV_PLAIN_PATH}")
            else:
                 logger.info(f"Plain file {ENV_PLAIN_PATH} loaded, but no new variables were added/overridden in os.environ by this call.")

        except Exception as e:
            logger.error(f"Error loading plain .env file {ENV_PLAIN_PATH}: {e}")
    else:
        logger.info(f"Plain environment file not found: {ENV_PLAIN_PATH}")
    
    logger.info("--- Environment Variable Loading for Test Complete ---")
    return True
# --- End of Environment Variable Loading Logic ---

RAYDIUM_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

async def test_helius_log_subscribe():
    # Setup environment first
    if not Settings or not setup_test_environment(): # Modified to call setup
        logger.error("Failed to setup test environment or Settings class not available. Cannot proceed.")
        return

    try:
        settings = Settings() # Now this should find the necessary env vars
        uri = settings.HELIUS_WSS_URL
        masked_uri = uri
        if "api-key=" in uri and settings.HELIUS_API_KEY: # Check if API key is part of settings
            # Mask API key for logging more robustly
            api_key_value = settings.HELIUS_API_KEY.get_secret_value()
            masked_uri = uri.replace(api_key_value, "<REDACTED_API_KEY>") if api_key_value else uri
        elif "api-key=" in uri: # Fallback masking if API key not directly from settings
             parts = uri.split("api-key=")
             if len(parts) > 1:
                masked_uri = parts[0] + "api-key=<REDACTED>"


        logger.info(f"Attempting to connect to: {masked_uri}")

    except Exception as e:
        logger.error(f"Failed to initialize Settings or get HELIUS_WSS_URL: {e}")
        logger.error("Ensure your .env and .env.encrypted files are correctly set up in the 'config' directory.")
        return

    subscription_request = {
        "jsonrpc": "2.0",
        "id": 1, 
        "method": "logsSubscribe",
        "params": [
            {"mentions": [RAYDIUM_PROGRAM_ID]},
            {"commitment": "confirmed"}
        ]
    }

    try:
        async with websockets.connect(uri, ping_interval=20, ping_timeout=60) as websocket:
            logger.info("Connected to WebSocket.")
            logger.info(f"Sending subscription request: {json.dumps(subscription_request)}")
            await websocket.send(json.dumps(subscription_request))
            logger.info("Subscription request sent. Waiting for confirmation (timeout: 60s)...")

            try:
                confirmation_message = await asyncio.wait_for(websocket.recv(), timeout=60.0)
                logger.info(f"Received message: {confirmation_message}")
                
                response_data = json.loads(confirmation_message)
                if response_data.get("id") == subscription_request["id"] and "result" in response_data:
                    logger.info(f"Subscription successful! Subscription ID: {response_data['result']}")
                    logger.info("Now listening for logs for a short period (press CTRL+C to stop earlier)...")
                    for i in range(5): 
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                            logger.info(f"Received log [{i+1}/5]: {message}")
                        except asyncio.TimeoutError:
                            logger.info(f"Timeout waiting for log message [{i+1}/5].")
                            break 
                else:
                    logger.warning("Received a message, but it's not the expected subscription confirmation format or ID.")

            except asyncio.TimeoutError:
                logger.error("Timeout: Did not receive subscription confirmation within 60 seconds.")
            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"Connection closed while waiting for confirmation: {e}")
            except Exception as e:
                logger.error(f"Error processing incoming message: {e}")
            
            logger.info("Test listening period finished or interrupted.")

    except websockets.exceptions.InvalidURI:
        logger.error(f"Error: Invalid WebSocket URI constructed: {masked_uri}")
    except websockets.exceptions.ConnectionClosedError as e:
        logger.error(f"Error: Connection failed. Could not connect to the WebSocket server: {e}")
    except ConnectionRefusedError:
        logger.error("Error: Connection refused by the server. Check firewall or server status.")
    except asyncio.TimeoutError:
        logger.error("Error: Connection attempt timed out.")
    except Exception as e:
        logger.error(f"An unexpected error occurred during the test: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(test_helius_log_subscribe()) 