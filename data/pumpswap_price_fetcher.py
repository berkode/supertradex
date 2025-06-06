"""
PumpSwap Price Fetcher using direct pool queries
Based on https://github.com/berkode/PumpSwapAMM
"""
import asyncio
import logging
from decimal import Decimal
from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timezone
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
import struct

class PumpSwapPriceFetcher:
    """Direct pool price fetching for PumpSwap AMM tokens using pool queries."""
    
    def __init__(self, solana_client: AsyncClient, settings, logger=None):
        self.solana_client = solana_client
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        
        # Pool cache for efficiency
        self.pool_cache: Dict[str, Dict] = {}
        self.last_price_cache: Dict[str, Tuple[float, datetime]] = {}
        
        # Known pool addresses for direct access
        self.known_pools = {
            "7ZYyESa8TkuoBVFi5seeLPr7B3MeLvyPgEgv5MDTpump": {  # Saphi
                "pool_address": "GHtwNAYk8UyABF7g...",  # This would be the actual pool address
                "decimals": 6
            }
        }
        
    async def fetch_pool_data(self, pool_address: str) -> Optional[Dict[str, Any]]:
        """
        Fetch pool data structure similar to PumpSwapAMM's fetch_pool function.
        Based on: https://github.com/berkode/PumpSwapAMM
        """
        try:
            pool_pubkey = Pubkey.from_string(pool_address)
            
            # Get pool account info
            response = await self.solana_client.get_account_info(pool_pubkey)
            if not response.value or not response.value.data:
                self.logger.warning(f"No pool data found for {pool_address}")
                return None
                
            # Parse pool data (simplified version)
            # This would need to be implemented based on the actual pool structure
            pool_data = {
                "pool_pubkey": pool_pubkey,
                "base_mint": None,  # Would be parsed from account data
                "quote_mint": None,  # Would be parsed from account data
                "pool_base_token_account": None,
                "pool_quote_token_account": None
            }
            
            self.pool_cache[pool_address] = pool_data
            return pool_data
            
        except Exception as e:
            self.logger.error(f"Error fetching pool data for {pool_address}: {e}")
            return None
    
    async def fetch_pool_price(self, pool_address: str, token_mint: str) -> Optional[float]:
        """
        Fetch current pool price similar to PumpSwapAMM's fetch_pool_base_price.
        Based on: https://github.com/berkode/PumpSwapAMM
        """
        try:
            # Get or fetch pool data
            pool_data = self.pool_cache.get(pool_address)
            if not pool_data:
                pool_data = await self.fetch_pool_data(pool_address)
                if not pool_data:
                    return None
            
            # Get token account balances for price calculation
            base_account = pool_data.get("pool_base_token_account")
            quote_account = pool_data.get("pool_quote_token_account")
            
            if not base_account or not quote_account:
                self.logger.warning(f"Missing token accounts for pool {pool_address}")
                return None
            
            # Fetch account balances
            base_response = await self.solana_client.get_token_account_balance(Pubkey.from_string(base_account))
            quote_response = await self.solana_client.get_token_account_balance(Pubkey.from_string(quote_account))
            
            if not base_response.value or not quote_response.value:
                return None
                
            # Calculate price from reserves (base_price = quote_balance / base_balance)
            base_balance = float(base_response.value.amount) / (10 ** base_response.value.decimals)
            quote_balance = float(quote_response.value.amount) / (10 ** quote_response.value.decimals)
            
            if base_balance <= 0:
                return None
                
            price_sol = quote_balance / base_balance
            
            # Cache the price
            self.last_price_cache[token_mint] = (price_sol, datetime.now(timezone.utc))
            
            self.logger.debug(f"📊 PumpSwap pool price for {token_mint}: {price_sol:.8f} SOL")
            return price_sol
            
        except Exception as e:
            self.logger.error(f"Error fetching pool price for {pool_address}: {e}")
            return None
    
    async def get_cached_price(self, token_mint: str, max_age_seconds: int = 30) -> Optional[float]:
        """Get cached price if recent enough."""
        if token_mint not in self.last_price_cache:
            return None
            
        price, timestamp = self.last_price_cache[token_mint]
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        
        if age <= max_age_seconds:
            return price
        else:
            return None
    
    async def fetch_multiple_pool_prices(self, token_pool_mapping: Dict[str, str]) -> Dict[str, Optional[float]]:
        """
        Fetch prices for multiple tokens in parallel.
        
        Args:
            token_pool_mapping: Dict mapping token_mint -> pool_address
            
        Returns:
            Dict mapping token_mint -> price_in_sol
        """
        tasks = []
        token_mints = []
        
        for token_mint, pool_address in token_pool_mapping.items():
            tasks.append(self.fetch_pool_price(pool_address, token_mint))
            token_mints.append(token_mint)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        price_results = {}
        for i, result in enumerate(results):
            token_mint = token_mints[i]
            if isinstance(result, Exception):
                self.logger.error(f"Error fetching price for {token_mint}: {result}")
                price_results[token_mint] = None
            else:
                price_results[token_mint] = result
                
        return price_results
    
    async def start_price_monitoring(self, token_pool_mapping: Dict[str, str], 
                                   update_callback=None, interval_seconds: int = 10):
        """
        Start continuous price monitoring for specified tokens.
        
        Args:
            token_pool_mapping: Dict mapping token_mint -> pool_address
            update_callback: Function to call with price updates
            interval_seconds: How often to fetch prices
        """
        self.logger.info(f"🔄 Starting PumpSwap price monitoring for {len(token_pool_mapping)} tokens")
        
        while True:
            try:
                prices = await self.fetch_multiple_pool_prices(token_pool_mapping)
                
                for token_mint, price in prices.items():
                    if price is not None and update_callback:
                        await update_callback({
                            "token_mint": token_mint,
                            "price_sol": price,
                            "source": "pumpswap_pool",
                            "timestamp": datetime.now(timezone.utc)
                        })
                
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                self.logger.error(f"Error in PumpSwap price monitoring loop: {e}")
                await asyncio.sleep(interval_seconds) 