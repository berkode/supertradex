#!/usr/bin/env python3
"""
SUPERTRADEX using SYNTHRON CRYPTO TRADER codebase
"""
import sys
import asyncio
import pandas as pd
import time
import logging
import os
import json
from pathlib import Path
from datetime import datetime, timezone
import signal
import httpx
from dotenv import load_dotenv, dotenv_values
import io
from solana.rpc.async_api import AsyncClient
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Type, Dict, Any
import aiohttp
from config.settings import EncryptionSettings
from sqlalchemy import select, desc, asc
from fastapi import FastAPI
from dataclasses import dataclass

# Add project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# --- Centralized Imports (Grouped) ---
# Configuration
from config import Settings
from config.logging_config import LoggingConfig
from config.solana_config import SolanaConfig
from config.dexscreener_api import DexScreenerAPI
from config.thresholds import Thresholds
from config.filters_config import FiltersConfig

# Utilities
from utils.encryption import decrypt_env_file, test_encryption, get_encryption_password
from utils.circuit_breaker import CircuitBreaker
from utils.proxy_manager import ProxyManager
from utils.helpers import ensure_directory_exists, setup_output_dirs
from utils import get_logger, get_git_commit_hash
from utils.logger import get_logger

# Data Components
# Import DataPackage first
from data import DataPackage
from data.market_data import MarketData
# Then import individual components needed for external initialization
from data.token_database import TokenDatabase, Token
from data.price_monitor import PriceMonitor
from data.monitoring import VolumeMonitor, Monitoring # Import Monitoring here if needed externally
from data.blockchain_listener import BlockchainListener  # Add import for BlockchainListener
# MonitoringSimple is no longer needed, we're using MarketData instead
# from data.monitoring_simple import MonitoringSimple  # Import our simplified monitoring class
# No need to import components initialized *inside* DataPackage unless used directly elsewhere
# Import TokenMetrics
from data.token_metrics import TokenMetrics # Added import
from data.platform_tracker import PlatformTracker # Added import for PlatformTracker
from data.data_processing import DataProcessing
from data.data_fetcher import DataFetcher
from data.delta_calculator import DeltaCalculator
from data.indicators import Indicators # Added this import
from data.token_scanner import TokenScanner # Added import for TokenScanner

# Filter Components
from filters.whitelist import Whitelist
from filters.blacklist import Blacklist # Added import
from filters import FilterManager # Import manager
# Import components needed for FilterManager initialization
from filters.twitter_check import TwitterCheck
# No need to import individual filters if only used via FilterManager config

# API Clients (Specific Examples)
from config.rugcheck_api import RugcheckAPI
from filters.solsniffer_api import SolsnifferAPI
from data.solanatracker_api import SolanaTrackerAPI

# Execution Components
from execution.trade_queue import TradeQueue
from execution.order_manager import OrderManager
from execution.transaction_tracker import TransactionTracker
from execution.trade_scheduler import TradeScheduler, TradeTrigger, TriggerType # Added Trigger imports

# Strategy Components
from strategies.entry_exit import EntryExitStrategy
from strategies.risk_management import RiskManagement, TokenRiskMonitor
from strategies.position_management import PositionManagement
from strategies.alert_system import AlertSystem
from strategies.paper_trading import PaperTrading
# Add StrategySelector import
from strategies.strategy_selector import StrategySelector
from strategies import StrategyEvaluator # ADDED - to import the correct one

# Wallet Components
from wallet.wallet_manager import WalletManager
from wallet.balance_checker import BalanceChecker
from wallet.trade_validator import TradeValidator

# Import additional components needed for focused monitoring
from strategies.paper_trading import PaperTrading
from data.blockchain_listener import BlockchainListener
from data.hybrid_monitoring_manager import HybridMonitoringManager, TokenPriority

@dataclass
class FocusedTokenData:
    symbol: str
    mint: str
    dex_id: str
    pair_address: str
    blockchain_price: Optional[float] = None
    price_monitor_price: Optional[float] = None
    last_blockchain_update: Optional[datetime] = None
    last_price_monitor_update: Optional[datetime] = None
    blockchain_update_count: int = 0
    price_monitor_update_count: int = 0

