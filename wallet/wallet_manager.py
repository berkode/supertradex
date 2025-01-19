import os
import json
import subprocess
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class WalletManager:
    def __init__(self):
        self.wallet_address = os.getenv("WALLET_ADDRESS")
        self.solana_cli_path = os.getenv("SOLANA_CLI_PATH", "solana")  # Default to 'solana' in PATH
        self.private_key = None
        self.verify_wallet_setup()

    def verify_wallet_setup(self):
        """
        Verify if the wallet is properly set up using the Solana CLI.
        """
        if not self.wallet_address:
            raise ValueError("WALLET_ADDRESS is not set in the .env file.")
        try:
            # Check if the wallet address is accessible via Solana CLI
            result = subprocess.run(
                [self.solana_cli_path, "address"],
                capture_output=True,
                text=True,
                check=True
            )
            cli_wallet_address = result.stdout.strip()
            if cli_wallet_address != self.wallet_address:
                raise ValueError("CLI wallet address does not match the configured wallet address.")
            print(f"Wallet verified: {self.wallet_address}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Solana CLI error: {e.stderr.strip()}")
        except FileNotFoundError:
            raise RuntimeError("Solana CLI is not installed or not in PATH.")

    def sign_transaction(self, transaction_data: dict) -> str:
        """
        Sign a transaction using Solana CLI.
        
        Args:
            transaction_data (dict): The transaction details to be signed.
        
        Returns:
            str: The signed transaction (base64-encoded signature).
        """
        try:
            # Serialize transaction data to JSON string
            transaction_json = json.dumps(transaction_data, sort_keys=True)
            
            # Write the transaction JSON to a temporary file
            with open("transaction.json", "w") as tx_file:
                tx_file.write(transaction_json)

            # Sign the transaction using Solana CLI
            result = subprocess.run(
                [self.solana_cli_path, "sign-message", "-m", transaction_json],
                capture_output=True,
                text=True,
                check=True
            )
            signature = result.stdout.strip()
            print("Transaction signed successfully.")
            return signature
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error signing transaction: {e.stderr.strip()}")
        finally:
            # Clean up the temporary transaction file
            if os.path.exists("transaction.json"):
                os.remove("transaction.json")

    @staticmethod
    def generate_key_pair():
        """
        Generate a new keypair using Solana CLI.
        """
        try:
            result = subprocess.run(
                ["solana", "keygen", "new", "--no-bip39-passphrase", "--outfile", "keypair.json"],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"Keypair generated and saved to keypair.json.\n{result.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error generating keypair: {e.stderr.strip()}")

