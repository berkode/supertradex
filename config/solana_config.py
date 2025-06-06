import os
import logging
from urllib.parse import urlparse
from config.settings import Settings
from typing import Dict, Any, Optional
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from utils.logger import get_logger

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SolanaConfig")

class SolanaConfig:
    """Configuration for Solana network interaction."""
    
    def __init__(self, settings: Settings):
        """Initialize with settings."""
        self.settings = settings
        self.cluster = settings.SOLANA_CLUSTER.lower()
        # Use HELIUS_RPC_URL as the primary endpoint
        self.rpc_url = settings.HELIUS_RPC_URL
        self.solana_mainnet_rpc = settings.SOLANA_MAINNET_RPC  # Store as fallback
        self.helius_wss_url = settings.HELIUS_WSS_URL
        self.helius_api_key = settings.HELIUS_API_KEY
        
        # Validate cluster value
        if self.cluster not in ['mainnet', 'testnet']:
            raise ValueError("SOLANA_CLUSTER must be either 'mainnet' or 'testnet'")

    # Default endpoints for Solana clusters
    DEFAULT_MAINNET_RPC = "https://api.mainnet-beta.solana.com"
    DEFAULT_TESTNET_RPC = "https://api.testnet.solana.com"

    @property
    def is_mainnet(self) -> bool:
        """Check if we're on mainnet."""
        return self.cluster == 'mainnet'
        
    @property
    def is_testnet(self) -> bool:
        """Check if we're on testnet."""
        return self.cluster == 'testnet'

    def get_rpc_endpoint(self) -> str:
        """Get the appropriate RPC endpoint based on cluster."""
        return self.rpc_url if self.is_mainnet else self.settings.SOLANA_TESTNET_RPC

    def validate_rpc_url(self, url: str) -> bool:
        """Validate RPC URL format."""
        try:
            if not url:
                return False
            parsed = urlparse(url)
            return all([parsed.scheme, parsed.netloc])
        except Exception as e:
            logger.error(f"Error validating RPC URL {url}: {e}")
            return False

    def validate_config(self) -> None:
        """Validate the Solana configuration."""
        logger.info("Validating Solana configuration...")
        errors = []

        if self.cluster not in ["mainnet", "testnet"]:
            errors.append(f"Invalid SOLANA_CLUSTER: {self.cluster}. Must be 'mainnet' or 'testnet'.")

        for rpc in [self.rpc_url, self.settings.SOLANA_TESTNET_RPC]:
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

    def display_config(self) -> None:
        """Display the current Solana configuration for debugging purposes."""
        logger.info("Current Solana Configuration:")
        logger.info(f"Cluster: {self.cluster}")
        logger.info(f"RPC URL: {self.rpc_url}")
        logger.info(f"Testnet RPC: {self.settings.SOLANA_TESTNET_RPC}")
        logger.info(f"Helius RPC: {self.solana_mainnet_rpc}")
        logger.info(f"Helius WSS: {self.helius_wss_url}")

if __name__ == "__main__":
    # Validate and display Solana configuration
    try:
        config = SolanaConfig(Settings())
        config.validate_config()
        config.display_config()

        # Example usage: Get the current RPC endpoint
        rpc_endpoint = config.get_rpc_endpoint()
        logger.info(f"Active RPC Endpoint: {rpc_endpoint}")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        exit(1)