# --- Enhanced Focused Monitoring Manager with Pool-Specific Subscriptions ---
class FocusedMonitoringManager:
    def __init__(self, settings: Settings, market_data: MarketData, db: TokenDatabase):
        self.settings = settings
        self.market_data = market_data
        self.db = db
        self.logger = get_logger(__name__)
        
        # Connection manager for pool-specific WebSocket subscriptions
        from data.websocket_connection_manager import WebSocketConnectionManager
        self.connection_manager = WebSocketConnectionManager(settings, self.logger)
        
        # Hybrid subscription management
        self.pool_subscriptions: Dict[str, Dict] = {}  # pool_address -> subscription_info
        self.account_subscriptions: Dict[str, Dict] = {}  # account_address -> subscription_info
        self.monitored_tokens: Dict[str, FocusedTokenData] = {}
        
        # WebSocket connections for hybrid approach
        self.ws_connection = None
        self._next_request_id = 1
        
        # DEX parsers for price extraction
        self.parsers = {}
        
        # Task management
        self.message_processing_task = None
        self.pumpswap_monitoring_task = None
        
        # Data source tracking for hybrid approach
        self.data_sources = {
            "pool_events": 0,
            "account_changes": 0,
            "pumpswap_direct": 0,
            "total_events": 0
        }
        
        # PumpSwap direct price fetcher for immediate price access
        self.pumpswap_fetcher = None
        
    async def initialize_focused_monitoring(self):
        """Initialize focused monitoring with pool-specific subscriptions using MINT-BASED selection."""
        try:
            # Initialize DEX parsers
            from data import RaydiumV4Parser, PumpSwapParser, RaydiumClmmParser
            from config.blockchain_logging import setup_blockchain_logger
            from data.pumpswap_price_fetcher import PumpSwapPriceFetcher
            
            blockchain_logger = setup_blockchain_logger("FocusedMonitoring")
            
            self.parsers = {
                'raydium_v4': RaydiumV4Parser(self.settings, blockchain_logger),
                'pumpswap': PumpSwapParser(self.settings, blockchain_logger),
                'raydium_clmm': RaydiumClmmParser(self.settings, blockchain_logger)
            }
            
            # Initialize PumpSwap direct price fetcher for immediate price access
            self.pumpswap_fetcher = PumpSwapPriceFetcher(
                solana_client=self.market_data.solana_client,
                settings=self.settings,
                logger=self.logger
            )
            self.logger.info("🚀 PumpSwap direct price fetcher initialized")
            
            # Get tokens from database for focused monitoring (will be populated by TokenScanner)
            # Only monitor tokens that are already in the database and have valid pair addresses
            tokens = await self.db.get_valid_tokens()  # Get valid tokens from database
            
            # Limit to top 5 most promising tokens for focused monitoring
            if tokens:
                tokens = tokens[:5]
                
            for token in tokens:
                if token.pair_address and token.mint:
                    self.monitored_tokens[token.mint] = FocusedTokenData(
                        symbol=token.symbol,
                        mint=token.mint,
                        dex_id=token.dex_id,
                        pair_address=token.pair_address
                    )
                    self.logger.info(f"🎯 Selected {token.symbol} ({token.dex_id.upper()}) for focused monitoring")
                    self.logger.info(f"   Mint: {token.mint}")
                    self.logger.info(f"   Pool: {token.pair_address}")
            
            self.logger.info(f"✅ Focused monitoring initialized for {len(self.monitored_tokens)} tokens")
            
        except Exception as e:
            self.logger.error(f"Error initializing focused monitoring: {e}", exc_info=True)
    
    async def subscribe_to_pool_events(self):
        """Subscribe to specific pool events using WebSocket - Hybrid Approach."""
        try:
            # Establish a single WebSocket connection for pool subscriptions
            self.ws_connection = await self._establish_pool_subscription_connection()
            if not self.ws_connection:
                self.logger.error("Failed to establish WebSocket connection for pool subscriptions")
                return
            
            # Hybrid Approach: Subscribe to both pools and token accounts
            subscription_count = 0
            
            # 1. Subscribe to each pool (existing approach)
            for mint, token_data in self.monitored_tokens.items():
                await self._subscribe_to_pool(token_data.pair_address, token_data.dex_id, mint)
                subscription_count += 1
            
            # 2. NEW: Subscribe to token account changes (more efficient for price updates)
            for mint, token_data in self.monitored_tokens.items():
                await self._subscribe_to_token_account(mint, token_data.symbol)
                subscription_count += 1
            
            # 3. NEW: Subscribe to known DEX program accounts for broader coverage
            await self._subscribe_to_dex_programs()
            subscription_count += 3  # Raydium V4, CLMM, PumpFun
            
            self.logger.info(f"🔗 Hybrid subscriptions established: {subscription_count} total subscriptions")
            
            # Start message processing and store the task
            self.message_processing_task = asyncio.create_task(self._process_pool_messages())
            self.logger.info("📡 Hybrid message processing started")
            
        except Exception as e:
            self.logger.error(f"Error in hybrid pool subscription: {e}", exc_info=True)
    
    async def _subscribe_to_token_account(self, mint: str, symbol: str):
        """Subscribe to token account changes for more efficient price monitoring."""
        try:
            # Subscribe to the token mint account for metadata changes
            subscription_request = {
                "jsonrpc": "2.0",
                "id": f"token_account_{mint[:8]}",
                "method": "accountSubscribe",
                "params": [
                    mint,  # Token mint address
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed"
                    }
                ]
            }
            
            await self.ws_connection.send(json.dumps(subscription_request))
            self.logger.info(f"📡 Subscribed to token account: {symbol} ({mint[:8]}...)")
            
        except Exception as e:
            self.logger.error(f"Error subscribing to token account {mint}: {e}")
    
    async def _subscribe_to_dex_programs(self):
        """Subscribe to major DEX program accounts for broader transaction coverage with enhanced filtering."""
        try:
            # Set up blockchain logger
            from config.blockchain_logging import setup_blockchain_logger, log_connection_event
            blockchain_logger = setup_blockchain_logger("FocusedMonitoring")
            
            # Major Solana DEX program IDs - Subscribe to transaction logs instead of account changes
            dex_programs = {
                "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium V4",
                "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM", 
                "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "PumpFun"
            }
            
            for program_id, name in dex_programs.items():
                # Subscribe to logs that mention this program (more likely to catch swaps)
                subscription_request = {
                    "jsonrpc": "2.0",
                    "id": f"dex_logs_{name.lower().replace(' ', '_')}",
                    "method": "logsSubscribe",
                    "params": [
                        {
                            "mentions": [program_id]  # Any transaction involving this program
                        },
                        {
                            "commitment": "processed",  # Use processed for faster updates
                            "encoding": "jsonParsed",
                            "maxSupportedTransactionVersion": 0
                        }
                    ]
                }
                
                await self.ws_connection.send(json.dumps(subscription_request))
                
                # Log to blockchain log
                log_connection_event(blockchain_logger, "CONNECTION", f"Subscribed to {name} program logs ({program_id[:8]}...)")
                self.logger.info(f"📡 Subscribed to DEX program logs: {name} ({program_id[:8]}...)")
                
        except Exception as e:
            self.logger.error(f"Error subscribing to DEX programs: {e}")
    
    async def _establish_pool_subscription_connection(self):
        """Establish WebSocket connection with proper Helius → Solana → PriceMonitor fallback hierarchy."""
        try:
            import websockets
            from config.blockchain_logging import setup_blockchain_logger, log_connection_event
            blockchain_logger = setup_blockchain_logger("FocusedMonitoring")
            
            connection_attempts = [
                {
                    "name": "Helius",
                    "url": self.settings.SOLANA_WSS_URL,  # This is already derived with API key in settings
                    "timeout": 30,
                    "priority": 1
                },
                {
                    "name": "Solana Mainnet",
                    "url": "wss://api.mainnet-beta.solana.com/",
                    "timeout": 20,
                    "priority": 2
                },
                {
                    "name": "Alternative Solana",
                    "url": "wss://rpc.ankr.com/solana_ws",
                    "timeout": 15,
                    "priority": 3
                }
            ]
            
            for attempt in connection_attempts:
                try:
                    log_connection_event(blockchain_logger, "CONNECTION", f"Attempting connection to {attempt['name']}...")
                    self.logger.info(f"🔌 Trying {attempt['name']} WebSocket connection...")
                    
                    ws = await websockets.connect(
                        attempt["url"],
                        open_timeout=attempt["timeout"],
                        ping_interval=20,
                        ping_timeout=20
                    )
                    
                    # Test the connection with a simple request
                    test_request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getVersion"
                    }
                    await ws.send(json.dumps(test_request))
                    
                    # Wait for response to confirm connection is working
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        response_data = json.loads(response)
                        
                        if "result" in response_data:
                            log_connection_event(blockchain_logger, "SUCCESS", f"✅ {attempt['name']} connection successful!")
                            self.logger.info(f"✅ {attempt['name']} WebSocket connection established and tested")
                            return ws
                        else:
                            raise Exception(f"Invalid response from {attempt['name']}: {response_data}")
                            
                    except asyncio.TimeoutError:
                        raise Exception(f"Connection test timeout for {attempt['name']}")
                        
                except Exception as e:
                    log_connection_event(blockchain_logger, "ERROR", f"❌ {attempt['name']} failed: {e}")
                    self.logger.error(f"❌ {attempt['name']} connection failed: {e}")
                    
                    # Close failed connection
                    try:
                        if 'ws' in locals():
                            await ws.close()
                    except:
                        pass
                    
                    # Continue to next attempt
                    continue
            
            # If all WebSocket connections failed, log fallback to PriceMonitor only
            log_connection_event(blockchain_logger, "FALLBACK", "All WebSocket connections failed, falling back to PriceMonitor only")
            self.logger.error("❌ All WebSocket connections failed. Falling back to PriceMonitor-only mode.")
            
            # Set a flag to indicate PriceMonitor-only mode
            self._fallback_to_price_monitor_only = True
            
            return None
            
        except Exception as e:
            self.logger.error(f"Critical error in connection establishment: {e}")
            return None
    
    async def _subscribe_to_pool(self, pool_address: str, dex_id: str, mint: str):
        """Subscribe to events for a specific pool address with enhanced filtering."""
        try:
            if not self.ws_connection:
                return

            # Set up blockchain logger
            from config.blockchain_logging import setup_blockchain_logger, log_connection_event
            blockchain_logger = setup_blockchain_logger("FocusedMonitoring")
            
            # Enhanced pool-specific subscription with broader filters to catch more events
            subscription_request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id,
                "method": "logsSubscribe",
                "params": [
                    {
                        "mentions": [pool_address]  # Subscribe to this specific pool
                    },
                    {
                        "commitment": "confirmed",  # Use confirmed for more reliable data
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            }
            
            await self.ws_connection.send(json.dumps(subscription_request))
            
            # Store subscription info
            self.pool_subscriptions[pool_address] = {
                "request_id": self._next_request_id,
                "dex_id": dex_id,
                "token_mint": mint,
                "pool_address": pool_address
            }
            
            # Log to blockchain log
            log_connection_event(blockchain_logger, "CONNECTION", f"Subscribed to {dex_id.upper()} pool {pool_address[:8]}... for {mint[:8]}...")
            
            self._next_request_id += 1
            self.logger.info(f"📡 Subscribed to pool {pool_address[:8]}... for {mint[:8]}... ({dex_id.upper()})")
            
        except Exception as e:
            self.logger.error(f"Error subscribing to pool {pool_address}: {e}")
    
    async def _process_pool_messages(self):
        """Process incoming WebSocket messages for pool events with reconnection logic."""
        reconnect_attempts = 0
        max_reconnect_attempts = 5
        base_reconnect_delay = 5  # seconds
        
        while True:  # Infinite loop with reconnection logic
            try:
                self.logger.info("🔄 Starting pool message processing loop...")
                
                # Ensure we have a valid connection
                connection_is_closed = True
                if self.ws_connection:
                    if hasattr(self.ws_connection, 'closed'):
                        connection_is_closed = self.ws_connection.closed
                    else:
                        # Assume connection is valid if we can't check closed status
                        connection_is_closed = False
                
                if not self.ws_connection or connection_is_closed:
                    self.logger.warning("WebSocket connection not available, attempting to reconnect...")
                    self.ws_connection = await self._establish_pool_subscription_connection()
                    if not self.ws_connection:
                        raise ConnectionError("Failed to establish WebSocket connection")
                    
                    # Re-subscribe to all pools after reconnection
                    self.logger.info("♻️ Re-subscribing to all pools after reconnection...")
                    for mint, token_data in self.monitored_tokens.items():
                        await self._subscribe_to_pool(token_data.pair_address, token_data.dex_id, mint)
                    self.logger.info("✅ Re-subscribed to all pools successfully")
                
                # Reset reconnect attempts on successful connection
                reconnect_attempts = 0
                
                # Process messages
                async for message in self.ws_connection:
                    try:
                        data = json.loads(message)
                        self.logger.debug(f"📡 Received WebSocket message: {data}")
                        
                        # Handle different subscription types in hybrid approach
                        if "method" in data:
                            method = data["method"]
                            
                            if method == "logsNotification":
                                # Pool transaction logs (existing approach)
                                await self._handle_pool_message(data)
                            elif method == "accountNotification":
                                # Token account changes (new)
                                await self._handle_account_notification(data)
                            elif method == "programNotification":
                                # DEX program notifications (new)
                                await self._handle_program_notification(data)
                            else:
                                self.logger.debug(f"🔍 Unknown notification method: {method}")
                        elif "result" in data:
                            # Subscription confirmation
                            self.logger.debug(f"✅ Subscription confirmed: {data}")
                        else:
                            self.logger.debug(f"🔍 Unhandled message type: {data}")
                            
                    except json.JSONDecodeError as e:
                        self.logger.error(f"Failed to parse WebSocket message: {e}")
                    except Exception as e:
                        self.logger.error(f"Error processing WebSocket message: {e}")
                        
                self.logger.warning("WebSocket message stream ended")
                break
            except (ConnectionError, OSError, Exception) as e:
                reconnect_attempts += 1
                self.logger.error(f"Error in pool message processing loop (attempt {reconnect_attempts}): {e}")
                
                if reconnect_attempts >= max_reconnect_attempts:
                    self.logger.critical(f"Max reconnection attempts ({max_reconnect_attempts}) reached. Message processing disabled.")
                    break
                
                # Close the failed connection
                try:
                    if self.ws_connection:
                        # Check if connection has close method and isn't already closed
                        if hasattr(self.ws_connection, 'close'):
                            if not hasattr(self.ws_connection, 'closed') or not self.ws_connection.closed:
                                await self.ws_connection.close()
                except:
                    pass
                self.ws_connection = None
                
                # Wait before reconnecting (exponential backoff)
                delay = base_reconnect_delay * (2 ** (reconnect_attempts - 1))
                delay = min(delay, 60)  # Cap at 60 seconds
                self.logger.info(f"🔄 Waiting {delay} seconds before reconnection attempt {reconnect_attempts}...")
                await asyncio.sleep(delay)
        
        self.logger.warning("🛑 Pool message processing loop has ended")
    
    async def _handle_pool_message(self, data: Dict):
        """Handle a pool-specific WebSocket message."""
        try:
            # Check if this is a log notification
            if data.get("method") == "logsNotification":
                params = data.get("params", {})
                result = params.get("result", {})
                
                # Extract transaction logs
                logs = result.get("value", {}).get("logs", [])
                signature = result.get("value", {}).get("signature", "unknown")
                
                if logs:
                    self.logger.debug(f"📋 Processing logs for signature {signature[:16]}... ({len(logs)} log entries)")
                    # Find which pool this event is for
                    await self._process_pool_swap_logs(logs, signature)
                else:
                    self.logger.debug("📋 Received logsNotification with no logs")
                    
        except Exception as e:
            self.logger.error(f"Error handling pool message: {e}")
    
    async def _handle_account_notification(self, data: Dict):
        """Handle token account change notifications."""
        try:
            params = data.get("params", {})
            result = params.get("result", {})
            value = result.get("value", {})
            
            if value:
                # Account data changed - could indicate token supply changes, metadata updates, etc.
                account_data = value.get("data", {})
                lamports = value.get("lamports", 0)
                
                self.logger.debug(f"📊 Account notification: {account_data}")
                
                # Extract relevant price information if available
                if isinstance(account_data, dict) and "parsed" in account_data:
                    parsed_data = account_data["parsed"]
                    
                    # Track account changes for price correlation
                    self.data_sources["account_changes"] += 1
                    self.data_sources["total_events"] += 1
                    
                    self.logger.info(f"🏦 Token account update detected (Total account events: {self.data_sources['account_changes']})")
                    
        except Exception as e:
            self.logger.error(f"Error handling account notification: {e}")
    
    async def _handle_program_notification(self, data: Dict):
        """Handle DEX program notifications for broader transaction coverage."""
        try:
            # Set up blockchain logger
            from config.blockchain_logging import setup_blockchain_logger, log_connection_event
            blockchain_logger = setup_blockchain_logger("FocusedMonitoring")
            
            params = data.get("params", {})
            result = params.get("result", {})
            
            # For logsSubscribe on programs, we get logs in the result
            if "value" in result:
                value = result["value"]
                logs = value.get("logs", [])
                signature = value.get("signature", "unknown")
                
                if logs:
                    blockchain_logger.info(f"🔧 DEX PROGRAM ACTIVITY: {len(logs)} log entries in transaction {signature[:8]}...")
                    
                    # Process these logs the same way as pool logs
                    await self._process_pool_swap_logs(logs, signature)
                    
                    # Track program events
                    self.data_sources["total_events"] += 1
                else:
                    blockchain_logger.debug(f"Program notification with no logs: {signature[:8]}...")
            else:
                # Old program account data format
                account_data = result.get("account", {})
                pubkey = result.get("pubkey", "unknown")
                
                blockchain_logger.debug(f"🔧 Program account notification from {pubkey[:16]}...")
                
                # Process program-level transaction data
                if isinstance(account_data, dict) and "data" in account_data:
                    # Track program events
                    self.data_sources["total_events"] += 1
                    
                    # Try to extract swap information from program data
                    await self._process_program_swap_data(account_data, pubkey)
                    
        except Exception as e:
            self.logger.error(f"Error handling program notification: {e}")
    
    async def _process_program_swap_data(self, account_data: Dict, pubkey: str):
        """Process swap data from DEX program notifications."""
        try:
            data_content = account_data.get("data", [])
            
            if isinstance(data_content, list) and len(data_content) > 0:
                # Program data often contains swap instructions
                # This is a simplified approach - full implementation would decode the instruction data
                self.logger.debug(f"🔧 Processing program data from {pubkey[:8]}... (data length: {len(data_content)})")
                
                # For now, just count and log program-level events
                # Full implementation would:
                # 1. Decode instruction data based on program type
                # 2. Extract swap amounts and prices
                # 3. Update token prices accordingly
                
                self.logger.info(f"💱 DEX program activity detected on {pubkey[:8]}...")
                
        except Exception as e:
            self.logger.error(f"Error processing program swap data: {e}")
    
    async def _process_pool_swap_logs(self, logs: List[str], signature: str):
        """Process logs from pool events to extract price information with enhanced blockchain logging."""
        try:
            # Set up blockchain logger for real-time event tracking
            from config.blockchain_logging import setup_blockchain_logger, log_price_event, log_swap_event, log_connection_event
            blockchain_logger = setup_blockchain_logger("FocusedMonitoring")
            
            # Log the event processing start
            log_connection_event(blockchain_logger, "SUCCESS", f"Processing blockchain transaction {signature[:8]}... with {len(logs)} log entries")
            
            # Process and assign amounts intelligently
            for mint, token_data in self.monitored_tokens.items():
                dex_id = token_data.dex_id.lower()
                
                if dex_id in self.parsers:
                    parser = self.parsers[dex_id]
                    
                    try:
                        # Parse the swap logs (sync method, not async) with target mint
                        swap_data = parser.parse_swap_logs(logs, signature, target_mint=mint)
                        
                        # ✅ CRITICAL FIX: Verify the swap is for our target token
                        if swap_data and swap_data.get('found_swap'):
                            # Extract token mint from logs to verify this is for our token
                            extracted_mint = None
                            if hasattr(parser, '_extract_token_mint_from_logs'):
                                extracted_mint = parser._extract_token_mint_from_logs(logs, signature)
                            
                            # Only process if the swap is for our target token
                            if extracted_mint == mint or not extracted_mint:
                                # Continue with processing (extracted_mint match or couldn't extract, assume it's ours)
                                pass
                            else:
                                # Skip this swap as it's for a different token
                                blockchain_logger.debug(f"Skipping swap for different token: extracted {extracted_mint}, want {mint}")
                                continue
                        
                        if swap_data and swap_data.get('found_swap'):
                            blockchain_logger.info(f"🔄 SWAP DETECTED: {dex_id.upper()} parser found swap in transaction {signature[:8]}...")
                            
                            # ARCHITECTURE FIX: Delegate to MarketData instead of calculating here
                            # MarketData already has _update_realtime_token_state method that handles price conversion
                            await self.market_data._update_realtime_token_state(
                                mint_address=mint,
                                event_type='swap',
                                price=swap_data.get('price'),  # Parser already calculated this
                                raw_event_data=swap_data,
                                dex_id=dex_id,
                                pair_address=token_data.pair_address
                            )
                            
                            # Update local tracking
                            token_data.last_blockchain_update = datetime.now(timezone.utc)
                            token_data.blockchain_update_count += 1
                            
                            # Track pool events
                            self.data_sources["pool_events"] += 1
                            self.data_sources["total_events"] += 1
                            
                            # Get the processed price from MarketData's state (it handles USD conversion)
                            processed_price_sol = None
                            processed_price_usd = None
                            if hasattr(self.market_data, '_realtime_token_state'):
                                token_state = self.market_data._realtime_token_state.get(mint)
                                if token_state:
                                    processed_price_sol = token_state.get('last_price_sol')
                                    processed_price_usd = token_state.get('last_price_usd')
                                    token_data.blockchain_price = processed_price_sol  # Store SOL price as primary
                            
                            # Log the event with SOL as primary, USD as secondary
                            if processed_price_sol:
                                log_price_event(blockchain_logger, token_data.symbol, processed_price_sol, f"blockchain_{dex_id}", processed_price_usd)
                                log_swap_event(blockchain_logger, token_data.symbol, 0, processed_price_sol, dex_id.upper(), processed_price_usd)
                            
                            return  # Found price, no need to check other tokens
                        else:
                            # Only log if we actually got data back
                            if swap_data:
                                blockchain_logger.debug(f"Parser {dex_id} returned data but no swap found for {signature[:8]}...")
                            
                    except Exception as parser_error:
                        log_connection_event(blockchain_logger, "ERROR", f"Parser {dex_id} failed: {parser_error}")
                        if self.logger and dex_id and parser_error:
                            self.logger.error(f"Error in {dex_id} parser: {parser_error}")
                        elif self.logger:
                            self.logger.error(f"Error in parser: {parser_error or 'Unknown error'}")
                    else:
                        blockchain_logger.debug(f"No parser available for DEX {dex_id}")
                        
        except Exception as e:
            self.logger.error(f"Error processing pool swap logs: {e}")
    
    # REMOVED: All price calculation methods - using MarketData's existing infrastructure instead
    # The parsers already calculate prices and MarketData._update_realtime_token_state handles USD conversion

    async def update_price_monitor_prices(self):
        """Update prices from PriceMonitor for comparison."""
        try:
            for token_mint, token_data in self.monitored_tokens.items():
                # Get current price from PriceMonitor
                price = await self.market_data.price_monitor.get_current_price_usd(token_mint)
                
                if price is not None:
                    token_data.price_monitor_price = price
                    token_data.last_price_monitor_update = datetime.now(timezone.utc)
                    token_data.price_monitor_update_count += 1
                    
        except Exception as e:
            self.logger.error(f"Error updating PriceMonitor prices: {e}")

    def print_focused_comparison(self):
        """Print focused price comparison summary with hybrid approach statistics"""
        self.logger.info("\n" + "=" * 80)
        self.logger.info(f"📊 FOCUSED PRICE MONITORING SUMMARY - {datetime.now().strftime('%H:%M:%S')}")
        self.logger.info("=" * 80)
        
        # Show hybrid approach statistics
        self.logger.info(f"📡 HYBRID APPROACH STATISTICS:")
        self.logger.info(f"   🏊 Pool Events: {self.data_sources['pool_events']}")
        self.logger.info(f"   🏦 Account Changes: {self.data_sources['account_changes']}")
        self.logger.info(f"   📊 Total Blockchain Events: {self.data_sources['total_events']}")
        self.logger.info(f"   🔄 Data Coverage: {len(self.monitored_tokens)} tokens × 3 subscription types = {len(self.monitored_tokens) * 3} subscriptions")
        
        for mint, token_data in self.monitored_tokens.items():
            self.logger.info(f"\n🎯 {token_data.symbol} ({token_data.dex_id.upper()})")
            self.logger.info(f"   Mint: {mint[:16]}...")
            self.logger.info(f"   Pair: {token_data.pair_address[:16]}...")
            
            # Blockchain price info
            if token_data.blockchain_price is not None:
                blockchain_age = (datetime.now(timezone.utc) - token_data.last_blockchain_update).total_seconds()
                
                # Format SOL price as primary
                sol_price_str = f"{token_data.blockchain_price:.8f} SOL"
                
                # Get USD price if available from MarketData state
                usd_price_str = ""
                if hasattr(self.market_data, '_realtime_token_state'):
                    token_state = self.market_data._realtime_token_state.get(mint)
                    if token_state and token_state.get('last_price_usd'):
                        usd_price_str = f" (${token_state['last_price_usd']:.6f})"
                
                self.logger.info(f"   💰 Blockchain Price: {sol_price_str}{usd_price_str} ({blockchain_age:.0f}s ago)")
                self.logger.info(f"   📊 Blockchain Updates: {token_data.blockchain_update_count}")
            else:
                self.logger.info(f"   💰 Blockchain Price: No data yet")
            
            # PriceMonitor price info (assuming this gives USD prices)
            if token_data.price_monitor_price is not None:
                pm_age = (datetime.now(timezone.utc) - token_data.last_price_monitor_update).total_seconds()
                self.logger.info(f"   📈 PriceMonitor Price: ${token_data.price_monitor_price:.8f} ({pm_age:.0f}s ago)")
                self.logger.info(f"   📊 PriceMonitor Updates: {token_data.price_monitor_update_count}")
            else:
                self.logger.info(f"   📈 PriceMonitor Price: No data yet")
            
            # Price difference (compare USD prices if both available)
            blockchain_usd = None
            if hasattr(self.market_data, '_realtime_token_state'):
                token_state = self.market_data._realtime_token_state.get(mint)
                if token_state:
                    blockchain_usd = token_state.get('last_price_usd')
            
            if blockchain_usd and token_data.price_monitor_price:
                diff_pct = ((blockchain_usd - token_data.price_monitor_price) / token_data.price_monitor_price) * 100
                diff_indicator = "📈" if diff_pct > 0 else "📉" if diff_pct < 0 else "➡️"
                self.logger.info(f"   🔄 Difference: {diff_pct:+.2f}% {diff_indicator} (Blockchain USD vs PriceMonitor)")
            else:
                self.logger.info(f"   🔄 Difference: Waiting for comparable data...")
                
            # Data source efficiency
            reliability_score = "🟢 HIGH" if token_data.blockchain_update_count > 0 else "🟡 MEDIUM" if self.data_sources['total_events'] > 0 else "🔴 LOW"
            self.logger.info(f"   📡 Data Reliability: {reliability_score}")
        
        # Summary of hybrid approach effectiveness
        self.logger.info(f"\n🔬 HYBRID APPROACH EFFECTIVENESS:")
        if self.data_sources['total_events'] > 0:
            pool_ratio = (self.data_sources['pool_events'] / self.data_sources['total_events']) * 100
            account_ratio = (self.data_sources['account_changes'] / self.data_sources['total_events']) * 100
            self.logger.info(f"   📊 Pool Events: {pool_ratio:.1f}% of total")
            self.logger.info(f"   📊 Account Events: {account_ratio:.1f}% of total")
            self.logger.info(f"   📊 Event Rate: {self.data_sources['total_events']} events captured")
        else:
            self.logger.info(f"   ⏳ Waiting for blockchain events...")
        
        self.logger.info("\n" + "=" * 80)
    
    async def update_price_monitor_display(self):
        """Update and display PriceMonitor prices with change indicators."""
        try:
            for token_mint, token_data in self.monitored_tokens.items():
                # Get current price from PriceMonitor
                price = await self.market_data.price_monitor.get_current_price_usd(token_mint)
                
                if price is not None:
                    old_price = token_data.price_monitor_price
                    token_data.price_monitor_price = price
                    token_data.last_price_monitor_update = datetime.now(timezone.utc)
                    token_data.price_monitor_update_count += 1
                    
                    if old_price is not None:
                        change = ((price - old_price) / old_price) * 100
                        direction = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                        self.logger.info(f"💰 {token_data.symbol}: ${price:.8f} {direction} ({change:+.2f}%)")
                    else:
                        self.logger.info(f"💰 {token_data.symbol}: ${price:.8f} (initial)")
                     
        except Exception as e:
            self.logger.error(f"Error updating PriceMonitor display: {e}")

# Define helper function for updating env vars BEFORE it's called
def update_dotenv_vars(env_vars: dict, override: bool = False) -> None:
    """Update os.environ with the given environment variables."""
    # Check if the logger is already configured, otherwise print
    global logger # Access the globally defined logger
    log_func = logger.debug if logger and logger.hasHandlers() else print

    updated_count = 0
    skipped_count = 0
    for key, value in env_vars.items():
        if value is None: # Skip if value is None
             log_func(f"Skipping None value for env var: {key}")
             skipped_count += 1
             continue

        value_str = str(value) # Ensure value is string

        if override or key not in os.environ:
            os.environ[key] = value_str
            # Mask sensitive keys before logging
            log_value = value_str[:3] + '...' + value_str[-3:] if len(value_str) > 6 and ('KEY' in key.upper() or 'SECRET' in key.upper() or 'PASSWORD' in key.upper()) else value_str
            log_func(f"Set env var: {key}={log_value}")
            updated_count += 1
        else:
            log_func(f"Skipped env var (already exists, override=False): {key}")
            skipped_count += 1
    log_func(f"Env var update: {updated_count} set, {skipped_count} skipped.")

# Initialize logger early for startup messages
logger = logging.getLogger(__name__)

# --- Constants ---
ENV_DIR = project_root / "config"
ENV_PLAIN_PATH = ENV_DIR / ".env"
ENV_ENCRYPTED_PATH = ENV_DIR / ".env.encrypted"

# Maximum runtime in seconds (e.g., 24 hours). None for indefinite.
MAX_RUNTIME_SECONDS = None

# --- Environment Variable Loading Logic ---
print("--- Loading Environment Variables --- ")
variables_loaded_count = 0

# 1. Try getting encryption password
password = None

# Load the key-file path from our config layer
key_settings = EncryptionSettings()
key_file_to_use = key_settings.ENCRYPTION_KEY_PATH
print(f"INFO: Using key filename for password retrieval: {key_file_to_use}")
try:
    password = get_encryption_password()
    if password:
        print("INFO: Successfully retrieved encryption password from stored key.")
    else:
        # Fallback to environment variable if stored password retrieval failed
        password = os.getenv("ENCRYPTION_PASSWORD")
        if password:
            print("INFO: Using encryption password from ENCRYPTION_PASSWORD environment variable.")
        else:
            print("INFO: No stored or environment encryption password found.")
except Exception as e:
    print(f"ERROR: Could not retrieve encryption password: {e}")

# 2. Try loading encrypted file first (if password available)
if ENV_ENCRYPTED_PATH.exists():
    print(f"INFO: Found encrypted environment file: {ENV_ENCRYPTED_PATH}")
    if password:
        print(f"INFO: Attempting decryption using password.")
        try:
            decrypted_content = decrypt_env_file(ENV_ENCRYPTED_PATH, password)
            if decrypted_content:
                loaded_vars = dotenv_values(stream=io.StringIO(decrypted_content))
                print(f"INFO: Found {len(loaded_vars)} variables in decrypted content. Updating environment (non-override)...")
                update_dotenv_vars(loaded_vars, override=False)
                print("INFO: Environment updated successfully from decrypted .env.encrypted.")
        except Exception as e:
            print(f"ERROR: Failed to decrypt or load {ENV_ENCRYPTED_PATH} using password: {e}", exc_info=True)
    else:
        print(f"WARNING: Encrypted file {ENV_ENCRYPTED_PATH} exists but no encryption password was available to decrypt it.")                      
else:
    print(f"INFO: Encrypted environment file not found: {ENV_ENCRYPTED_PATH}")

# 3. Load plain .env file (overrides anything loaded from encrypted file)
if ENV_PLAIN_PATH.exists():
    print(f"INFO: Loading plain environment file (with override): {ENV_PLAIN_PATH}")
    try:
        loaded_plain_count = load_dotenv(dotenv_path=ENV_PLAIN_PATH, override=True)
        if loaded_plain_count:
            # Only increment count if encrypted wasn't loaded
            if variables_loaded_count == 0:
                variables_loaded_count += 1
                print(f"INFO: Successfully loaded/overridden variables from plain file: {ENV_PLAIN_PATH}")
            else:
                 print(f"INFO: Plain file {ENV_PLAIN_PATH} loaded, but encrypted vars took precedence (override=True still applies).")
        else:
            print(f"WARNING: Plain environment file {ENV_PLAIN_PATH} exists but failed to load/override any variables.")
    except Exception as e:
        print(f"ERROR: Failed loading plain env file {ENV_PLAIN_PATH}: {e}")
else:
    print(f"INFO: Plain environment file not found: {ENV_PLAIN_PATH}")

if variables_loaded_count == 0:
    print("WARNING: No environment variables loaded from config/.env or config/.env.encrypted. Relying on system environment.")
print("--- Environment Variable Loading Complete --- ")


# --- Settings and Logging Setup (Initialize AFTER loading ALL env vars) ---
try:
    settings = Settings()
    LoggingConfig.setup_logging(settings=settings)
    logger = logging.getLogger(__name__) # Re-get logger after setup
    
    # Setup specialized loggers for prices and trades
    from config.logging_config import setup_specialized_loggers
    price_logger, trade_logger = setup_specialized_loggers()
    logger.info("📊 Specialized loggers initialized: prices.log and trades.log")
    # --- Explicitly set websockets logger level to INFO ---
    websockets_logger = logging.getLogger('websockets')
    websockets_logger.setLevel(logging.INFO)
    # Optional: Ensure handlers also respect this level if they have their own level set higher
    # for handler in websockets_logger.handlers:
    #     handler.setLevel(logging.INFO)
    # # Propagate setting to root handlers if no specific handlers are attached 
    # if not websockets_logger.handlers:
    #    for handler in logging.getLogger().handlers:
    #        # Be careful not to lower the level of handlers meant for higher levels (e.g., ERROR file handler)
    #        # This part might be unnecessary if root handlers are already at INFO or DEBUG
    #        pass # Usually inheriting from root is sufficient
    logger.info("Websockets logger level forced to INFO.") # Add log message
    # -----------------------------------------------------
    # --- REMOVED Explicit TokenScanner Debug Setting --- ## REMOVED ##
    # token_scanner_logger = logging.getLogger('data.token_scanner')
    # token_scanner_logger.setLevel(logging.DEBUG)
    # --- Added Debug Setting for MarketData --- #
    logging.getLogger('data.market_data').setLevel(logging.DEBUG)
    logger.info("Logging configured successfully.")
    logger.info("Settings loaded and Logging configured.")
except ValueError as e:
    initial_logger = logging.getLogger("startup_error")
    initial_logger.error(f"CRITICAL ERROR: Missing required environment variable: {e}. Check .env files. Exiting.")
    print("--- Loaded Environment Variables (at time of error) ---")
    debug_vars = {k: (v[:3] + '...' + v[-3:] if isinstance(v, str) and len(v)>6 and ('KEY' in k or 'SECRET' in k or 'PASSWORD' in k) else v) for k, v in os.environ.items()}
    print(json.dumps(debug_vars, indent=2))
    print("--- End Loaded Environment Variables --- ")
    sys.exit(1)
except Exception as e:
    initial_logger = logging.getLogger("startup_error")
    initial_logger.error(f"CRITICAL ERROR during Settings initialization: {e}. Exiting.", exc_info=True)
    sys.exit(1)


# --- Helper Function for Graceful Shutdown ---
async def close_all_components(components_dict: dict):
    """Safely closes components listed in the dictionary."""
    logger.info("--- Closing All Components ---")
    # Close in reverse order of initialization or based on dependencies
    
    # Close StrategyEvaluator first if it depends on MarketData, DB etc.
    strategy_evaluator = components_dict.get("strategy_evaluator")
    if strategy_evaluator and hasattr(strategy_evaluator, 'close') and callable(getattr(strategy_evaluator, 'close')):
        try:
            logger.info("Closing StrategyEvaluator...")
            await strategy_evaluator.close()
            logger.info("StrategyEvaluator closed.")
        except Exception as e:
            logger.error(f"Error closing StrategyEvaluator: {e}", exc_info=True)

    # Close TradeExecutor
    trade_executor = components_dict.get("trade_executor")
    if trade_executor and hasattr(trade_executor, 'close') and callable(getattr(trade_executor, 'close')):
        try:
            logger.info("Closing TradeExecutor...")
            await trade_executor.close() # Assuming it has an async close
            logger.info("TradeExecutor closed.")
        except Exception as e:
            logger.error(f"Error closing TradeExecutor: {e}", exc_info=True)

    # Close TokenScanner
    token_scanner = components_dict.get("token_scanner")
    if token_scanner and hasattr(token_scanner, 'close') and callable(getattr(token_scanner, 'close')):
        try:
            logger.info("Closing TokenScanner...")
            await token_scanner.close()
            logger.info("TokenScanner closed.")
        except Exception as e:
            logger.error(f"Error closing TokenScanner: {e}", exc_info=True)

    # Close MarketData
    market_data = components_dict.get("market_data")
    if market_data and hasattr(market_data, 'close') and callable(getattr(market_data, 'close')):
        try:
            logger.info("Closing MarketData...")
            await market_data.close()
            logger.info("MarketData closed.")
        except Exception as e:
            logger.error(f"Error closing MarketData: {e}", exc_info=True)
            
    # Close WalletManager
    wallet_manager = components_dict.get("wallet_manager")
    if wallet_manager and hasattr(wallet_manager, 'close') and callable(getattr(wallet_manager, 'close')):
        try:
            logger.info("Closing WalletManager...")
            await wallet_manager.close()
            logger.info("WalletManager closed.")
        except Exception as e:
            logger.error(f"Error closing WalletManager: {e}", exc_info=True)

    # Close Hybrid Monitoring Manager
    hybrid_monitoring = components_dict.get("hybrid_monitoring")
    if hybrid_monitoring and hasattr(hybrid_monitoring, 'close') and callable(getattr(hybrid_monitoring, 'close')):
        try:
            logger.info("Closing HybridMonitoringManager...")
            await hybrid_monitoring.close()
            logger.info("HybridMonitoringManager closed.")
        except Exception as e:
            logger.error(f"Error closing HybridMonitoringManager: {e}", exc_info=True)
    
    # Close Enhanced PumpSwap Parser Stream
    helius_pump_parser = components_dict.get("helius_pump_parser")
    if helius_pump_parser and hasattr(helius_pump_parser, 'stop_helius_pump_stream') and callable(getattr(helius_pump_parser, 'stop_helius_pump_stream')):
        try:
            logger.info("Stopping Helius Pump AMM stream...")
            await helius_pump_parser.stop_helius_pump_stream()
            logger.info("Helius Pump AMM stream stopped.")
        except Exception as e:
            logger.error(f"Error stopping Helius Pump AMM stream: {e}", exc_info=True)

    # Close Blockchain Listener
    blockchain_listener = components_dict.get("blockchain_listener")
    if blockchain_listener and hasattr(blockchain_listener, 'close') and callable(getattr(blockchain_listener, 'close')):
        try:
            logger.info("Closing BlockchainListener...")
            await blockchain_listener.close()
            logger.info("BlockchainListener closed.")
        except Exception as e:
            logger.error(f"Error closing BlockchainListener: {e}", exc_info=True)

    # Close Database
    db = components_dict.get("db")
    if db and hasattr(db, 'close') and callable(getattr(db, 'close')):
        try:
            logger.info("Closing TokenDatabase...")
            await db.close()
            logger.info("TokenDatabase closed.")
        except Exception as e:
            logger.error(f"Error closing TokenDatabase: {e}", exc_info=True)

    # Close HTTP Client
    http_client = components_dict.get("http_client")
    if http_client and hasattr(http_client, 'aclose') and callable(getattr(http_client, 'aclose')):
        try:
            logger.info("Closing HTTPX Client...")
            await http_client.aclose()
            logger.info("HTTPX Client closed.")
        except Exception as e:
            logger.error(f"Error closing HTTPX Client: {e}", exc_info=True)
            
    # Close Solana Client
    solana_client = components_dict.get("solana_client")
    if solana_client and hasattr(solana_client, 'close') and callable(getattr(solana_client, 'close')):
        try:
            logger.info("Closing Solana Client...")
            await solana_client.close() # Ensure this is the correct close method
            logger.info("Solana Client closed.")
        except Exception as e:
            logger.error(f"Error closing Solana Client: {e}", exc_info=True)
            
    # Close SolanaTrackerAPI
    solana_tracker_api = components_dict.get("solana_tracker_api")
    if solana_tracker_api and hasattr(solana_tracker_api, 'close') and callable(getattr(solana_tracker_api, 'close')):
        try:
            logger.info("Closing SolanaTrackerAPI...")
            await solana_tracker_api.close()
            logger.info("SolanaTrackerAPI closed.")
        except Exception as e:
            logger.error(f"Error closing SolanaTrackerAPI: {e}", exc_info=True)

    # Close PlatformTracker
    platform_tracker = components_dict.get("platform_tracker")
    if platform_tracker and hasattr(platform_tracker, 'close') and callable(getattr(platform_tracker, 'close')):
        try:
            logger.info("Closing PlatformTracker...")
            await platform_tracker.close()
            logger.info("PlatformTracker closed.")
        except Exception as e:
            logger.error(f"Error closing PlatformTracker: {e}", exc_info=True)

    # Example for other components if they have close methods
    # filter_manager = components_dict.get("filter_manager")
    # if filter_manager and hasattr(filter_manager, 'close'):
    # try:
    # logger.info("Closing FilterManager...")
    # await filter_manager.close()
    # logger.info("FilterManager closed.")
    # except Exception as e:
    # logger.error(f"Error closing FilterManager: {e}", exc_info=True)

    logger.info("--- All Components Closed ---")


async def signal_handler_async(shutdown_event: asyncio.Event, 
                               logger_instance: logging.Logger):
    """Coroutine to handle signals by setting the shutdown event."""
    if shutdown_event.is_set():
        logger_instance.info("signal_handler_async: Shutdown already in progress.")
        return

    logger_instance.info("signal_handler_async: Signal received, setting shutdown_event. Main `finally` block will handle component cleanup and handler restoration.")
    shutdown_event.set()


# --- Unified Asynchronous Component Initialization Function ---
async def initialize_components(settings: Settings) -> dict:
    """Initializes and returns all core application components."""
    logger.info("--- Initializing Core Components ---")
    start_time = time.time()
    
    # Initialize basic utilities
    proxy_manager = ProxyManager(settings.PROXY_FILE_PATH) if settings.USE_PROXIES else None
    if proxy_manager:
        logger.info(f"ProxyManager initialized. {len(proxy_manager.get_all_proxies())} proxies loaded.")

    # Setup HTTP client session (aiohttp or httpx based on preference)
    # Using httpx as an example, compatible with proxy_manager
    if proxy_manager:
        # If using proxies, get a proxy URL for the client to use
        proxy_url = proxy_manager.get_proxy_url()
        if proxy_url:
            transport = httpx.AsyncHTTPTransport(proxy_url=proxy_url)
            http_client = httpx.AsyncClient(transport=transport, timeout=settings.HTTP_TIMEOUT)
            logger.info(f"HTTPX AsyncClient initialized with proxy: {proxy_url}")
        else:
            http_client = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT)
            logger.info("HTTPX AsyncClient initialized without proxy (no valid proxies available)")
    else:
        http_client = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT)
        logger.info("HTTPX AsyncClient initialized without proxy manager")
    logger.info(f"HTTPX AsyncClient initialized. Timeout: {settings.HTTP_TIMEOUT}s")

    # Initialize Solana client
    solana_client = AsyncClient(settings.SOLANA_RPC_URL)
    logger.info(f"Solana AsyncClient initialized for endpoint: {settings.SOLANA_RPC_URL}")

    # --- Database Initialization ---
    db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
    if not db:
        logger.critical("Failed to initialize TokenDatabase. Exiting.")
        raise RuntimeError("Failed to initialize TokenDatabase.")
    logger.info(f"TokenDatabase initialized with DB: {settings.DATABASE_FILE_PATH}")
    
    # --- Configuration Objects ---
    thresholds = Thresholds(settings=settings)
    logger.info("Thresholds initialized.")
    filters_config = FiltersConfig(settings=settings, thresholds=thresholds)
    logger.info("FiltersConfig initialized.")

    # --- Wallet Manager ---
    wallet_manager = WalletManager(settings=settings, solana_client=solana_client, db=db)
    await wallet_manager.initialize() # Initialize and load keypair
    logger.info("WalletManager initialized.")

    # Initialize shared HTTP and Solana clients
    # ... (http_client, solana_client, proxy_manager initialization) ...

    # Initialize main DexScreenerAPI client (SHARED INSTANCE)
    logger.info("Initializing main DexScreenerAPI client...")
    dexscreener_api = DexScreenerAPI(settings, proxy_manager=proxy_manager)
    if not await dexscreener_api.initialize():
        logger.critical("Failed to initialize main DexScreenerAPI client. Exiting.")
        # Perform necessary cleanup before exiting
        if proxy_manager: await proxy_manager.close_session() # Close proxy manager's session if it has one
        if http_client: await http_client.aclose()
        if solana_client: await solana_client.close() # Changed to .close()
        if db: await db.close() 
        # No other dexscreener_api instance to close here yet
        return None # Return None on initialization failure
    logger.info("Main DexScreenerAPI client initialized successfully.")

    # Initialize MarketData, pass the SHARED dexscreener_api
    logger.info("Initializing MarketData...")
    market_data = MarketData(settings, dexscreener_api=dexscreener_api, token_db=db, http_client=http_client, solana_client=solana_client)
    if not await market_data.initialize():
        logger.critical("Failed to initialize MarketData. Exiting.")
        # Perform necessary cleanup before exiting
        await dexscreener_api.close() # Close the shared instance
        if proxy_manager: await proxy_manager.close_session()
        if http_client: await http_client.aclose()
        if solana_client: await solana_client.close() # Changed to .close()
        if db: await db.close()
        return None
    logger.info("MarketData initialized successfully.")
    
    # Initialize other components like FilterManager, TokenMetrics, APIs...
    # (Existing code for FilterManager, TokenMetrics, RugcheckAPI, SolsnifferAPI, TwitterCheck)
    # ...

    # Initialize main DexScreenerAPI client (SHARED INSTANCE)
    # ... (dexscreener_api initialization) ...

    # Initialize MarketData, pass the SHARED dexscreener_api
    # ... (market_data initialization) ...

    # --- Initialize components needed by FilterManager and TokenScanner ---
    logger.info("Initializing API clients for FilterManager...")
    rugcheck_api = RugcheckAPI(settings=settings, proxy_manager=proxy_manager)
    logger.info("RugcheckAPI initialized.")
    # SolsnifferAPI only accepts settings
    solsniffer_api = SolsnifferAPI(settings=settings) 
    logger.info("SolsnifferAPI initialized.")
    # TwitterCheck accepts settings and thresholds
    twitter_check = TwitterCheck(settings=settings, thresholds=thresholds)
    await twitter_check.initialize()  # TwitterCheck has async initialize
    logger.info("TwitterCheck initialized.")

    logger.info("Initializing FilterManager...")
    filter_manager = FilterManager(
        settings=settings,
        thresholds=thresholds,
        filters_config=filters_config,
        db=db,
        http_client=http_client, 
        solana_client=solana_client, 
        price_monitor=market_data.price_monitor, # Get from MarketData
        rugcheck_api=rugcheck_api,
        solsniffer_api=solsniffer_api,
        twitter_check=twitter_check
    )
    logger.info("FilterManager initialized successfully.")

    logger.info("Initializing TokenMetrics...")
    # TokenMetrics needs many components that we haven't initialized yet
    # For now, let's skip TokenMetrics initialization and continue with other components
    # token_metrics = TokenMetrics(...)
    token_metrics = None  # Placeholder - will be initialized later
    logger.info("TokenMetrics initialization deferred (missing dependencies).") 
    # --- End FilterManager and TokenScanner dependencies ---

    # TokenScanner initialization will be moved after TokenMetrics is properly initialized
    token_scanner = None  # Placeholder - will be initialized later
    logger.info("TokenScanner initialization deferred until TokenMetrics is ready.")

    # Initialize PlatformTracker (after TokenScanner if it depends on it, or in parallel if not)
    logger.info("Initializing PlatformTracker...")
    # PlatformTracker expects: db, settings, thresholds, solana_client
    platform_tracker = PlatformTracker(db, settings, thresholds, solana_client)
    if not await platform_tracker.initialize():
        logger.critical("Failed to initialize PlatformTracker. Exiting.")
        # ... (full cleanup) ...
        return None
    logger.info("PlatformTracker initialized successfully.")

    # Skip DataPackage for now - it's causing TokenMetrics initialization issues
    # All necessary components are already initialized above
    logger.info("Skipping DataPackage initialization (not required for basic functionality).")
    data_package = None

    # Initialize trade queue

    # --- Execution Components (needed by StrategyComponents) ---
    balance_checker = BalanceChecker(
        solana_client=solana_client,
        wallet_pubkey=wallet_manager.get_public_key(),
        http_client=http_client,
        settings=settings
    )
    trade_validator = TradeValidator(balance_checker=balance_checker, settings=settings)
    order_manager = OrderManager(
        settings=settings,
        solana_client=solana_client,
        db=db,
        wallet_manager=wallet_manager,
        http_client=http_client,
        trade_validator=trade_validator,
        price_monitor=market_data.price_monitor # price_monitor comes from market_data
    )
    trade_queue = TradeQueue(order_manager=order_manager)
    # Initialize TransactionTracker here as it can be needed by other strategy components initialized shortly
    transaction_tracker = TransactionTracker(settings=settings, solana_client=solana_client, db=db)
    logger.info("Core execution components (BalanceChecker, TradeValidator, OrderManager, TradeQueue, TransactionTracker) initialized.")

    # --- Strategy Components ---
    # Initialize AlertSystem first as it's a dependency for RiskMgmt and PositionMgmt
    alert_system = AlertSystem() # AlertSystem initializes its own settings and does not take db/thresholds
    logger.info("AlertSystem initialized.")

    # Initialize Blacklist as it's needed by StrategySelector
    blacklist = Blacklist(db=db) # Blacklist only takes db
    logger.info("Blacklist initialized.")

    # Initialize RiskManagement
    risk_management = RiskManagement(
        settings=settings,
        thresholds=thresholds,
        alert_system=alert_system,
        db=db,
        transaction_tracker=transaction_tracker,
        order_manager=order_manager
    )
    logger.info("RiskManagement initialized.")

    # Initialize PositionManagement
    position_management = PositionManagement(
        order_manager=order_manager,
        settings=settings,
        thresholds=thresholds,
        balance_checker=balance_checker,
        trade_validator=trade_validator
    )
    logger.info("PositionManagement initialized.")
    
    # Initialize missing components needed by StrategySelector
    # Initialize Indicators
    indicators = Indicators(settings=settings, thresholds=thresholds)
    logger.info("Indicators initialized.")
    
    # Initialize Whitelist
    whitelist = Whitelist(settings=settings)
    logger.info("Whitelist initialized.")
    
    # Initialize SolanaTrackerAPI
    solana_tracker_api = SolanaTrackerAPI(settings=settings)
    logger.info("SolanaTrackerAPI initialized.")
    
    # Get price_monitor from MarketData
    price_monitor = market_data.price_monitor
    logger.info("PriceMonitor reference obtained from MarketData.")
    
    # Get volume_monitor from MarketData or create one
    volume_monitor = VolumeMonitor(db=db, settings=settings, thresholds=thresholds)
    logger.info("VolumeMonitor initialized.")
    
    # Use MarketData as monitoring service
    monitoring_service = market_data
    logger.info("Monitoring service set to MarketData.")
    
    # Initialize EntryExitStrategy first as StrategySelector and StrategyEvaluator might need it
    entry_exit_strategy = EntryExitStrategy(
        settings=settings,
        db=db,
        trade_queue=None, # Operates in signal generation mode when used by StrategyEvaluator
        market_data=market_data,
        whitelist=whitelist,
        blacklist=blacklist,
        thresholds=thresholds,
        wallet_manager=wallet_manager
        # indicators=indicators # EES will calculate its own or use data from price events
    )
    await entry_exit_strategy.initialize(order_manager=order_manager) # Pass order_manager during initialization
    logger.info("EntryExitStrategy initialized standalone.")

    strategy_selector = StrategySelector(
        settings=settings,
        thresholds=thresholds,
        filters_config=filters_config,
        db=db,
        market_data=market_data,
        indicators=indicators,
        price_monitor=price_monitor,
        trade_queue=trade_queue,
        entry_exit_strategy=entry_exit_strategy,
        wallet_manager=wallet_manager,
        order_manager=order_manager,
        risk_management=risk_management,
        position_management=position_management,
        alert_system=alert_system,
        whitelist=whitelist,
        blacklist=blacklist
    )
    logger.info("StrategySelector initialized with more dependencies.")

    token_metrics = TokenMetrics(
        settings=settings,
        db=db,
        price_monitor=price_monitor,
        thresholds=thresholds,
        filter_manager=filter_manager,
        whitelist=whitelist,
        monitoring=monitoring_service, # Pass the MarketData instance as monitoring service
        indicators=indicators,
        platform_tracker=platform_tracker,
        volume_monitor=volume_monitor,
        strategy_selector=strategy_selector,
        solana_client=solana_client
    )
    logger.info("TokenMetrics initialized.")

    # Now initialize TokenScanner with proper TokenMetrics
    logger.info("Initializing TokenScanner...")
    token_scanner = TokenScanner(
        db=db, 
        settings=settings, 
        thresholds=thresholds, 
        filter_manager=filter_manager, 
        market_data=market_data, 
        dexscreener_api=dexscreener_api,
        token_metrics=token_metrics,
        rugcheck_api=rugcheck_api # Optional, but pass if available
    )
    if not await token_scanner.initialize():
        logger.critical("Failed to initialize TokenScanner. Exiting.")
        # ... (cleanup including dexscreener_api, market_data, filter_manager, etc.)
        await dexscreener_api.close()
        await market_data.close() # MarketData close will handle its internal PriceMonitor
        # filter_manager may have resources (like its own http_client if not shared) - check its close method
        if hasattr(filter_manager, 'close') and asyncio.iscoroutinefunction(filter_manager.close):
            await filter_manager.close()
        if proxy_manager: await proxy_manager.close_session()
        if http_client: await http_client.aclose()
        if solana_client: await solana_client.close()
        if db: await db.close()
        return None
    logger.info("TokenScanner initialized successfully.")

    # DataFetcher - initialized as it was before, TokenScanner does not directly use it.
    data_fetcher = DataFetcher(settings=settings)
    logger.info("DataFetcher initialized.")

    # Initialize TradeExecutor if available
    trade_executor_instance = None
    try:
        from execution.trade_executor import TradeExecutor
        trade_executor_instance = TradeExecutor(
            settings=settings,
            order_manager=order_manager,
            transaction_tracker=transaction_tracker,
            db=db,
            wallet_manager=wallet_manager,
            market_data=market_data
        )
        await trade_executor_instance.initialize()
        logger.info("TradeExecutor initialized.")
    except ImportError:
        logger.warning("TradeExecutor class not found. Using None - StrategyEvaluator will work without trade execution.")
        trade_executor_instance = None
    except Exception as e:
        logger.warning(f"TradeExecutor initialization failed: {e}. Using None.")
        trade_executor_instance = None

    # --- Strategy Components ---
    strategy_evaluator = StrategyEvaluator(
        market_data=market_data,
        db=db,
        settings=settings,
        thresholds=thresholds,
        trade_executor=trade_executor_instance,
        wallet_manager=wallet_manager,
        indicators=indicators,
        trade_queue=trade_queue,
        order_manager=order_manager,
        entry_exit_strategy=entry_exit_strategy,
        strategy_selector=strategy_selector
    )
    await strategy_evaluator.initialize_strategies() # Initialize internal strategies (will use provided EES or create if None)
    logger.info("StrategyEvaluator initialized.")
    
    # --- Paper Trading System ---
    paper_trading = PaperTrading(
        settings=settings,
        db=db,
        wallet_manager=wallet_manager,
        price_monitor=price_monitor
    )
    await paper_trading.load_persistent_state()
    logger.info("PaperTrading system initialized.")
    
    # --- Focused Monitoring Manager ---
    focused_monitoring = FocusedMonitoringManager(
        settings=settings,
        market_data=market_data,
        db=db
    )
    logger.info("FocusedMonitoringManager initialized.")
    
    # --- Blockchain Listener ---
    blockchain_listener = BlockchainListener(settings=settings, callback=None)
    await blockchain_listener.initialize()
    logger.info("BlockchainListener initialized.")
    
    # --- Hybrid Monitoring Manager ---
    hybrid_monitoring = HybridMonitoringManager(
        settings=settings,
        blockchain_listener=blockchain_listener,
        market_data=market_data,
        token_db=db,
        logger=logger
    )
    logger.info("HybridMonitoringManager initialized.")
    
    # --- Enhanced PumpSwap Parser with Helius Stream ---
    from data.pumpswap_parser import PumpSwapParser
    from config.blockchain_logging import setup_blockchain_logger
    
    async def helius_pump_callback(price_data):
        """Handle Helius Pump AMM price updates from enhanced parser"""
        try:
            # **DISABLED: The blockchain transaction data is NOT price data!**
            # This was causing confusion by treating transaction amounts as prices
            logger.debug(f"🔧 Helius blockchain event received (not processing as price): {price_data.get('signature', 'unknown')[:8]}...")
            return  # Skip processing blockchain events as prices
            
            # **OLD CODE DISABLED:**
            # if price_data.get('price'):
            #     # Extract mint from the price data or use a default approach
            #     token_mint = price_data.get('token_mint') or price_data.get('mint', 'unknown')
            #     
            #     # Update market data with the price
            #     await market_data._update_realtime_token_state(
            #         mint_address=token_mint,
            #         event_type='helius_pump_swap',
            #         price=price_data['price'],
            #         raw_event_data=price_data,
            #         dex_id='pumpswap',
            #         pair_address=price_data.get('signature', 'unknown')[:8]
            #     )
            #     
            #     price = price_data['price']
            #     decimals_info = f"(decimals: {price_data.get('token_decimals_used', 'unknown')})"
            #     method_info = price_data.get('calculation_method', 'unknown')
            #     
            #     # Cross-validate with Jupiter API
            #     mint_address = price_data.get('mint_address')
            #     if mint_address:
            #         try:
            #             import httpx
            #             async with httpx.AsyncClient(timeout=5.0) as client:
            #                 response = await client.get(f"https://lite-api.jup.ag/price/v2?ids={mint_address}&vsToken=So11111111111111111111111111111111111111112")
            #                 if response.status_code == 200:
            #                     jupiter_data = response.json()
            #                     if 'data' in jupiter_data and mint_address in jupiter_data['data']:
            #                         jupiter_price = float(jupiter_data['data'][mint_address]['price'])
            #                         price_diff_pct = abs(price - jupiter_price) / jupiter_price * 100 if jupiter_price > 0 else 0
            #                         
            #                         if price_diff_pct > 50:  # More than 50% difference
            #                             logger.warning(f"🚨 PRICE MISMATCH: Blockchain: {price:.8f} SOL vs Jupiter: {jupiter_price:.8f} SOL (diff: {price_diff_pct:.1f}%) [{method_info}]")
            #                         else:
            #                             logger.info(f"✅ Price validated: {price:.8f} SOL (Jupiter: {jupiter_price:.8f} SOL, diff: {price_diff_pct:.1f}%) [{method_info}]")
            #                         return  # Skip the normal log if we have validation
            #         except Exception as e:
            #             logger.debug(f"Jupiter validation failed: {e}")
            #     
            #     logger.info(f"🎯 Helius Pump price update: {price:.8f} SOL {decimals_info} [{method_info}]")
        except Exception as e:
            logger.error(f"Error processing Helius pump callback: {e}")
    
    # Initialize enhanced PumpSwap parser with stream capability
    blockchain_logger = setup_blockchain_logger("PumpSwapStream")
    helius_pump_parser = PumpSwapParser(settings, blockchain_logger)
    
    # Start the Helius Pump AMM stream
    await helius_pump_parser.start_helius_pump_stream(callback=helius_pump_callback)
    logger.info("🚀 Enhanced PumpSwap parser with Helius stream initialized and started")
    
    # --- Filters ---
    # FilterManager setup can occur here if it's a standalone component
    # Example: filter_manager = FilterManager(settings, db, ...)
    # await filter_manager.initialize()
    # logger.info("FilterManager initialized.")

    components = {
        "settings": settings,
        "db": db,
        "thresholds": thresholds,
        "filters_config": filters_config,
        "market_data": market_data,
        "dexscreener_api": dexscreener_api,
        "rugcheck_api": rugcheck_api,         # Add rugcheck_api
        "solsniffer_api": solsniffer_api,     # Add solsniffer_api
        "solana_tracker_api": solana_tracker_api, # Add solana_tracker_api
        "twitter_check": twitter_check,       # Add twitter_check
        "filter_manager": filter_manager,     # Add filter_manager
        "whitelist": whitelist,               # Add whitelist
        "blacklist": blacklist,               # Add blacklist
        "alert_system": alert_system,         # Add alert_system
        "risk_management": risk_management,     # Add risk_management
        "position_management": position_management, # Add position_management
        "indicators": indicators,             # Add indicators
        "platform_tracker": platform_tracker, # Add platform_tracker
        "volume_monitor": volume_monitor,     # Add volume_monitor
        "strategy_selector": strategy_selector, # Add strategy_selector
        "token_metrics": token_metrics,       # Add token_metrics
        "data_fetcher": data_fetcher,         # Add data_fetcher
        "token_scanner": token_scanner,
        "http_client": http_client,
        "solana_client": solana_client,
        "wallet_manager": wallet_manager,
        "trade_queue": trade_queue, # Keep for other potential uses
        "order_manager": order_manager, # Keep for other potential uses
        "transaction_tracker": transaction_tracker, # Keep for other potential uses
        "trade_executor": trade_executor_instance, # Add to components (could be None)
        "strategy_evaluator": strategy_evaluator, # Add to components
        "paper_trading": paper_trading, # Add paper trading system
        "blockchain_listener": blockchain_listener, # Add blockchain listener
        "focused_monitoring": focused_monitoring, # Add focused monitoring manager
        "hybrid_monitoring": hybrid_monitoring, # Add hybrid monitoring manager
        "helius_pump_parser": helius_pump_parser, # Add enhanced PumpSwap parser with Helius stream
        # "filter_manager": filter_manager, # If used
    }
    # Log component initialization times or other relevant info
    end_time = time.time()
    logger.info(f"--- Core Components Initialized ({end_time - start_time:.2f}s) ---")
    return components # Return as a dictionary


