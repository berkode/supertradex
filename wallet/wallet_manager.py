import os
import json
import logging
from typing import Optional
# import subprocess # Removed subprocess usage
# from cryptography.hazmat.primitives.asymmetric import padding # Removed unused crypto imports
# from cryptography.hazmat.primitives import hashes
# from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
# from cryptography.hazmat.primitives import serialization
# from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv
from solders.pubkey import Pubkey
from solders.keypair import Keypair # Added Keypair import
from pydantic import SecretStr # Import SecretStr
from config.settings import Settings
from utils.logger import get_logger # Use central logger
from solana.rpc.async_api import AsyncClient # For type hinting
from data.token_database import TokenDatabase # For type hinting

# Load environment variables from .env file - Handled by Settings now
# load_dotenv('config/.env')

# logger = logging.getLogger(__name__) # Use central logger
logger = get_logger(__name__)

class WalletManager:
    """Manages the user's Solana wallet keypair securely."""
    def __init__(self, settings: Settings, solana_client: AsyncClient, db: TokenDatabase):
        self.settings = settings
        self.solana_client = solana_client
        self.db = db
        self._keypair: Optional[Keypair] = None # Store the loaded keypair
        self.public_key: Optional[Pubkey] = None

        # Load keypair on initialization
        self._load_keypair()

    async def initialize(self) -> bool:
        """
        Asynchronous initialization method.
        Since the wallet is already initialized in __init__, this just verifies the state.
        
        Returns:
            bool: True if the wallet is properly initialized, False otherwise.
        """
        try:
            return self._keypair is not None and self.public_key is not None
        except Exception as e:
            logger.error(f"Error during WalletManager initialization: {e}")
            return False

    def _load_keypair(self):
        """Loads the Keypair from the private key stored in settings."""
        try:
            # Retrieve the potentially masked private key string from settings
            # Note: Settings masks it for logging, but WalletManager needs the real one.
            # We rely on the initial loading from .env (before masking) being correct.
            # Accessing WALLET_PRIVATE_KEY via the passed settings object if it exists there
            # or fallback to os.getenv if it's a direct environment variable not in Settings model.
            # For consistency with rules, it should be part of the Settings model.
            private_key_str = None
            if hasattr(self.settings, 'WALLET_PRIVATE_KEY'):
                # If WALLET_PRIVATE_KEY is a SecretStr in Settings
                if isinstance(self.settings.WALLET_PRIVATE_KEY, SecretStr):
                    private_key_str = self.settings.WALLET_PRIVATE_KEY.get_secret_value()
                else:
                    private_key_str = self.settings.WALLET_PRIVATE_KEY
            else:
                # Fallback for older configurations or direct env usage
                logger.warning("Attempting to load WALLET_PRIVATE_KEY directly from os.getenv. Consider adding it to the Settings model.")
                private_key_str = os.getenv("WALLET_PRIVATE_KEY") 

            if not private_key_str:
                raise ValueError("WALLET_PRIVATE_KEY environment variable not found or empty.")

            # Assuming the private key is stored as a base58 encoded string
            # Or potentially a byte array string like '[1, 2, 3,...]' - check format!
            # For base58 string:
            self._keypair = Keypair.from_base58_string(private_key_str)

            # For byte array string (e.g., from Phantom export):
            # import ast
            # pk_bytes = bytes(ast.literal_eval(private_key_str))
            # self._keypair = Keypair.from_bytes(pk_bytes)

            self.public_key = self._keypair.pubkey()
            logger.info(f"Wallet keypair loaded successfully for public key: {self.public_key}")

        except ValueError as e:
            logger.error(f"Failed to load keypair: Invalid private key format or value. Error: {e}")
            self._keypair = None
            self.public_key = None
            raise # Re-raise the error to prevent operation without a valid keypair
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading the keypair: {e}", exc_info=True)
            self._keypair = None
            self.public_key = None
            raise # Re-raise the error

    # Removed verify_wallet_setup - replaced by _load_keypair
    # def verify_wallet_setup(self):
    #     ...

    def get_public_key(self) -> Optional[Pubkey]:
        """
        Get the public key of the wallet.
        Returns:
            Optional[Pubkey]: The wallet's public key or None if not loaded.
        """
        # Ensure keypair is loaded (or attempt reload if needed)
        # if self._keypair is None:
        #     self._load_keypair() # Or handle error depending on design
        return self.public_key

    def get_keypair(self) -> Optional[Keypair]:
        """
        Get the loaded Keypair object.
        Returns:
            Optional[Keypair]: The loaded Keypair or None if loading failed.
        """
        # Ensure keypair is loaded
        # if self._keypair is None:
        #     self._load_keypair()
        return self._keypair

    # Removed subprocess-based sign_transaction
    # def sign_transaction(self, transaction_data: dict) -> str:
    #     ...

    # Removed subprocess-based generate_key_pair
    # @staticmethod
    # def generate_key_pair():
    #     ...

# Example usage (for testing):
# if __name__ == '__main__':
#     try:
#         manager = WalletManager()
#         pubkey = manager.get_public_key()
#         kp = manager.get_keypair()
#         if pubkey and kp:
#             print(f"Public Key: {pubkey}")
#             # print(f"Keypair: {kp}") # Careful printing keypair
#         else:
#             print("Failed to load wallet.")
#     except Exception as e:
#         print(f"Error: {e}")