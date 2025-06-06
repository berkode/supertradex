import logging
import asyncio
from typing import Dict, Optional
from utils.logger import get_logger
from solders.pubkey import Pubkey
from solders.rpc.responses import GetBalanceResp
from solana.rpc.async_api import AsyncClient

class BalanceChecker:
    def __init__(self, solana_client: AsyncClient, http_client, wallet_pubkey: Pubkey, settings):
        """Initialize the BalanceChecker with required clients and info."""
        self.logger = get_logger(__name__)
        self.solana_client = solana_client
        self.http_client = http_client
        self.wallet_pubkey = wallet_pubkey
        self.settings = settings
        self.lock = asyncio.Lock()
        self.balances: Dict[str, float] = {}
        self.sol_balance_lamports: Optional[int] = None
        self.last_sol_check_time: Optional[float] = None
        self.sol_cache_duration = 60
        
    async def get_sol_balance(self, force_refresh: bool = False) -> int:
        """Get the SOL balance of the wallet in lamports.
        
        Args:
            force_refresh: If True, bypass cache and fetch fresh balance.
            
        Returns:
            int: Wallet SOL balance in lamports.
            
        Raises:
            Exception: If the balance cannot be fetched.
        """
        async with self.lock:
            now = asyncio.get_event_loop().time()
            if not force_refresh and self.sol_balance_lamports is not None and self.last_sol_check_time and (now - self.last_sol_check_time < self.sol_cache_duration):
                self.logger.debug(f"Returning cached SOL balance: {self.sol_balance_lamports} lamports")
                return self.sol_balance_lamports
                
            pubkey_to_check = self.wallet_pubkey
            self.logger.info(f"Fetching SOL balance for wallet pubkey: {str(pubkey_to_check)}")
            try:
                balance_response: GetBalanceResp = await self.solana_client.get_balance(pubkey_to_check)
                
                raw_balance_value = balance_response.value
                self.logger.info(f"Raw balance response value from RPC: {raw_balance_value}")

                if raw_balance_value is not None:
                    self.sol_balance_lamports = raw_balance_value
                    self.last_sol_check_time = now
                    self.logger.info(f"Fetched SOL balance: {self.sol_balance_lamports} lamports")
                    return self.sol_balance_lamports
                else:
                    self.logger.error(f"Failed to get SOL balance for {str(pubkey_to_check)}. Response value is None.")
                    raise ValueError("Failed to fetch SOL balance from RPC")
                    
            except Exception as e:
                self.logger.error(f"Error fetching SOL balance for {str(pubkey_to_check)}: {e}", exc_info=True)
                raise Exception(f"Could not fetch SOL balance: {e}") from e

    async def check_balance(self, mint: str) -> Optional[float]:
        """Check the balance of a specific SPL token for the associated wallet.
        
        Args:
            mint: Address of the SPL token to check.
            
        Returns:
            Optional[float]: Token balance if found, None otherwise.
        """
        NATIVE_SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"
        if mint is None or mint == "SOL" or mint == NATIVE_SOL_MINT_ADDRESS:
             try:
                 sol_lamports = await self.get_sol_balance() 
                 return sol_lamports / 1_000_000_000
             except Exception as e:
                 self.logger.error(f"Could not get SOL balance via check_balance: {e}")
                 return None

        async with self.lock:
            try:
                if mint in self.balances:
                    return self.balances[mint]
                    
                self.logger.warning(f"SPL token balance check for mint {mint} is not fully implemented yet.")
                
                balance = 0.0
                return balance
                
            except Exception as e:
                self.logger.error(f"Error checking balance for SPL token {mint}: {e}")
                return None
                
    async def update_balance(self, token_address: str, balance: float) -> bool:
        """Update the cached balance for a token (meant for SPL tokens).
        
        Args:
            token_address: Address of the token (mint) to update.
            balance: New balance value (float).
            
        Returns:
            bool: True if balance was updated, False otherwise.
        """
        async with self.lock:
            try:
                NATIVE_SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"
                if token_address is None or token_address == "SOL" or token_address == NATIVE_SOL_MINT_ADDRESS:
                    self.logger.warning("Attempted to update SOL balance via update_balance. Use get_sol_balance for SOL.")
                    return False
                    
                self.balances[token_address] = balance
                self.logger.debug(f"Updated cached balance for {token_address} to {balance}")
                return True
                
            except Exception as e:
                self.logger.error(f"Error updating balance for {token_address}: {e}")
                return False
                
    async def clear_cache(self):
        """Clear the balance cache."""
        async with self.lock:
            self.balances.clear()
            self.sol_balance_lamports = None
            self.last_sol_check_time = None
            self.logger.info("Cleared balance cache (SOL and SPL)")
            
    async def get_all_balances(self) -> Dict[str, float]:
        """Get all cached balances (SOL and SPL) for the wallet.
            
        Returns:
            Dict[str, float]: Dictionary mapping token mints/"SOL" to balances.
        """
        async with self.lock:
            all_bals = self.balances.copy()
            try:
                sol_lamports = await self.get_sol_balance()
                all_bals["SOL"] = sol_lamports / 1_000_000_000
            except Exception:
                self.logger.warning("Could not retrieve SOL balance for get_all_balances")
                
            return all_bals
            
    async def close(self):
        """Clean up resources."""
        self.logger.info("Closing BalanceChecker") 