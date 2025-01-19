import os
import json
import asyncio
import aiohttp
from solana.publickey import PublicKey
from solana.transaction import Transaction, TransactionInstruction
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


class TransactionBuilder:
    def __init__(self):
        self.solana_cluster = os.getenv("SOLANA_CLUSTER", "mainnet")
        self.rpc_endpoint = self._get_rpc_endpoint()
        self.raydium_api_base_url = os.getenv("RAYDIUM_API_BASE_URL", "https://api-v3.raydium.io")
        self.client = AsyncClient(self.rpc_endpoint)

    def _get_rpc_endpoint(self):
        """Return the appropriate RPC endpoint based on the selected Solana cluster."""
        if self.solana_cluster == "mainnet":
            return os.getenv("SOLANA_MAINNET_RPC")
        elif self.solana_cluster == "testnet":
            return os.getenv("SOLANA_TESTNET_RPC")
        else:
            raise ValueError("Invalid SOLANA_CLUSTER value. Must be 'mainnet' or 'testnet'.")

    async def fetch_raydium_pool_info(self, pool_address: str) -> dict:
        """
        Fetch Raydium pool information from the API asynchronously.

        Args:
            pool_address (str): Address of the Raydium liquidity pool.

        Returns:
            dict: Pool details including token addresses, balances, etc.
        """
        url = f"{self.raydium_api_base_url}/pool/{pool_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise RuntimeError(f"Failed to fetch pool info: {await response.text()}")
                return await response.json()

    async def build_swap_transaction(self, wallet_address: str, pool_address: str, input_token: str, output_token: str, amount: int) -> Transaction:
        """
        Build a transaction for swapping tokens on Raydium.

        Args:
            wallet_address (str): User's wallet address.
            pool_address (str): Address of the Raydium liquidity pool.
            input_token (str): Mint address of the token to swap from.
            output_token (str): Mint address of the token to swap to.
            amount (int): Amount of the input token to swap (in lamports).

        Returns:
            Transaction: Solana transaction object ready to sign and send.
        """
        pool_info = await self.fetch_raydium_pool_info(pool_address)

        if input_token not in pool_info["tokens"] or output_token not in pool_info["tokens"]:
            raise ValueError("Specified tokens are not part of the liquidity pool.")

        # Define accounts and instructions
        wallet_pubkey = PublicKey(wallet_address)
        pool_pubkey = PublicKey(pool_address)
        input_token_pubkey = PublicKey(input_token)
        output_token_pubkey = PublicKey(output_token)

        instruction = TransactionInstruction(
            program_id=PublicKey(pool_info["program_id"]),
            keys=[
                {"pubkey": wallet_pubkey, "is_signer": True, "is_writable": True},
                {"pubkey": pool_pubkey, "is_signer": False, "is_writable": True},
                {"pubkey": input_token_pubkey, "is_signer": False, "is_writable": True},
                {"pubkey": output_token_pubkey, "is_signer": False, "is_writable": True},
            ],
            data=amount.to_bytes(8, "little"),
        )

        transaction = Transaction()
        transaction.add(instruction)
        return transaction

    async def send_transaction(self, transaction: Transaction, wallet_keypair) -> str:
        """
        Sign and send a transaction to the Solana blockchain asynchronously.

        Args:
            transaction (Transaction): The Solana transaction to be sent.
            wallet_keypair: Keypair object for signing the transaction.

        Returns:
            str: Transaction signature.
        """
        try:
            response = await self.client.send_transaction(transaction, wallet_keypair, opts=TxOpts(skip_confirmation=False))
            print(f"Transaction sent successfully. Signature: {response['result']}")
            return response["result"]
        except Exception as e:
            raise RuntimeError(f"Failed to send transaction: {e}")

    async def close(self):
        """Close the async RPC client."""
        await self.client.close()

