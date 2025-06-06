"""
Jupiter Price Parser for real-time price fetching via REST API
Fetches prices from Jupiter's price API
"""

import asyncio
import httpx
import time
from typing import Dict, Any, Optional, List, Set
from .base_parser import DexParser


class JupiterPriceParser(DexParser):
    """Parser for fetching real-time prices from Jupiter API"""
    
    DEX_ID = 'jupiter_price'
    
    def __init__(self, settings, logger=None, http_client=None):
        super().__init__(settings, logger)
        
        # Jupiter API configuration - Updated to new endpoint
        self.api_base_url = "https://lite-api.jup.ag/price/v2"
        self.price_endpoint = ""  # v2 API doesn't need additional path
        self.http_timeout = getattr(settings, 'HTTP_TIMEOUT', 30)
        
        # Price update interval from settings
        self.update_interval = getattr(settings, 'SOL_PRICE_UPDATE_INTERVAL', 30)  # Default 30 seconds
        
        # HTTP client for API requests - use shared client if provided
        self.http_client = http_client
        self._owns_http_client = http_client is None  # Track if we created the client
        
        # Tracking
        self.monitored_tokens: Set[str] = set()
        self.last_update_time = 0
        self.price_cache: Dict[str, Dict[str, Any]] = {}
        
        # Task management
        self.price_update_task = None
        self.is_running = False
        
        # SOL mint address for price conversion
        self.sol_mint = "So11111111111111111111111111111111111111112"
        
        if self.logger:
            self.logger.info(f"JupiterPriceParser initialized with {self.update_interval}s update interval")
    
    async def initialize(self) -> bool:
        """Initialize the HTTP client and prepare for price fetching"""
        try:
            if self._owns_http_client:
                self.http_client = httpx.AsyncClient(timeout=self.http_timeout)
            if self.logger:
                self.logger.info("JupiterPriceParser HTTP client initialized")
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to initialize JupiterPriceParser: {e}")
            return False
    
    async def close(self):
        """Clean up resources"""
        try:
            self.is_running = False
            
            if self.price_update_task and not self.price_update_task.done():
                self.price_update_task.cancel()
                try:
                    await self.price_update_task
                except asyncio.CancelledError:
                    pass
            
            if self._owns_http_client and self.http_client:
                await self.http_client.aclose()
                self.http_client = None
                
            if self.logger:
                self.logger.info("JupiterPriceParser closed successfully")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error closing JupiterPriceParser: {e}")
    
    def parse_swap_logs(self, logs: List[str], signature: str = None) -> Optional[Dict[str, Any]]:
        """
        Not applicable for REST API price parser
        This method is required by the base class but not used for price fetching
        """
        return None
    
    def parse_account_update(self, raw_data: Any, pool_address: str = None) -> Optional[Dict[str, Any]]:
        """
        Not applicable for REST API price parser
        This method is required by the base class but not used for price fetching
        """
        return None
    
    def add_token_to_monitor(self, mint_address: str):
        """Add a token to the monitoring list"""
        if mint_address and mint_address not in self.monitored_tokens:
            self.monitored_tokens.add(mint_address)
            if self.logger:
                self.logger.info(f"Added token {mint_address[:8]}... to Jupiter price monitoring")
    
    def remove_token_from_monitor(self, mint_address: str):
        """Remove a token from the monitoring list"""
        if mint_address in self.monitored_tokens:
            self.monitored_tokens.discard(mint_address)
            if mint_address in self.price_cache:
                del self.price_cache[mint_address]
            if self.logger:
                self.logger.info(f"Removed token {mint_address[:8]}... from Jupiter price monitoring")
    
    async def start_price_monitoring(self, callback=None):
        """Start the price monitoring loop"""
        if self.is_running:
            if self.logger:
                self.logger.warning("Jupiter price monitoring already running")
            return
        
        if not self.http_client:
            await self.initialize()
        
        self.is_running = True
        self.price_callback = callback
        self.price_update_task = asyncio.create_task(self._price_update_loop())
        
        if self.logger:
            self.logger.info(f"Started Jupiter price monitoring with {self.update_interval}s interval")
    
    async def stop_price_monitoring(self):
        """Stop the price monitoring loop"""
        self.is_running = False
        if self.price_update_task and not self.price_update_task.done():
            self.price_update_task.cancel()
            try:
                await self.price_update_task
            except asyncio.CancelledError:
                pass
        
        if self.logger:
            self.logger.info("Stopped Jupiter price monitoring")
    
    async def _price_update_loop(self):
        """Main loop for fetching prices at regular intervals"""
        while self.is_running:
            try:
                if self.monitored_tokens:
                    await self._fetch_and_process_prices()
                
                # Wait for the next update interval
                await asyncio.sleep(self.update_interval)
                
            except asyncio.CancelledError:
                if self.logger:
                    self.logger.info("Jupiter price update loop cancelled")
                break
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error in Jupiter price update loop: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(min(self.update_interval, 10))
    
    async def _fetch_and_process_prices(self):
        """Fetch prices for all monitored tokens"""
        try:
            # Jupiter API supports multiple tokens in a single request
            mint_list = ",".join(self.monitored_tokens)
            
            # Make API request
            url = f"{self.api_base_url}{self.price_endpoint}"
            params = {
                "ids": mint_list,
                "vsToken": self.sol_mint  # Get prices in SOL
            }
            
            if self.logger:
                self.logger.debug(f"Fetching Jupiter prices for {len(self.monitored_tokens)} tokens")
            
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Jupiter API returns data directly
            if isinstance(data, dict) and "data" in data:
                prices_data = data["data"]
            else:
                prices_data = data
                
            await self._process_price_data(prices_data)
                    
        except httpx.HTTPStatusError as e:
            if self.logger:
                self.logger.error(f"HTTP error fetching Jupiter prices: {e.response.status_code}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error fetching Jupiter prices: {e}")
    
    async def _process_price_data(self, prices_data: Dict[str, Any]):
        """Process the price data from Jupiter API"""
        current_time = time.time()
        
        for mint_address, price_info in prices_data.items():
            if mint_address in self.monitored_tokens:
                try:
                    # Jupiter returns price in the vs token (SOL in our case)
                    price_sol = price_info.get("price")
                    if price_sol is None:
                        continue
                    
                    price_sol_float = float(price_sol)
                    
                    # **PRICE VALIDATION** - Reject unrealistic prices
                    if price_sol_float > 10.0:  # No small token should cost more than 10 SOL
                        if self.logger:
                            self.logger.warning(f"🚨 Jupiter price validation FAILED for {mint_address[:8]}...: {price_sol_float:.8f} SOL is unrealistic (>10 SOL). Skipping.")
                        continue
                    
                    if price_sol_float <= 0:  # Reject zero or negative prices
                        if self.logger:
                            self.logger.warning(f"🚨 Jupiter price validation FAILED for {mint_address[:8]}...: {price_sol_float:.8f} SOL is invalid (<=0). Skipping.")
                        continue
                    
                    # Get USD price if available
                    price_usd = None
                    sol_price_usd = await self._get_sol_price_usd()
                    if sol_price_usd and sol_price_usd > 0:
                        price_usd = price_sol_float * sol_price_usd
                        
                        # Additional USD validation
                        if price_usd > 1000.0:  # No small token should cost more than $1000
                            if self.logger:
                                self.logger.warning(f"🚨 Jupiter USD price validation FAILED for {mint_address[:8]}...: ${price_usd:.2f} is unrealistic (>$1000). Skipping.")
                            continue
                    
                    price_data = {
                        "mint": mint_address,
                        "price_sol": price_sol_float,
                        "price_usd": price_usd,
                        "timestamp": current_time,
                        "source": "jupiter_api",
                        "dex_id": self.DEX_ID,
                        "raw_data": price_info,
                        "validated": True  # Mark as validated
                    }
                    
                    if sol_price_usd:
                        price_data["sol_price_usd"] = sol_price_usd
                    
                    # Update cache
                    self.price_cache[mint_address] = price_data
                    
                    # Call callback if provided
                    if hasattr(self, 'price_callback') and self.price_callback:
                        await self.price_callback(price_data)
                    
                    if self.logger:
                        try:
                            price_str = f"{price_sol_float:.8f} SOL"
                            if price_usd:
                                price_str += f" (${price_usd:.6f})"
                            self.logger.info(f"🪐 Jupiter price update: {mint_address[:8]}... = {price_str} ✅")
                        except (ValueError, TypeError):
                            self.logger.warning(f"🪐 Jupiter price update: {mint_address[:8]}... = {price_sol} SOL (invalid format)")
                        
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Error processing price for {mint_address}: {e}")
    
    async def _get_sol_price_usd(self) -> Optional[float]:
        """Get SOL price in USD"""
        try:
            # Use Jupiter API to get SOL price in USD
            url = f"{self.api_base_url}{self.price_endpoint}"
            params = {
                "ids": self.sol_mint,
                "vsToken": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC mint for USD price
            }
            
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract SOL price
            if isinstance(data, dict):
                if "data" in data:
                    sol_data = data["data"].get(self.sol_mint)
                else:
                    sol_data = data.get(self.sol_mint)
                    
                if sol_data:
                    return float(sol_data.get("price", 0))
            
            return None
            
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Could not fetch SOL price from Jupiter: {e}")
            return None
    
    async def get_current_price(self, mint_address: str) -> Optional[Dict[str, Any]]:
        """Get the current cached price for a token"""
        return self.price_cache.get(mint_address)
    
    async def fetch_single_price(self, mint_address: str) -> Optional[Dict[str, Any]]:
        """Fetch price for a single token immediately"""
        # Simple print to see if method is called
        print(f"🚀 JUPITER FETCH CALLED: {mint_address}")
        
        # Debug logging at the very start
        if self.logger:
            self.logger.info(f"🚀 Jupiter fetch_single_price called for: {mint_address}")
        
        try:
            if not self.http_client:
                await self.initialize()
            
            url = f"{self.api_base_url}{self.price_endpoint}"
            params = {
                "ids": mint_address,
                "vsToken": self.sol_mint
            }
            
            # Debug logging to see exact URL and client info
            if self.logger:
                self.logger.info(f"🔍 Jupiter API Debug - URL: {url}")
                self.logger.info(f"🔍 Jupiter API Debug - Params: {params}")
                self.logger.info(f"🔍 Jupiter API Debug - HTTP Client: {type(self.http_client)}")
                self.logger.info(f"🔍 Jupiter API Debug - Client closed: {getattr(self.http_client, 'is_closed', 'unknown')}")
            
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract price data
            if isinstance(data, dict):
                if "data" in data:
                    price_info = data["data"].get(mint_address)
                else:
                    price_info = data.get(mint_address)
                    
                if price_info:
                    price_sol = float(price_info.get("price", 0))
                    
                    # Convert to USD if possible
                    sol_price_usd = await self._get_sol_price_usd()
                    price_usd = None
                    if sol_price_usd and sol_price_usd > 0:
                        price_usd = price_sol * sol_price_usd
                    
                    return {
                        "mint": mint_address,
                        "price_sol": price_sol,
                        "price_usd": price_usd,
                        "timestamp": time.time(),
                        "source": "jupiter_api",
                        "dex_id": self.DEX_ID,
                        "raw_data": price_info
                    }
            
            return None
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error fetching single price for {mint_address}: {e}")
            return None
    
    async def get_quote(self, input_mint: str, output_mint: str, amount: int) -> Optional[Dict[str, Any]]:
        """Get a quote for swapping tokens (Jupiter's main feature)"""
        try:
            if not self.http_client:
                await self.initialize()
            
            # Use Jupiter's new quote API endpoint
            quote_url = "https://lite-api.jup.ag/swap/v1/quote"
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": "50"  # 0.5% slippage
            }
            
            response = await self.http_client.get(quote_url, params=params)
            response.raise_for_status()
            
            quote_data = response.json()
            
            if self.logger:
                in_amount = quote_data.get("inAmount", "0")
                out_amount = quote_data.get("outAmount", "0")
                self.logger.info(f"🪐 Jupiter quote: {in_amount} → {out_amount}")
            
            return quote_data
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting Jupiter quote: {e}")
            return None
    
    def get_monitoring_status(self) -> Dict[str, Any]:
        """Get current monitoring status"""
        return {
            "is_running": self.is_running,
            "monitored_tokens": len(self.monitored_tokens),
            "cached_prices": len(self.price_cache),
            "update_interval": self.update_interval,
            "last_update": self.last_update_time,
            "dex_id": self.DEX_ID
        } 