# Add this where other async functions are defined before main()

async def manage_top_token_trading(
    db: TokenDatabase, 
    market_data: MarketData, 
    settings: Settings, 
    token_scanner: TokenScanner,
    strategy_evaluator: Optional[StrategyEvaluator],
    shutdown_event: asyncio.Event
):
    logger.info("Starting Top 3 Token Trading Manager...")
    current_monitored_tokens: Dict[str, Dict] = {}  # Track multiple tokens: {mint: {pair_address, dex_id}}
    max_tokens = 3  # Monitor top 3 tokens

    while not shutdown_event.is_set():
        try:
            logger.info("Top 3 Token Manager: Checking for new best tokens...")
            # Get the top 3 tokens for trading
            top_tokens = await db.get_top_tokens_for_trading(limit=max_tokens, include_inactive_tokens=True)

            if top_tokens:
                logger.info(f"Top 3 Token Manager: Found {len(top_tokens)} candidates")
                
                # Get current token mints
                new_token_mints = {token.mint for token in top_tokens}
                current_token_mints = set(current_monitored_tokens.keys())
                
                # Stop monitoring tokens that are no longer in top 3
                tokens_to_stop = current_token_mints - new_token_mints
                for mint_to_stop in tokens_to_stop:
                    logger.info(f"Top 3 Token Manager: Stopping monitoring for token no longer in top 3: {mint_to_stop}")
                    await market_data.stop_monitoring_token(mint_to_stop)
                    await db.update_token_monitoring_status(mint_to_stop, 'stopped')
                    if strategy_evaluator:
                        strategy_evaluator.stop_evaluating_token(mint_to_stop)
                    del current_monitored_tokens[mint_to_stop]
                
                # Start monitoring new tokens
                tokens_to_start = new_token_mints - current_token_mints
                for token in top_tokens:
                    if token.mint in tokens_to_start:
                        logger.info(f"Top 3 Token Manager: Starting monitoring for new token: {token.mint} (Pair: {token.pair_address}, DEX: {token.dex_id})")
                        success = await market_data.start_monitoring_token(mint=token.mint)
                        if success:
                            current_monitored_tokens[token.mint] = {
                                'pair_address': token.pair_address,
                                'dex_id': token.dex_id
                            }
                            await db.update_token_monitoring_status(token.mint, 'active')
                            logger.info(f"Top 3 Token Manager: Successfully started monitoring {token.mint}")
                            if strategy_evaluator:
                                strategy_evaluator.start_evaluating_token(token.mint, token.pair_address, token.dex_id)
                        else:
                            logger.error(f"Top 3 Token Manager: Failed to start monitoring for {token.mint}")
                
                # Log current status
                logger.info(f"Top 3 Token Manager: Currently monitoring {len(current_monitored_tokens)} tokens: {list(current_monitored_tokens.keys())}")
                
            else:
                logger.info("Top 3 Token Manager: No suitable tokens found for trading in this cycle.")
                # Stop all current monitoring if no tokens found
                for mint in list(current_monitored_tokens.keys()):
                    logger.info(f"Top 3 Token Manager: No candidates found, stopping monitoring for {mint}")
                    await market_data.stop_monitoring_token(mint)
                    await db.update_token_monitoring_status(mint, 'stopped')
                    if strategy_evaluator:
                        strategy_evaluator.stop_evaluating_token(mint)
                current_monitored_tokens.clear()
            
            # Wait for the next cycle
            logger.info(f"Top 3 Token Manager: Sleeping for {settings.TOP_TOKEN_SELECTION_INTERVAL_SECONDS} seconds.")
            await asyncio.sleep(settings.TOP_TOKEN_SELECTION_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Top 3 Token Trading Manager shutting down due to cancellation.")
            break


# --- Main Asynchronous Function ---
async def main():
    """Main entry point for the trading bot."""
    # Get a logger instance
    logger = get_logger(__name__) # Ensure logger is the configured one
    logger.info("🚀 --- SUPERTRADEX BOT STARTING --- 🚀")
    logger.info(f"Version: {get_git_commit_hash()}") # Log git commit hash
    logger.info(f"Python Version: {sys.version}")
    logger.info(f"Current Working Directory: {os.getcwd()}")
    logger.info(f"Max Runtime: {'Unlimited' if MAX_RUNTIME_SECONDS is None else f'{MAX_RUNTIME_SECONDS}s'}")
    
    # Create a global shutdown event
    shutdown_event = asyncio.Event()

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    
    # Store original signal handlers
    original_sigint_handler = signal.getsignal(signal.SIGINT)
    original_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def signal_handler_wrapper():
        # This synchronous wrapper schedules the asynchronous signal_handler_async.
        logger.info("Signal received by wrapper, initiating shutdown sequence...")
        if not shutdown_event.is_set():
            # logger is captured from main's scope
            # The third argument to the old signal_handler_async (components) is removed.
            asyncio.create_task(signal_handler_async(shutdown_event, logger))
        else:
            logger.info("Signal received by wrapper, but shutdown_event already set.")

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler_wrapper)

    components = None # Initialize components to None
    try:
        logger.info(f"Starting SuperTradex Bot. Commit: {get_git_commit_hash()}")
        logger.info(f"Max runtime: {MAX_RUNTIME_SECONDS if MAX_RUNTIME_SECONDS else 'Indefinite'}")

        # --- Initialize Components ---
        # All component initialization is now within initialize_components
        components = await initialize_components(settings)
        
        # Check if initialization failed
        if components is None:
            logger.critical("Component initialization failed. Exiting.")
            return

        # Extract necessary components (assuming components is a dictionary)
        db = components["db"]
        market_data = components["market_data"]
        token_scanner = components["token_scanner"]
        strategy_evaluator = components.get("strategy_evaluator") # Use .get() for optional components
        trade_scheduler = components.get("trade_scheduler") # Use .get() for optional components
        paper_trading = components.get("paper_trading") # Get paper trading system
        focused_monitoring = components.get("focused_monitoring") # Get focused monitoring manager
        blockchain_listener = components.get("blockchain_listener") # Get blockchain listener

        if not all([db, market_data, token_scanner]): # Basic check
            logger.critical("One or more critical components (DB, MarketData, TokenScanner) failed to initialize. Exiting.")
            return

        # --- Initialize Focused Monitoring for Real-time Price Comparison ---
        if focused_monitoring:
            logger.info("🎯 Starting focused monitoring initialization...")
            await focused_monitoring.initialize_focused_monitoring()
            # Subscribe to blockchain events for real-time price comparison
            await focused_monitoring.subscribe_to_pool_events()
            logger.info("✅ Focused monitoring initialized for real-time price comparison")
        
        # --- Initialize Hybrid Monitoring for Priority-Based Token Monitoring ---
        hybrid_monitoring = components.get("hybrid_monitoring")
        if hybrid_monitoring:
            logger.info("🎯 Setting up hybrid monitoring with priority-based token strategies...")
            
            # Add BONK as HIGH priority token with direct account subscription
            bonk_success = await hybrid_monitoring.add_high_priority_token(
                mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
                symbol="BONK",
                pool_address="8BnEgHoWFysVcuFFX7QztDmzuH8r5ZFvyP3sYwn1XTh6",  # Raydium V4 BONK/SOL
                dex_id="raydium_v4"
            )
            
            if bonk_success:
                logger.info("🔥 BONK added as HIGH priority with direct account subscription")
            else:
                logger.error("❌ Failed to add BONK as high priority token")
            
            # Add SAPHI as MEDIUM priority token with program logs
            saphi_success = await hybrid_monitoring.add_medium_priority_token(
                mint="7ZYyESa8TkuoBVFi5seeLPr7B3MeLvyPgEgv5MDTpump",  # ✅ FIXED: Use same mint as focused monitoring
                symbol="SAPHI",
                dex_id="pumpswap"
            )
            
            if saphi_success:
                logger.info("📡 SAPHI added as MEDIUM priority with program logs")
            
            # Set up blockchain event callback for hybrid monitoring
            if blockchain_listener:
                existing_callback = blockchain_listener._callback
                
                async def hybrid_callback(event_data):
                    # Route to hybrid monitoring first
                    await hybrid_monitoring.handle_blockchain_event(event_data)
                    # Then call existing callback if it exists
                    if existing_callback:
                        await existing_callback(event_data)
                
                blockchain_listener.set_callback(hybrid_callback)
                logger.info("🔗 Hybrid monitoring blockchain callback integrated")
            
            logger.info("✅ Hybrid monitoring initialized with priority-based token strategies")
        
        # --- Enable Paper Trading for Focused Tokens ---
        if paper_trading:
            logger.info("📄 Paper trading system ready for focused tokens")

        logger.info("--- All Components Initialized and Ready --- ")
        
        # The signal_handler_wrapper defined above will correctly use the shutdown_event and logger
        # from the main() scope. No redefinition or complex passing of 'components' to the
        # signal handler itself is needed with the new approach, as the 'finally' block handles cleanup.
        # Old comments regarding this can be removed or ignored.

        # --- Setup API Endpoints (FastAPI app) ---
        # Create an instance of the FastAPI app
        app_instance = FastAPI()

        # Include routers from different modules
        if "api" in sys.modules: # Check if api module is loaded (it should be if __init__ is correct)
            from api.routes.metrics_router import router as metrics_router
            from api.routes.control_router import router as control_router
            from api.routes.config_router import router as config_router
            from api.routes.data_router import router as data_router # Added data_router
            
            app_instance.include_router(metrics_router, prefix="/api/metrics")
            app_instance.include_router(control_router, prefix="/api/control")
            app_instance.include_router(config_router, prefix="/api/config")
            app_instance.include_router(data_router, prefix="/api/data") # Added data_router prefix

            # Pass components to the FastAPI app context if needed by route handlers
            # This is a common pattern for FastAPI to make shared resources available.
            app_instance.state.components = components
            app_instance.state.settings = settings # Pass settings as well
            logger.info("FastAPI routers included and components/settings attached to app state.")
        else:
            logger.warning("API module not found in sys.modules. FastAPI endpoints will not be available.")

        # --- Start Background Tasks ---
        background_tasks = []
        
        # Start the token scanner
        scanner_task = asyncio.create_task(token_scanner.run_scan_loop(shutdown_event))
        background_tasks.append(scanner_task)
        logger.info("TokenScanner task started.")

        # Start the MarketData service (e.g., WebSocket connections, price updates)
        market_data_task = asyncio.create_task(market_data.start_monitoring())
        background_tasks.append(market_data_task)
        logger.info("MarketData monitoring task started.")

        # Start the TradeScheduler if available and initialized
        if trade_scheduler:
            scheduler_task = asyncio.create_task(trade_scheduler.run(shutdown_event))
            background_tasks.append(scheduler_task)
            logger.info("TradeScheduler task started.")
        else:
            logger.info("TradeScheduler not available or not initialized, task not started.")
            
        # Initialize and Start the BlockchainListener's main loop if enabled
        # DISABLED: Using new pool-specific subscriptions instead
        # if settings.USE_BLOCKCHAIN_LISTENER:
        #     if hasattr(market_data, 'initialize_blockchain_listener') and callable(market_data.initialize_blockchain_listener):
        #         logger.info("Initializing MarketData's BlockchainListener...")
        #         await market_data.initialize_blockchain_listener() # Call the initialization method
        #         
        #         if hasattr(market_data, 'blockchain_listener') and market_data.blockchain_listener:
        #             listener_instance = market_data.blockchain_listener
        #             if hasattr(listener_instance, 'run_forever') and callable(listener_instance.run_forever):
        #                 logger.info("Starting BlockchainListener.run_forever() task...")
        #                 blockchain_listener_task = asyncio.create_task(listener_instance.run_forever())
        #                 background_tasks.append(blockchain_listener_task)
        #                 logger.info("BlockchainListener.run_forever() task started.")
        #             else:
        #                 logger.warning("MarketData's blockchain_listener does not have a callable run_forever method.")
        #         else:
        #             logger.warning("MarketData.initialize_blockchain_listener() called, but market_data.blockchain_listener is still not available.")
        #     else:
        #         logger.warning("MarketData does not have an initialize_blockchain_listener method.")
        # else:
        #     logger.info("BlockchainListener not enabled (USE_BLOCKCHAIN_LISTENER is false).")
        logger.info("🚫 Old BlockchainListener disabled - using pool-specific subscriptions instead")

        # Start the Top Token Trading Manager
        top_token_manager_task = asyncio.create_task(
            manage_top_token_trading(
                db=db,
                market_data=market_data,
                settings=settings,
                token_scanner=token_scanner, # Pass the TokenScanner instance
                strategy_evaluator=strategy_evaluator, # Pass StrategyEvaluator
                shutdown_event=shutdown_event
            )
        )
        background_tasks.append(top_token_manager_task)
        logger.info("Top Token Trading Manager task started.")
        
        # Start the StrategyEvaluator periodic evaluation task
        if strategy_evaluator and hasattr(strategy_evaluator, 'run_evaluations'):
            strategy_evaluator_task = asyncio.create_task(strategy_evaluator.run_evaluations(shutdown_event))
            background_tasks.append(strategy_evaluator_task)
            logger.info("StrategyEvaluator periodic evaluation task started.")
        elif strategy_evaluator:
            logger.warning("StrategyEvaluator instance exists but does not have 'run_evaluations' method. Periodic evaluation will not run.")
        else:
            logger.info("StrategyEvaluator not available, periodic evaluation task not started.")

        # Start Focused Monitoring Background Tasks
        if focused_monitoring:
            # Task 1: Update and display PriceMonitor prices every 30 seconds
            async def price_monitor_update_task():
                logger.info("🎯 Starting PriceMonitor price update task...")
                while not shutdown_event.is_set():
                    try:
                        await focused_monitoring.update_price_monitor_display()
                        await asyncio.sleep(30)  # Update every 30 seconds
                    except asyncio.CancelledError:
                        logger.info("PriceMonitor update task cancelled")
                        break
                    except Exception as e:
                        logger.error(f"Error in PriceMonitor update task: {e}")
                        await asyncio.sleep(30)  # Continue after error
            
            # Task 2: Print comparison summary every 60 seconds
            async def comparison_summary_task():
                logger.info("📊 Starting price comparison summary task...")
                await asyncio.sleep(60)  # Wait 60s before first summary
                while not shutdown_event.is_set():
                    try:
                        focused_monitoring.print_focused_comparison()
                        await asyncio.sleep(60)  # Print summary every 60 seconds
                    except asyncio.CancelledError:
                        logger.info("Comparison summary task cancelled")
                        break
                    except Exception as e:
                        logger.error(f"Error in comparison summary task: {e}")
                        await asyncio.sleep(60)  # Continue after error
            
            price_monitor_task = asyncio.create_task(price_monitor_update_task())
            background_tasks.append(price_monitor_task)
            logger.info("🎯 Focused PriceMonitor update task started (30s intervals)")
            
            comparison_task = asyncio.create_task(comparison_summary_task())
            background_tasks.append(comparison_task)
            logger.info("📊 Focused price comparison summary task started (60s intervals)")
            
            # Add the WebSocket message processing task to background tasks
            if focused_monitoring.message_processing_task:
                background_tasks.append(focused_monitoring.message_processing_task)
                logger.info("🔄 Added focused monitoring message processing task to background tasks")
        else:
            logger.warning("Focused monitoring not available, price comparison tasks not started.")
        
        # Start Hybrid Monitoring Background Tasks
        if hybrid_monitoring:
            # Task: Print hybrid monitoring status every 2 minutes
            async def hybrid_status_task():
                logger.info("🎯 Starting hybrid monitoring status reporting...")
                await asyncio.sleep(120)  # Wait 2 minutes before first report
                while not shutdown_event.is_set():
                    try:
                        await hybrid_monitoring.print_status_report()
                        await asyncio.sleep(120)  # Report every 2 minutes
                    except asyncio.CancelledError:
                        logger.info("Hybrid monitoring status task cancelled")
                        break
                    except Exception as e:
                        logger.error(f"Error in hybrid monitoring status task: {e}")
                        await asyncio.sleep(120)  # Continue after error
            
            hybrid_task = asyncio.create_task(hybrid_status_task())
            background_tasks.append(hybrid_task)
            logger.info("🎯 Hybrid monitoring status reporting task started (2min intervals)")
        else:
            logger.warning("Hybrid monitoring not available, status reporting not started.")

        # **ADDED: Jupiter API Price Fetching Task**
        async def jupiter_price_fetching_task():
            """Fetch real prices from Jupiter API for monitored tokens"""
            logger.info("💰 Starting Jupiter API price fetching task...")
            await asyncio.sleep(10)  # Wait 10 seconds before first fetch
            while not shutdown_event.is_set():
                try:
                    # Get currently monitored tokens
                    monitored_tokens = await db.get_tokens_with_status('active')
                    if monitored_tokens:
                        mint_addresses = [token.mint for token in monitored_tokens[:5]]  # Limit to top 5
                        
                        # Fetch prices from Jupiter API
                        try:
                            import httpx
                            mint_ids = ",".join(mint_addresses)
                            url = f"https://lite-api.jup.ag/price/v2?ids={mint_ids}&vsToken=So11111111111111111111111111111111111111112"
                            
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                response = await client.get(url)
                                if response.status_code == 200:
                                    jupiter_data = response.json()
                                    
                                    if 'data' in jupiter_data and jupiter_data['data']:
                                        for mint_address in mint_addresses:
                                            if mint_address in jupiter_data['data']:
                                                price_data = jupiter_data['data'][mint_address]
                                                if price_data and 'price' in price_data:
                                                    jupiter_price = float(price_data['price'])
                                                    
                                                    # **PRICE VALIDATION** - Reject unrealistic prices
                                                    if jupiter_price > 10.0:
                                                        token_info = next((t for t in monitored_tokens if t.mint == mint_address), None)
                                                        symbol = token_info.symbol if token_info and token_info.symbol else mint_address[:8]
                                                        logger.warning(f"🚨 JUPITER_API price validation FAILED: {symbol} | {mint_address[:8]}... | {jupiter_price:.8f} SOL is unrealistic (>10 SOL). Skipping.")
                                                        continue
                                                    
                                                    if jupiter_price <= 0:
                                                        token_info = next((t for t in monitored_tokens if t.mint == mint_address), None)
                                                        symbol = token_info.symbol if token_info and token_info.symbol else mint_address[:8]
                                                        logger.warning(f"🚨 JUPITER_API price validation FAILED: {symbol} | {mint_address[:8]}... | {jupiter_price:.8f} SOL is invalid (<=0). Skipping.")
                                                        continue
                                                    
                                                    # Update market data with Jupiter price
                                                    await market_data._update_realtime_token_state(
                                                        mint_address=mint_address,
                                                        event_type='jupiter_api_price',
                                                        price=jupiter_price,
                                                        raw_event_data=price_data,
                                                        dex_id='jupiter_aggregator',
                                                        pair_address='jupiter_api'
                                                    )
                                                    
                                                    # Get token symbol for logging
                                                    token_info = next((t for t in monitored_tokens if t.mint == mint_address), None)
                                                    symbol = token_info.symbol if token_info and token_info.symbol else mint_address[:8]
                                                    
                                                    logger.info(f"💰 JUPITER_API price: {symbol} | {mint_address[:8]}... | {jupiter_price:.8f} SOL [jupiter_api] ✅")
                                                else:
                                                    logger.debug(f"Jupiter API: No price data for {mint_address[:8]}...")
                                            else:
                                                logger.debug(f"Jupiter API: Token {mint_address[:8]}... not found in response")
                                    else:
                                        logger.warning("Jupiter API returned no price data")
                                else:
                                    logger.warning(f"Jupiter API error: {response.status_code}")
                        except Exception as e:
                            logger.error(f"Jupiter API fetch failed: {e}")
                    
                    # Wait 30 seconds before next fetch
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    logger.info("Jupiter price fetching task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in Jupiter price fetching task: {e}")
                    await asyncio.sleep(30)

        jupiter_task = asyncio.create_task(jupiter_price_fetching_task())
        background_tasks.append(jupiter_task)
        logger.info("💰 Jupiter API price fetching task started (30s intervals)")

        # --- Start FastAPI Server ---
        # Configuration for Uvicorn
        # Ensure Uvicorn is imported
        try:
            import uvicorn
            from uvicorn_log_config import UVICORN_LOGGING_CONFIG # Import custom log config
            
            # Make sure settings.API_HOST and settings.API_PORT are defined
            api_host = getattr(settings, 'API_HOST', '127.0.0.1')
            api_port = getattr(settings, 'API_PORT', 8000)

            logger.info(f"Starting FastAPI server on {api_host}:{api_port}")
            
            # Configure Uvicorn to run the FastAPI app
            # Use the imported logging config
            config = uvicorn.Config(app_instance, host=api_host, port=api_port, log_config=UVICORN_LOGGING_CONFIG)
            server = uvicorn.Server(config)
            
            # Run Uvicorn in a separate thread or as an asyncio task
            # To allow other asyncio tasks to run concurrently.
            # Running in a separate thread is often simpler for Uvicorn.
            # However, for graceful shutdown, running as an asyncio task is better.
            # server.run() # This is blocking
            
            # Start Uvicorn as an asyncio task
            uvicorn_task = asyncio.create_task(server.serve())
            background_tasks.append(uvicorn_task)
            logger.info("Uvicorn server task started.")

        except ImportError:
            logger.warning("Uvicorn not installed. FastAPI server will not run. Run 'pip install uvicorn[standard]'")
        except AttributeError as e:
            logger.error(f"FastAPI/Uvicorn configuration error: {e}. Check API_HOST/API_PORT in settings. Server will not run.", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to start FastAPI server: {e}", exc_info=True)


        # --- Main Application Loop (Keep Alive) ---
        start_main_loop_time = time.time()
        while not shutdown_event.is_set():
            # Check max runtime
            if MAX_RUNTIME_SECONDS and (time.time() - start_main_loop_time > MAX_RUNTIME_SECONDS):
                logger.info(f"Max runtime of {MAX_RUNTIME_SECONDS}s reached. Initiating shutdown.")
                shutdown_event.set()
                break
            
            # Main loop can perform periodic checks or just sleep
            # logger.debug("Main loop iteration...")
            await asyncio.sleep(settings.MAIN_LOOP_SLEEP_INTERVAL_S) # Sleep for a configured interval

        logger.info("Shutdown event set. Exiting main loop.")

    except Exception as e:
        logger.critical(f"CRITICAL ERROR in main execution: {e}", exc_info=True)
    finally:
        logger.info("--- Main `finally` block: Initiating Graceful Shutdown ---")
        
        # Ensure shutdown_event is set if an exception caused early exit or if not set by signal
        if not shutdown_event.is_set():
            logger.info("Main `finally` block: Shutdown event was not set (e.g., due to an exception), setting it now.")
            shutdown_event.set() # Ensures subsequent checks for shutdown_event are true
        
        # Call the helper to close all components
        # Make sure `components` dictionary is available here.
        # It should be, due to its definition at the start of the `try` block.
        if components and isinstance(components, dict): # Ensure components were initialized and is a dictionary
            logger.info("Main `finally` block: Closing all components.")
            await close_all_components(components) 
        else:
            logger.warning("Main `finally` block: Components dictionary not available or not initialized for shutdown.")

        # Explicitly close Solana client and HTTP client if not managed by components
        # These are usually passed to components which should manage their lifecycle (e.g., closing sessions)
        # However, if they were created in `initialize_components` and not passed to a component that closes them,
        # or if some components failed to initialize, we might need to close them here.
        # For now, let's assume components handle their resources.
        # Example:
        # if 'solana_client' in locals() and solana_client:
        #     await solana_client.close()
        # if 'http_client' in locals() and http_client:
        #     await http_client.aclose()
        #     logger.info("HTTP client closed.")

        # Wait for all background tasks to complete
        if 'background_tasks' in locals() and background_tasks:
            logger.info(f"Waiting for {len(background_tasks)} background tasks to complete...")
            # Set a timeout for waiting for tasks
            # Gather with return_exceptions=True to prevent one failed task from stopping others
            # Cancel pending tasks to ensure they terminate if they don't respect shutdown_event quickly
            for task in background_tasks:
                if not task.done():
                    task.cancel()
            
            results = await asyncio.gather(*background_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                task_name = background_tasks[i].get_name() if hasattr(background_tasks[i], 'get_name') else f"Task-{i}"
                if isinstance(result, asyncio.CancelledError):
                    logger.info(f"Background task {task_name} was cancelled during shutdown.")
                elif isinstance(result, Exception):
                    logger.error(f"Background task {task_name} raised an exception during shutdown: {result}", exc_info=result)
            logger.info("All background tasks processed for shutdown.")
        
        # Deregister our asyncio signal handlers
        logger.info("Main `finally` block: Removing custom asyncio signal handlers.")
        if loop and not loop.is_closed(): # Ensure loop is available and not closed
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.remove_signal_handler(sig)
                    logger.info(f"Main `finally` block: Removed asyncio signal handler for {sig}.")
                except ValueError: 
                    logger.warning(f"Main `finally` block: Asyncio signal handler for {sig} not found or already removed.")
                except RuntimeError as e: 
                    logger.warning(f"Main `finally` block: Error removing asyncio signal handler for {sig}: {e}")
                except Exception as e:
                    logger.error(f"Main `finally` block: Unexpected error removing asyncio signal handler for {sig}: {e}", exc_info=True)
        else:
            logger.warning("Main `finally` block: Event loop not available or closed, skipping removal of asyncio signal handlers.")

        # Restore original OS-level signal handlers
        logger.info("Main `finally` block: Restoring original OS-level signal handlers.")
        try:
            if original_sigint_handler is not None:
                signal.signal(signal.SIGINT, original_sigint_handler)
                logger.info("Main `finally` block: Restored original SIGINT handler.")
            else: # If original was None, it implies default or no handler, SIG_DFL is python's default upon start if not inherited
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                logger.info("Main `finally` block: Restored SIGINT handler to default (SIG_DFL) as original was None.")

            if original_sigterm_handler is not None:
                signal.signal(signal.SIGTERM, original_sigterm_handler)
                logger.info("Main `finally` block: Restored original SIGTERM handler.")
            else:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                logger.info("Main `finally` block: Restored SIGTERM handler to default (SIG_DFL) as original was None.")
        except Exception as e: 
            logger.error(f"Main `finally` block: Error restoring original OS-level signal handlers: {e}", exc_info=True)
        
        logger.info("--- Main `finally` block: Shutdown process complete ---")
        # asyncio_mqtt_client.close() # Example if there were other global resources
        # if http_client: await http_client.aclose() # Example

    return 0 # Return 0 for success, 1 for error (or specific codes)


# --- FastAPI Routes & Global App Setup ---
# Create a global FastAPI app instance
app = FastAPI(
    title="SuperTradex API",
    description="API for controlling and monitoring the SuperTradex trading bot.",
    version=get_git_commit_hash() # Use git commit hash for version
)

# --- Entry Point --- #
if __name__ == "__main__":
    main_exit_code = 0 # Default success
    try:
        # Run main and get the exit code it returns
        main_exit_code = asyncio.run(main())

    except KeyboardInterrupt:
        # Use logger if possible, otherwise print
        try: logger.info("KeyboardInterrupt received, exiting.")
        except NameError: print("KeyboardInterrupt received, exiting.")
        main_exit_code = 1 # Indicate interruption
    except Exception as e:
        # This top-level catch might catch errors during asyncio.run setup itself
        try: logger.critical(f"Unhandled exception at top level __main__: {e}", exc_info=True)
        except NameError: print(f"CRITICAL: Unhandled exception at top level __main__: {e}")
        main_exit_code = 1 # Set failure exit code
    finally:
        # Explicitly shutdown logging here ensures it happens even if asyncio.run errors early
        logging.shutdown()
        sys.exit(main_exit_code) # Use the captured/determined exit code

@app.get("/api/metrics/blockchain")
async def get_blockchain_metrics():
    """
    Get metrics about blockchain listener reliability and fallback operations
    
    Returns:
        dict: Metrics about connection reliability and fallbacks to PriceMonitor
    """
    if market_data:
        metrics = await market_data.get_blockchain_listener_metrics()
        
        # Add additional stats about monitoring strategy
        metrics["monitoring_strategy"] = {
            "description": "Combined monitoring strategy statistics",
            "priority_counts": await get_monitoring_priority_counts(),
            "success_rates": {
                "direct_account": get_success_rate(metrics, "direct_account"),
                "log_subscription": get_success_rate(metrics, "logs"),
                "webhook": 0.0,  # Not implemented yet
                "price_monitor": 100.0  # Always works as fallback
            }
        }
        
        return metrics
    else:
        return {
            "error": "MarketData not initialized",
            "timestamp": time.time()
        }

@app.get("/api/paper-trading/balance")
async def get_paper_trading_balance():
    """Get current paper trading SOL balance"""
    try:
        if 'db' in globals():
            balance_data = await db.get_paper_summary_value('paper_sol_balance')
            if balance_data and balance_data.get('value_float') is not None:
                return {"balance": balance_data['value_float'], "currency": "SOL"}
            else:
                return {"balance": 0.0, "currency": "SOL"}
        else:
            return {"error": "Database not available", "balance": 0.0, "currency": "SOL"}
    except Exception as e:
        return {"error": str(e), "balance": 0.0, "currency": "SOL"}

@app.get("/api/paper-trading/positions")
async def get_paper_trading_positions():
    """Get all current paper trading positions"""
    try:
        if 'db' in globals():
            positions = await db.get_all_paper_positions()
            position_list = []
            for position in positions:
                # Get token info for symbol
                token_info = await db.get_token_by_mint(position.mint)
                symbol = token_info.symbol if token_info else position.mint[:8]
                
                position_data = {
                    "mint": position.mint,
                    "symbol": symbol,
                    "quantity": position.quantity,
                    "total_cost_usd": position.total_cost_usd,
                    "average_price_usd": position.average_price_usd,
                    "last_updated": position.last_updated.isoformat() if position.last_updated else None
                }
                position_list.append(position_data)
            return {"positions": position_list}
        else:
            return {"error": "Database not available", "positions": []}
    except Exception as e:
        return {"error": str(e), "positions": []}

@app.get("/api/paper-trading/tokens")
async def get_available_tokens():
    """Get tokens available for paper trading"""
    try:
        if 'db' in globals():
            tokens = await db.get_top_tokens_for_trading(limit=10)
            token_list = []
            for token in tokens:
                # Get SOL price from api_data if available
                current_price_sol = 0.000001  # Default
                if token.api_data and 'price_sol' in token.api_data:
                    current_price_sol = token.api_data['price_sol']
                elif token.price:
                    current_price_sol = token.price / 150  # Assume $150/SOL
                
                token_data = {
                    "mint": token.mint,
                    "symbol": token.symbol or 'UNKNOWN',
                    "name": token.name or '',
                    "price_sol": current_price_sol,
                    "price_usd": token.price or 0,
                    "volume_24h": token.volume_24h or 0,
                    "liquidity": token.liquidity or 0,
                    "dex_id": token.dex_id or '',
                    "rugcheck_score": token.rugcheck_score or 0
                }
                token_list.append(token_data)
            return {"tokens": token_list}
        else:
            return {"error": "Database not available", "tokens": []}
    except Exception as e:
        return {"error": str(e), "tokens": []}

@app.post("/api/paper-trading/execute")
async def execute_paper_trade():
    """Execute a paper trade"""
    try:
        from fastapi import Request
        # This would need to be implemented with proper request handling
        # For now, return a placeholder
        return {"success": False, "message": "Paper trade execution endpoint needs implementation"}
    except Exception as e:
        return {"success": False, "message": str(e)}
        
async def get_monitoring_priority_counts():
    """
    Get counts of tokens being monitored at each priority level
    
    Returns:
        dict: Counts by priority level
    """
    if not market_data:
        return {"high": 0, "medium": 0, "low": 0, "total": 0}
        
    result = {"high": 0, "medium": 0, "low": 0, "total": 0}
    
    for token_address, token_info in market_data._monitored_tokens.items():
        priority = token_info.get('priority', 'low')
        if priority in result:
            result[priority] += 1
        result["total"] += 1
        
    return result
    
def get_success_rate(metrics, monitoring_type):
    """
    Calculate success rate for a specific monitoring type
    
    Args:
        metrics: Metrics data
        monitoring_type: Type of monitoring to calculate for
    
    Returns:
        float: Success rate percentage
    """
    if "primary" not in metrics or "fallback" not in metrics:
        return 0.0
        
    primary = metrics["primary"]
    fallback = metrics["fallback"]
    
    if monitoring_type == "direct_account":
        primary_success = primary.get("subscription_success_rate", 0)
        fallback_success = fallback.get("subscription_success_rate", 0)
        return max(primary_success, fallback_success) * 100.0
    
    elif monitoring_type == "logs":
        # For logs, connection is more important than subscription
        primary_conn = primary.get("connection_success_rate", 0)
        fallback_conn = fallback.get("connection_success_rate", 0)
        return max(primary_conn, fallback_conn) * 100.0
    
    return 0.0