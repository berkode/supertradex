"""
Raydium Price Parser for real-time price fetching via REST API
Fetches prices from https://api.raydium.io/v2/main/price
"""

import asyncio
import httpx
import time
from typing import Dict, Any, Optional, List, Set
from .base_parser import DexParser


class RaydiumPriceParser(DexParser):
    """Parser for fetching real-time prices from Raydium REST API"""
    
    DEX_ID = 'raydium_price'
    
    def __init__(self, settings, logger=None):
        super().__init__(settings, logger)
        
        # Raydium API configuration
        self.api_base_url = "https://api.raydium.io/v2"
        self.price_endpoint = "/main/price"
        self.http_timeout = getattr(settings, 'HTTP_TIMEOUT', 30)
        
        # Price update interval from settings
        self.update_interval = getattr(settings, 'SOL_PRICE_UPDATE_INTERVAL', 30)  # Default 30 seconds
        
        # HTTP client for API requests
        self.http_client = None
        
        # Tracking
        self.monitored_tokens: Set[str] = set()
        self.last_update_time = 0
        self.price_cache: Dict[str, Dict[str, Any]] = {}
        
        # Task management
        self.price_update_task = None
        self.is_running = False
        
        if self.logger:
            self.logger.info(f"RaydiumPriceParser initialized with {self.update_interval}s update interval")
    
    async def initialize(self) -> bool:
        """Initialize the HTTP client and prepare for price fetching"""
        try:
            self.http_client = httpx.AsyncClient(timeout=self.http_timeout)
            if self.logger:
                self.logger.info("RaydiumPriceParser HTTP client initialized")
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to initialize RaydiumPriceParser: {e}")
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
            
            if self.http_client:
                await self.http_client.aclose()
                self.http_client = None
                
            if self.logger:
                self.logger.info("RaydiumPriceParser closed successfully")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error closing RaydiumPriceParser: {e}")
    
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
                self.logger.info(f"Added token {mint_address[:8]}... to Raydium price monitoring")
    
    def remove_token_from_monitor(self, mint_address: str):
        """Remove a token from the monitoring list"""
        if mint_address in self.monitored_tokens:
            self.monitored_tokens.discard(mint_address)
            if mint_address in self.price_cache:
                del self.price_cache[mint_address]
            if self.logger:
                self.logger.info(f"Removed token {mint_address[:8]}... from Raydium price monitoring")
    
    async def start_price_monitoring(self, callback=None):
        """Start the price monitoring loop"""
        if self.is_running:
            if self.logger:
                self.logger.warning("Raydium price monitoring already running")
            return
        
        if not self.http_client:
            await self.initialize()
        
        self.is_running = True
        self.price_callback = callback
        self.price_update_task = asyncio.create_task(self._price_update_loop())
        
        if self.logger:
            self.logger.info(f"Started Raydium price monitoring with {self.update_interval}s interval")
    
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
            self.logger.info("Stopped Raydium price monitoring")
    
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
                    self.logger.info("Raydium price update loop cancelled")
                break
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error in Raydium price update loop: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(min(self.update_interval, 10))
    
    async def _fetch_and_process_prices(self):
        """Fetch prices for all monitored tokens"""
        try:
            # Create comma-separated list of mint addresses
            mint_list = ",".join(self.monitored_tokens)
            
            # Make API request
            url = f"{self.api_base_url}{self.price_endpoint}"
            params = {"mints": mint_list}
            
            if self.logger:
                self.logger.debug(f"Fetching Raydium prices for {len(self.monitored_tokens)} tokens")
            
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("success", False):
                prices_data = data.get("data", {})
                await self._process_price_data(prices_data)
            else:
                if self.logger:
                    self.logger.warning(f"Raydium API returned unsuccessful response: {data}")
                    
        except httpx.HTTPStatusError as e:
            if self.logger:
                self.logger.error(f"HTTP error fetching Raydium prices: {e.response.status_code}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error fetching Raydium prices: {e}")
    
    async def _process_price_data(self, prices_data: Dict[str, Any]):
        """Process the price data from Raydium API"""
        current_time = time.time()
        
        for mint_address, price_info in prices_data.items():
            if mint_address in self.monitored_tokens:
                try:
                    # Extract price in SOL (Raydium typically returns USD prices)
                    price_usd = price_info.get("price")
                    if price_usd is None:
                        continue
                    
                    # Convert USD to SOL if needed (we'll need SOL price for this)
                    # For now, store both USD and the raw data
                    price_data = {
                        "mint": mint_address,
                        "price_usd": float(price_usd),
                        "price_sol": None,  # Will be calculated if SOL/USD rate is available
                        "timestamp": current_time,
                        "source": "raydium_api",
                        "dex_id": self.DEX_ID,
                        "raw_data": price_info
                    }
                    
                    # Try to get SOL price and convert
                    sol_price_usd = await self._get_sol_price_usd()
                    if sol_price_usd and sol_price_usd > 0:
                        price_data["price_sol"] = float(price_usd) / sol_price_usd
                        price_data["sol_price_usd"] = sol_price_usd
                    
                    # Update cache
                    self.price_cache[mint_address] = price_data
                    
                    # Call callback if provided
                    if hasattr(self, 'price_callback') and self.price_callback:
                        await self.price_callback(price_data)
                    
                    if self.logger:
                        price_str = f"${price_usd:.6f}"
                        if price_data["price_sol"]:
                            price_str += f" ({price_data['price_sol']:.8f} SOL)"
                        self.logger.info(f"📈 Raydium price update: {mint_address[:8]}... = {price_str}")
                        
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Error processing price for {mint_address}: {e}")
    
    async def _get_sol_price_usd(self) -> Optional[float]:
        """Get SOL price in USD for conversion"""
        try:
            # Use SOL mint address
            sol_mint = "So11111111111111111111111111111111111111112"
            
            url = f"{self.api_base_url}{self.price_endpoint}"
            params = {"mints": sol_mint}
            
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            if data.get("success", False):
                sol_data = data.get("data", {}).get(sol_mint)
                if sol_data:
                    return float(sol_data.get("price", 0))
            
            return None
            
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Could not fetch SOL price: {e}")
            return None
    
    async def get_current_price(self, mint_address: str) -> Optional[Dict[str, Any]]:
        """Get the current cached price for a token"""
        return self.price_cache.get(mint_address)
    
    async def fetch_single_price(self, mint_address: str) -> Optional[Dict[str, Any]]:
        """Fetch price for a single token immediately"""
        try:
            if not self.http_client:
                await self.initialize()
            
            url = f"{self.api_base_url}{self.price_endpoint}"
            params = {"mints": mint_address}
            
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            if data.get("success", False):
                price_info = data.get("data", {}).get(mint_address)
                if price_info:
                    price_usd = float(price_info.get("price", 0))
                    
                    # Convert to SOL if possible
                    sol_price_usd = await self._get_sol_price_usd()
                    price_sol = None
                    if sol_price_usd and sol_price_usd > 0:
                        price_sol = price_usd / sol_price_usd
                    
                    return {
                        "mint": mint_address,
                        "price_usd": price_usd,
                        "price_sol": price_sol,
                        "timestamp": time.time(),
                        "source": "raydium_api",
                        "dex_id": self.DEX_ID,
                        "raw_data": price_info
                    }
            
            return None
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error fetching single price for {mint_address}: {e}")
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