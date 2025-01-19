import os
from dotenv import load_dotenv
import logging
from urllib.parse import urlparse

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SolanaConfig")

class SolanaConfig:
    """Class to manage Solana network configurations for the trading system."""

    # Default endpoints for Solana clusters
    DEFAULT_MAINNET_RPC = "https://api.mainnet-beta.solana.com"
    DEFAULT_TESTNET_RPC = "https://api.testnet.solana.com"

    # Cluster configuration
    CLUSTER = os.getenv("SOLANA_CLUSTER", "mainnet").lower()  # Either 'mainnet' or 'testnet'

    MAINNET_RPC = os.getenv("SOLANA_MAINNET_RPC", DEFAULT_MAINNET_RPC)
    TESTNET_RPC = os.getenv("SOLANA_TESTNET_RPC", DEFAULT_TESTNET_RPC)

    @classmethod
    def get_rpc_endpoint(cls):
        """Retrieve the RPC endpoint based on the selected cluster.

        Returns:
            str: The RPC endpoint URL for the selected cluster.
        """
        rpc_endpoint = ""
        if cls.CLUSTER == "mainnet":
            rpc_endpoint = cls.MAINNET_RPC
        elif cls.CLUSTER == "testnet":
            rpc_endpoint = cls.TESTNET_RPC
        else:
            logger.error(f"Invalid Solana cluster specified: {cls.CLUSTER}")
            raise ValueError(f"Invalid Solana cluster: {cls.CLUSTER}. Must be 'mainnet' or 'testnet'.")

        logger.info(f"Using Solana {cls.CLUSTER.capitalize()} RPC: {rpc_endpoint}")
        return rpc_endpoint

    @classmethod
    def validate_config(cls):
        """Validate the Solana configuration."""
        logger.info("Validating Solana configuration...")
        errors = []

        if cls.CLUSTER not in ["mainnet", "testnet"]:
            errors.append(f"Invalid SOLANA_CLUSTER: {cls.CLUSTER}. Must be 'mainnet' or 'testnet'.")

        for rpc in [cls.MAINNET_RPC, cls.TESTNET_RPC]:
            if not rpc.startswith("https://"):
                errors.append(f"RPC endpoint must start with 'https://'. Invalid endpoint: {rpc}")
            try:
                result = urlparse(rpc)
                if not all([result.scheme, result.netloc]):
                    errors.append(f"Invalid URL format for RPC endpoint: {rpc}")
            except Exception as e:
                errors.append(f"Error parsing RPC endpoint '{rpc}': {e}")

        if errors:
            for error in errors:
                logger.error(error)
            raise ValueError("Solana configuration validation failed. Check logs for details.")

        logger.info("Solana configuration validated successfully.")

    @classmethod
    def display_config(cls):
        """Display the current Solana configuration for debugging purposes."""
        logger.info("Current Solana Configuration:")
        logger.info(f"Cluster: {cls.CLUSTER}")
        logger.info(f"Mainnet RPC: {cls.MAINNET_RPC}")
        logger.info(f"Testnet RPC: {cls.TESTNET_RPC}")

if __name__ == "__main__":
    # Validate and display Solana configuration
    try:
        SolanaConfig.validate_config()
        SolanaConfig.display_config()

        # Example usage: Get the current RPC endpoint
        rpc_endpoint = SolanaConfig.get_rpc_endpoint()
        logger.info(f"Active RPC Endpoint: {rpc_endpoint}")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        exit(1)
