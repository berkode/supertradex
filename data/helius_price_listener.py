import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable
import websockets
from websockets.exceptions import WebSocketException, ConnectionClosed
from solders.pubkey import Pubkey
from datetime import datetime

from config.settings import Settings
from data.token_database import TokenDatabase
from data.price_monitor import PriceMonitor
from utils.logger import get_logger

class HeliusPriceListener:
    """
    Focused Helius WebSocket listener for real-time price calculation.
    Monitors the best tokens from database and calculates SOL prices from blockchain swaps.
    """
    
    def __init__(self, settings: Settings, token_db: TokenDatabase, price_monitor: PriceMonitor):
        self.settings = settings
        self.token_db = token_db
        self.price_monitor = price_monitor
        self.logger = get_logger(__name__)
        
        # WebSocket connection
        self.ws = None
        self.is_running = False
        self.stop_event = asyncio.Event()
        
        # Price tracking
        self.blockchain_prices: Dict[str, float] = {}  # mint -> SOL price
        self.api_prices: Dict[str, float] = {}  # mint -> SOL price from Jupiter
        self.last_price_update: Dict[str, datetime] = {}
        
        # Monitored tokens
        self.monitored_tokens: List[Dict] = []
        self.subscription_ids: Dict[str, int] = {}  # mint -> subscription_id
        
        # Callbacks for price updates
        self.price_callbacks: List[Callable] = []
        
        # Known DEX program IDs for swap detection
        self.dex_programs = {
            "raydium_v4": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
            "raydium_clmm": "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK", 
            "pumpfun": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
            "pumpswap": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
        }
        
        # SOL mint address for price calculations
        self.SOL_MINT = "So11111111111111111111111111111111111111112"
        
    async def initialize(self) -> bool:
        """Initialize the listener and get tokens to monitor."""
        try:
            # Get best tokens from database (limit to top 10 for performance)
            self.monitored_tokens = await self.token_db.get_valid_tokens(limit=10)
            self.logger.info(f"🎯 Helius Price Listener initialized with {len(self.monitored_tokens)} tokens to monitor")
            
            for token in self.monitored_tokens:
                mint = token.get('mint')
                symbol = token.get('symbol', 'UNKNOWN')
                self.logger.info(f"  📊 Monitoring: {symbol} ({mint})")
                
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Helius Price Listener: {e}")
            return False
    
    def add_price_callback(self, callback: Callable):
        """Add a callback function to be called when prices are updated."""
        self.price_callbacks.append(callback)
    
    async def start(self):
        """Start the Helius WebSocket listener."""
        if not await self.initialize():
            return False
            
        self.is_running = True
        self.stop_event.clear()
        
        # Start the main listening loop
        asyncio.create_task(self._listen_loop())
        
        # Start API price fetching task
        asyncio.create_task(self._fetch_api_prices_loop())
        
        self.logger.info("🚀 Helius Price Listener started")
        return True
    
    async def stop(self):
        """Stop the listener."""
        self.is_running = False
        self.stop_event.set()
        
        if self.ws:
            await self.ws.close()
            
        self.logger.info("🛑 Helius Price Listener stopped")
    
    async def _listen_loop(self):
        """Main WebSocket listening loop with reconnection."""
        while self.is_running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                self.logger.error(f"❌ Helius listener error: {e}")
                if self.is_running:
                    self.logger.info("🔄 Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def _connect_and_listen(self):
        """Connect to Helius WebSocket and listen for messages."""
        wss_url = self.settings.SOLANA_WSS_URL
        if not wss_url:
            self.logger.error("❌ No Helius WebSocket URL configured")
            return
            
        self.logger.info(f"🔗 Connecting to Helius WebSocket...")
        
        async with websockets.connect(wss_url) as ws:
            self.ws = ws
            self.logger.info("✅ Connected to Helius WebSocket")
            
            # Subscribe to DEX program logs for swap detection
            await self._subscribe_to_dex_programs()
            
            # Listen for messages
            async for message in ws:
                if not self.is_running:
                    break
                    
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except Exception as e:
                    self.logger.error(f"❌ Error processing message: {e}")
    
    async def _subscribe_to_dex_programs(self):
        """Subscribe to DEX program logs to detect swaps."""
        for dex_name, program_id in self.dex_programs.items():
            try:
                subscription_request = {
                    "jsonrpc": "2.0",
                    "id": f"sub_{dex_name}",
                    "method": "logsSubscribe",
                    "params": [
                        {
                            "mentions": [program_id]
                        },
                        {
                            "commitment": "confirmed"
                        }
                    ]
                }
                
                await self.ws.send(json.dumps(subscription_request))
                self.logger.info(f"📡 Subscribed to {dex_name} program logs")
                
            except Exception as e:
                self.logger.error(f"❌ Failed to subscribe to {dex_name}: {e}")
    
    async def _handle_message(self, data: Dict):
        """Handle incoming WebSocket messages."""
        try:
            # Check if it's a subscription confirmation
            if "result" in data and "id" in data:
                sub_id = data["result"]
                request_id = data["id"]
                self.logger.debug(f"✅ Subscription confirmed: {request_id} -> {sub_id}")
                return
            
            # Check if it's a log notification
            if "method" in data and data["method"] == "logsNotification":
                params = data.get("params", {})
                result = params.get("result", {})
                
                if "value" in result:
                    log_data = result["value"]
                    await self._process_log_data(log_data)
                    
        except Exception as e:
            self.logger.error(f"❌ Error handling message: {e}")
    
    async def _process_log_data(self, log_data: Dict):
        """Process log data to extract swap information and calculate prices."""
        try:
            logs = log_data.get("logs", [])
            signature = log_data.get("signature", "")
            
            # Look for swap-related logs
            swap_detected = False
            for log in logs:
                if any(keyword in log.lower() for keyword in ["swap", "trade", "exchange"]):
                    swap_detected = True
                    break
            
            if not swap_detected:
                return
            
            # Extract price information from logs
            price_info = await self._extract_price_from_logs(logs, signature)
            if price_info:
                mint = price_info.get("mint")
                sol_price = price_info.get("sol_price")
                
                if mint and sol_price and mint in [t.get("mint") for t in self.monitored_tokens]:
                    # Update blockchain price
                    self.blockchain_prices[mint] = sol_price
                    self.last_price_update[mint] = datetime.now()
                    
                    # Get token symbol
                    token_symbol = next((t.get("symbol", "UNKNOWN") for t in self.monitored_tokens if t.get("mint") == mint), "UNKNOWN")
                    
                    self.logger.info(f"💰 {token_symbol} blockchain price: {sol_price:.10f} SOL")
                    
                    # Notify callbacks
                    await self._notify_price_callbacks(mint, sol_price)
                    
        except Exception as e:
            self.logger.error(f"❌ Error processing log data: {e}")
    
    async def _extract_price_from_logs(self, logs: List[str], signature: str) -> Optional[Dict]:
        """Extract price information from swap logs."""
        try:
            # This is a simplified price extraction
            # In a real implementation, you'd parse the specific DEX instruction data
            
            for log in logs:
                # Look for PumpFun swap pattern
                if "Program log: Instruction: Swap" in log:
                    # Try to extract amounts from subsequent logs
                    # This is a placeholder - real implementation would parse instruction data
                    return await self._estimate_price_from_context(logs, signature)
                    
                # Look for Raydium swap pattern
                if "Program log: ray_log" in log and "swap" in log.lower():
                    return await self._estimate_price_from_context(logs, signature)
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error extracting price from logs: {e}")
            return None
    
    async def _estimate_price_from_context(self, logs: List[str], signature: str) -> Optional[Dict]:
        """Estimate price from log context (simplified implementation)."""
        try:
            # This is a placeholder implementation
            # In reality, you'd need to:
            # 1. Parse the transaction instruction data
            # 2. Decode the swap amounts
            # 3. Calculate the price ratio
            
            # For now, return None to indicate we need more sophisticated parsing
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error estimating price: {e}")
            return None
    
    async def _fetch_api_prices_loop(self):
        """Periodically fetch API prices for comparison."""
        while self.is_running:
            try:
                for token in self.monitored_tokens:
                    mint = token.get("mint")
                    if mint:
                        # Get SOL price from Jupiter API
                        sol_price = await self.price_monitor.get_current_price_sol(mint, max_age_seconds=60)
                        if sol_price and sol_price > 0:
                            self.api_prices[mint] = sol_price
                            
                            # Get token symbol
                            symbol = token.get("symbol", "UNKNOWN")
                            self.logger.debug(f"📊 {symbol} API price: {sol_price:.10f} SOL")
                
                # Wait 30 seconds before next fetch
                await asyncio.sleep(30)
                
            except Exception as e:
                self.logger.error(f"❌ Error fetching API prices: {e}")
                await asyncio.sleep(30)
    
    async def _notify_price_callbacks(self, mint: str, sol_price: float):
        """Notify all registered callbacks about price updates."""
        for callback in self.price_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(mint, sol_price)
                else:
                    callback(mint, sol_price)
            except Exception as e:
                self.logger.error(f"❌ Error in price callback: {e}")
    
    def get_price_comparison_data(self) -> List[Dict]:
        """Get current price comparison data for the dashboard."""
        comparison_data = []
        
        for token in self.monitored_tokens:
            mint = token.get("mint")
            symbol = token.get("symbol", "UNKNOWN")
            
            if mint:
                blockchain_price = self.blockchain_prices.get(mint)
                api_price = self.api_prices.get(mint)
                
                matching = False
                difference_pct = None
                
                if blockchain_price and api_price and blockchain_price > 0 and api_price > 0:
                    difference_pct = abs((blockchain_price - api_price) / api_price) * 100
                    matching = difference_pct < 5.0  # Consider matching if within 5%
                
                comparison_data.append({
                    "symbol": symbol,
                    "mint": mint,
                    "blockchain_price_sol": blockchain_price,
                    "api_price_sol": api_price,
                    "matching": matching,
                    "difference_pct": difference_pct,
                    "last_update": self.last_price_update.get(mint)
                })
        
        return comparison_data 