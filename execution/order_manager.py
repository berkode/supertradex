import logging
import os
from typing import Optional, Dict, Any, List, TYPE_CHECKING
# import requests # Use httpx instead
from dotenv import load_dotenv
# Removed nacl imports as signing is handled by WalletManager/Keypair
# import hashlib # Not needed if WalletManager handles key loading
import json
import asyncio
from datetime import datetime, timezone
import base64
import httpx # Use httpx for async http requests

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient # Correct import path
from solders.transaction import VersionedTransaction
from solana.rpc.types import TxOpts, Commitment  # Changed from solders
from solana.rpc.commitment import Confirmed, Processed  # Changed from solders
from solana.rpc.core import RPCException # Changed import location again
# from solders.rpc.errors import SendTransactionError # Keep commented for now

from data.token_database import TokenDatabase # Assuming this has update_trade_status
from config.settings import Settings
from utils.logger import get_logger
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType

# Import Wallet components
from wallet.wallet_manager import WalletManager
from wallet.trade_validator import TradeValidator # Import TradeValidator
from wallet.balance_checker import BalanceChecker # Import for type hint

# Import Execution components
# from .transaction_tracker import TransactionTracker  # Remove this import since it's in TYPE_CHECKING

# Import PaperTrading for simulated trades
from strategies.paper_trading import PaperTrading

# Import PriceMonitor for paper trading price fallback
from data.price_monitor import PriceMonitor

if TYPE_CHECKING:
    from .transaction_tracker import TransactionTracker

# Load environment variables
load_dotenv()

# Set up logging (assuming configured elsewhere)
logger = get_logger(__name__)

# Define SOL mint address globally
SOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")

class OrderManager:
    """
    Manages order placement and execution, primarily using Jupiter API.
    Interacts with WalletManager for signing and TransactionTracker for confirmation.
    """

    def __init__(self,
                 solana_client: AsyncClient, # Accept shared client
                 http_client: httpx.AsyncClient, # Accept shared http client
                 settings: Settings,
                 db: TokenDatabase,
                 wallet_manager: WalletManager, # Require WalletManager
                 trade_validator: TradeValidator, # Require TradeValidator
                 price_monitor: PriceMonitor, # Added PriceMonitor dependency
                 transaction_tracker: Optional['TransactionTracker'] = None # Allow setting tracker at init or later
                ):
        """
        Initialize the OrderManager.

        Args:
            solana_client: An initialized shared Solana AsyncClient instance.
            http_client: An initialized shared httpx AsyncClient instance.
            settings: Application settings object.
            db: An initialized TokenDatabase instance.
            wallet_manager: An initialized WalletManager instance.
            trade_validator: An initialized TradeValidator instance.
            price_monitor: An initialized PriceMonitor instance.
            transaction_tracker: Optional TransactionTracker instance.
        """
        self.solana_client = solana_client # Use the passed client
        self.http_client = http_client # Use the passed client
        self.settings = settings
        self.db = db
        self.wallet_manager = wallet_manager # Store WalletManager
        self.trade_validator = trade_validator # Store TradeValidator
        self.price_monitor = price_monitor # Store PriceMonitor instance
        self.transaction_tracker = transaction_tracker # Placeholder for tracker
        # self.http_client = httpx.AsyncClient() # REMOVED - Use shared client

        # Initialize PaperTrading instance if enabled in settings
        if self.settings.PAPER_TRADING_ENABLED:
            self.paper_trader = PaperTrading(settings=self.settings, db=self.db, wallet_manager=self.wallet_manager, price_monitor=self.price_monitor)
            logger.info("Paper trading mode is ENABLED.")
        else:
            self.paper_trader = None
            logger.info("Paper trading mode is DISABLED (live trading).")

        # Load settings
        self.slippage_bps = int(self.settings.MAX_SLIPPAGE_PCT * 100) # Jupiter expects BPS (e.g. 0.5% is 50 BPS)
        self.compute_unit_price_micro_lamports = self.settings.COMPUTE_UNIT_PRICE_MICRO_LAMPORTS
        self.compute_unit_limit = self.settings.COMPUTE_UNIT_LIMIT
        self.jupiter_api_base_url = self.settings.JUPITER_API_ENDPOINT

        self.logger = logger
        self.wallet_pubkey_str = str(self.wallet_manager.get_public_key()) if self.wallet_manager.get_public_key() else None
        if self.wallet_pubkey_str:
             logger.info(f"OrderManager initialized for wallet: {self.wallet_pubkey_str}")
        else:
             logger.error("OrderManager initialized but WalletManager has no public key available!")
             # Consider raising an error if wallet is essential at init

        # Enhanced position and order tracking
        self.positions: Dict[str, float] = {} # mint_address -> quantity
        self.orders: Dict[int, Dict[str, Any]] = {} # trade_id -> order_details
        self.position_history = {}  # Track position changes
        self.order_history = {}     # Track order history
        
        # Trade execution state
        self._execution_lock = asyncio.Lock()  # Prevent concurrent executions
        self._pending_trades = set()  # Track trades in progress

        # Initialize circuit breaker with settings
        self.circuit_breaker = CircuitBreaker(
            breaker_type=CircuitBreakerType.COMPONENT,
            identifier="order_manager",
            max_consecutive_failures=self.settings.COMPONENT_CB_MAX_FAILURES,
            reset_after_minutes=self.settings.CIRCUIT_BREAKER_RESET_MINUTES,
            on_activate=self._on_circuit_breaker_activate,
            on_reset=self._on_circuit_breaker_reset
        )

        # Call state initialization (can be awaited later if needed)
        # asyncio.create_task(self.initialize_state()) # Or call explicitly from main

    def _on_circuit_breaker_activate(self) -> None:
        """Callback when circuit breaker activates."""
        logger.error("Circuit breaker activated - order management operations suspended")
        # TODO: Add notification to admin/telegram

    def _on_circuit_breaker_reset(self) -> None:
        """Callback when circuit breaker resets."""
        logger.info("Circuit breaker reset - order management operations resumed")
        # TODO: Add notification to admin/telegram

    def set_transaction_tracker(self, transaction_tracker: 'TransactionTracker'):
        """Allows setting the TransactionTracker instance after initialization."""
        self.transaction_tracker = transaction_tracker
        self.logger.info("TransactionTracker instance set for OrderManager.")

    # _sign_transaction removed as WalletManager handles keys

    async def _fetch_jupiter_quote(self,
                                 input_mint: str,
                                 output_mint: str,
                                 amount_atomic: int,
                                 slippage_bps: Optional[int] = None
                                ) -> Optional[Dict[str, Any]]:
        """Fetches a swap quote from the Jupiter API."""
        if self.circuit_breaker.check():
            logger.warning("Circuit breaker active. Skipping Jupiter quote fetch.")
            return None
                
        slippage_val = slippage_bps if slippage_bps is not None else self.slippage_bps
        url = f"{self.jupiter_api_base_url}/quote"
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_atomic), # Amount in atomic units
            "slippageBps": slippage_val,
            "asLegacyTransaction": "false", # Request VersionedTransaction
        }
        # Add compute unit price if configured
        if self.compute_unit_price_micro_lamports:
            params["computeUnitPriceMicroLamports"] = str(self.compute_unit_price_micro_lamports)
        # TODO: Consider Jupiter v6 'priorityFeeLamports': 'auto' or specific value for priority fees
        # TODO: Consider Jupiter v6 'dynamicComputeUnitLimit': true instead of manual limits/price for dynamic CUs

        self.logger.info(f"Fetching Jupiter quote: {amount_atomic} {input_mint} -> {output_mint} (Slippage: {slippage_val}bps)")
        retries = 3
        delay = 1
        for attempt in range(retries):
            try:
                response = await self.http_client.get(url, params=params, timeout=20.0)
                response.raise_for_status() # Raise HTTP errors
                quote_data = response.json()
                self.logger.debug(f"Jupiter quote response: {json.dumps(quote_data, indent=2)}")

                if not quote_data or 'outAmount' not in quote_data:
                    self.logger.error("Invalid quote response received from Jupiter.")
                    return None
                self.logger.info(f"Received Jupiter quote: In {quote_data.get('inAmount')} -> Out {quote_data.get('outAmount')}")
                return quote_data
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e: # Catch retryable errors
                logger.warning(f"Attempt {attempt + 1}/{retries} failed fetching Jupiter quote: {e}")
                if attempt == retries - 1:
                    error_body = "Unknown error"
                    if isinstance(e, httpx.HTTPStatusError):
                        try: error_body = await e.response.text()
                        except Exception: pass
                        # Log CRITICAL on final retry failure
                        logger.critical(f"Final attempt failed fetching Jupiter quote after {retries} retries: Status {e.response.status_code} - {error_body}", exc_info=False)
                    else:
                         # Log CRITICAL on final retry failure
                         logger.critical(f"Final attempt failed fetching Jupiter quote after {retries} retries: {e}", exc_info=False)
                    self.circuit_breaker.increment_failures()
                    return None
                await asyncio.sleep(delay * (2 ** attempt))
            except Exception as e:
                self.logger.error(f"Unexpected error fetching Jupiter quote: {e}", exc_info=True)
                self.circuit_breaker.increment_failures()
                return None # Don't retry unexpected errors
        return None # Should not be reached

    async def _get_jupiter_swap_tx(self, quote_response: Dict[str, Any], **kwargs) -> Optional[str]:
        """Gets the serialized transaction for a given Jupiter quote response."""
        if self.circuit_breaker.check():
            logger.warning("Circuit breaker active. Skipping Jupiter swap transaction fetch.")
            return None
                
        url = f"{self.jupiter_api_base_url}/swap"
        wallet_address = self.wallet_manager.get_public_key()
        if not wallet_address:
             self.logger.error("Cannot get swap transaction: Wallet address not available.")
             return None

        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": str(wallet_address),
            "wrapAndUnwrapSol": True, # Automatically handle SOL wrapping/unwrapping
            "asLegacyTransaction": False, # Request VersionedTransaction
            # Optional parameters for compute units and priority fees:
            # "dynamicComputeUnitLimit": True, # Let Jupiter recommend CU limit dynamically (preferred if available)
            # "computeUnitPriceMicroLamports": ..., # Explicit CU price (alternative to dynamic)
            # "prioritizationFeeLamports": "auto" # or specify lamports e.g., 10000
        }
        # Only add compute unit price if explicitly set and not using dynamic CU
        if self.compute_unit_price_micro_lamports and not payload.get("dynamicComputeUnitLimit"):
             payload["computeUnitPriceMicroLamports"] = self.compute_unit_price_micro_lamports
             # If setting price, you might need to set limit too unless using dynamic
             # if self.compute_unit_limit:
             #     payload["computeUnitLimit"] = self.compute_unit_limit

        # --- Allow Overrides for Priority Fees --- 
        # Passed from execute_jupiter_swap if provided
        priority_fee_override = kwargs.get('priority_fee_override')
        if priority_fee_override:
             # Ensure it's treated as lamports if it's just a number, or handle "auto"
            if isinstance(priority_fee_override, (int, float)) and priority_fee_override > 0:
                payload["prioritizationFeeLamports"] = int(priority_fee_override)
            elif isinstance(priority_fee_override, str) and priority_fee_override.lower() == 'auto':
                payload["prioritizationFeeLamports"] = "auto"
            else:
                self.logger.warning(f"Ignoring invalid priority_fee_override: {priority_fee_override}")
        elif self.settings.COMPUTE_UNIT_PRICE_MICRO_LAMPORTS and not payload.get("dynamicComputeUnitLimit"):
            # Fallback to compute unit price if no override and not dynamic
            payload["computeUnitPriceMicroLamports"] = self.compute_unit_price_micro_lamports
        # --- End Override Logic --- 

        self.logger.info(f"Requesting Jupiter swap transaction with payload: {payload}")
        retries = 3
        delay = 1
        for attempt in range(retries):
            try:
                response = await self.http_client.post(url, json=payload, timeout=30.0)
                response.raise_for_status()
                swap_data = response.json()
                self.logger.debug(f"Jupiter swap response: {json.dumps(swap_data, indent=2)}")

                if not swap_data or "swapTransaction" not in swap_data:
                    self.logger.error("Invalid swap response received from Jupiter (missing 'swapTransaction').")
                    # This is an API logic error, not likely retryable
                    return None 

                return swap_data["swapTransaction"] # This is the base64 encoded Versioned Tx
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(f"Attempt {attempt + 1}/{retries} failed getting Jupiter swap tx: {e}")
                if attempt == retries - 1:
                    error_body = "Unknown error"
                    if isinstance(e, httpx.HTTPStatusError):
                         try: error_body = await e.response.text()
                         except Exception: pass
                         # Log CRITICAL on final retry failure
                         logger.critical(f"Final attempt failed getting Jupiter swap tx after {retries} retries: Status {e.response.status_code} - {error_body}", exc_info=False)
                    else:
                         # Log CRITICAL on final retry failure
                         logger.critical(f"Final attempt failed getting Jupiter swap tx after {retries} retries: {e}", exc_info=False)
                    self.circuit_breaker.increment_failures()
                    return None
                await asyncio.sleep(delay * (2 ** attempt))
            except Exception as e:
                self.logger.error(f"Unexpected error getting Jupiter swap tx: {e}", exc_info=True)
                self.circuit_breaker.increment_failures()
                return None # Don't retry unexpected errors
        return None # Should not be reached

    async def _sign_and_send_jupiter_tx(self, swap_tx_base64: str) -> Optional[str]:
        """Signs and sends the base64 encoded transaction from Jupiter."""
        if self.circuit_breaker.check():
            logger.warning("Circuit breaker active. Skipping transaction signing and sending.")
            return None

        keypair = self.wallet_manager.get_keypair()
        if not keypair:
            self.logger.error("Cannot sign transaction: Wallet keypair not loaded.")
            return None

        try:
            # Decode and deserialize the transaction
            tx_bytes = base64.b64decode(swap_tx_base64)
            versioned_tx = VersionedTransaction.from_bytes(tx_bytes)
            self.logger.debug("Successfully deserialized Jupiter transaction.")

            # Sign the transaction message using the keypair
            message_bytes = versioned_tx.message.serialize()
            signature = keypair.sign_message(message_bytes)

            # Versioned transactions have a list of signatures. The fee payer's is first.
            # Jupiter's tx usually has one empty signature placeholder. Replace it.
            if len(versioned_tx.signatures) == 1:
                versioned_tx.signatures[0] = signature
            else:
                # Fallback if structure is different (shouldn't happen with V6)
                versioned_tx.signatures = [signature] + versioned_tx.signatures[1:]

            self.logger.debug("Successfully signed Jupiter transaction.")

            # Define transaction options
            opts = TxOpts(skip_preflight=False, preflight_commitment=Processed, skip_confirmation=True)

            # Send the SIGNED transaction using the shared client
            self.logger.info("Sending signed transaction to Solana network...")
            tx_signature_result = await self.solana_client.send_transaction(versioned_tx, opts=opts)
            signature_str = str(tx_signature_result.value)
            self.logger.info(f"Transaction submitted successfully! Signature: {signature_str}")

            # Confirmation is handled by TransactionTracker
            return signature_str

        except RPCException as e: # Catch RPCException from core
            self.logger.error(f"RPC error sending transaction: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
            return None
        except ValueError as e:
             self.logger.error(f"Value error processing Jupiter transaction (decode/deserialize): {e}", exc_info=True)
             self.circuit_breaker.increment_failures()
             return None
        except Exception as e:
            self.logger.error(f"Unexpected error signing/sending transaction: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()
            return None
            
    async def execute_jupiter_swap(
        self,
        trade_id: int,
        input_mint: str,
        output_mint: str,
        input_amount: float,
        input_decimals: int,
        slippage_bps: Optional[int] = None,
        priority_fee_override: Optional[int] = None,
        slippage_bps_override: Optional[int] = None
    ) -> Optional[str]:
        """Executes a swap via Jupiter API or simulates if paper trading is enabled."""
            
        async with self._execution_lock:
            if trade_id in self._pending_trades:
                logger.warning(f"Trade {trade_id} is already being processed. Skipping duplicate execution.")
                return None
            self._pending_trades.add(trade_id)

            try:
                # Check if paper trading is enabled
                if self.paper_trader and self.settings.PAPER_TRADING_ENABLED:
                    self.logger.info(f"[Paper Trade] Attempting to execute paper trade ID: {trade_id} for {input_amount:.8f} of {input_mint} to {output_mint}")
                    
                    action: Optional[str] = None
                    traded_mint: Optional[str] = None
                    simulated_amount_traded: float = 0.0

                    if input_mint == self.settings.SOL_MINT:
                        action = "BUY"
                        traded_mint = output_mint
                        # For a BUY, input_amount is the SOL to spend.
                        # We need to calculate how much of traded_mint is bought.
                    elif output_mint == self.settings.SOL_MINT:
                        action = "SELL"
                        traded_mint = input_mint
                        simulated_amount_traded = input_amount # Amount of token being sold
                    else:
                        self.logger.error(f"[Paper Trade] Trade {trade_id} is not a SOL pair ({input_mint}/{output_mint}). Paper trading currently supports SOL pairs only.")
                        return None # Or handle as error

                    if not traded_mint or not action:
                        self.logger.error(f"[Paper Trade] Could not determine action or traded_mint for trade {trade_id}.")
                        return None

                    # Get simulated price from PriceMonitor
                    # Use a short max_age to prefer fresh prices for paper trades
                    simulated_price_usd = await self.price_monitor.get_current_price_usd(traded_mint, max_age_seconds=60)

                    if simulated_price_usd is None:
                        self.logger.error(f"[Paper Trade] Could not get price from PriceMonitor for {traded_mint} for trade {trade_id}. Cannot execute paper trade.")
                        return None
                    
                    self.logger.info(f"[Paper Trade] Using simulated price for {traded_mint}: ${simulated_price_usd:.6f}")

                    if action == "BUY":
                        if simulated_price_usd > 0:
                            simulated_amount_traded = input_amount / simulated_price_usd # input_amount is SOL here
                        else:
                            self.logger.error(f"[Paper Trade] Simulated price for {traded_mint} is ${simulated_price_usd:.6f}, cannot calculate BUY amount for trade {trade_id}.")
                            return None
                    # For SELL, simulated_amount_traded is already set to input_amount

                    paper_trade_successful = await self.paper_trader.execute_trade(
                        trade_id=trade_id,
                        action=action,
                        mint=traded_mint,
                        price=simulated_price_usd,
                        amount=simulated_amount_traded
                    )

                    if paper_trade_successful:
                        self.logger.info(f"[Paper Trade] Successfully processed for trade ID {trade_id}.")
                        return f"PAPER_TRADE_SUCCESS_{trade_id}"
                    else:
                        self.logger.error(f"[Paper Trade] Failed to execute paper trade via PaperTrading class for trade ID {trade_id}.")
                        return None

                # --- Live Trading Logic --- 
                self.logger.info(f"[Live Trade] Attempting to execute trade ID: {trade_id} for {input_amount:.8f} of {input_mint} to {output_mint}")
                
                # Convert amount to atomic units
                input_amount_atomic = int(input_amount * (10**input_decimals))
                    
                # Validate trade before proceeding (applies to live trades)
                # For paper trades, validation might be different or skipped depending on testing goals
                if not self.settings.PAPER_TRADING_ENABLED: # Only validate for live trades for now
                    can_trade, validation_msg = await self.trade_validator.validate_trade(
                    input_mint=input_mint,
                    output_mint=output_mint,
                        amount_atomic=input_amount_atomic,
                    slippage_bps=slippage_bps or self.slippage_bps
                    )
                    if not can_trade:
                        logger.error(f"Trade {trade_id} failed validation: {validation_msg}")
                    return None
                
                # Get quote with retries
                quote = await self._fetch_jupiter_quote(
                    input_mint=input_mint,
                    output_mint=output_mint,
                        amount_atomic=input_amount_atomic,
                    slippage_bps=slippage_bps or self.slippage_bps
                )
                
                if not quote:
                    logger.error(f"Failed to get quote for trade {trade_id}")
                    return None
                
                # Get swap transaction
                swap_tx = await self._get_jupiter_swap_tx(
                    quote_response=quote,
                    priority_fee_override=priority_fee_override
                )
                
                if not swap_tx:
                    logger.error(f"Failed to get swap transaction for trade {trade_id}")
                    return None
                
                # Sign and send transaction
                signature = await self._sign_and_send_jupiter_tx(swap_tx)
                
                if signature:
                    # Update trade status and track transaction
                    await self.db.update_trade_status(trade_id, "pending", signature)
                    if self.transaction_tracker:
                        await self.transaction_tracker.track_transaction(signature, trade_id)
                    
                        # Update position tracking handled by DB layer on confirmation
                        logger.info(f"Trade {trade_id} submitted for live execution. Signature: {signature}")
                    return signature
                    
                return None
            
            except Exception as e:
                logger.error(f"Error executing trade {trade_id}: {e}", exc_info=True)
                await self.db.update_trade_status(trade_id, "failed", error_message=str(e))
                self.circuit_breaker.increment_failures()
                return None
                
            finally:
                self._pending_trades.discard(trade_id)

        return None # Should be unreachable if logic flows correctly

    async def _update_position_after_trade(self, trade_id: int, input_mint: str, output_mint: str, input_amount: float):
        """DEPRECATED or for in-memory cache only. Main position updates via DB methods.
        Update in-memory position tracking after a successful trade submission (not confirmation).
        Actual DB position update should happen upon TX confirm.
        """
        self.logger.warning("_update_position_after_trade is likely deprecated or for in-memory cache. DB positions updated on TX confirm.")
        # This logic was simplified and might not be robust for all cases, 
        # especially with the new Position model in DB.
        # Example for in-memory cache:
        # try:
        #     action = "BUY" if input_mint == self.settings.SOL_MINT else "SELL"
        #     traded_token = output_mint if action == "BUY" else input_mint
        #     current_qty = self.positions.get(traded_token, 0.0)
        #     
        #     # This is a very rough estimate of quantity from a Jupiter trade input
        #     # Real quantity comes from tx confirmation or quote.outAmount
        #     # For now, just logging that a trade happened. We can't accurately update in-memory qty here.
        #     
        #     # self.positions[traded_token] = new_qty
        #     # self.logger.info(f"In-memory position cache updated for {traded_token}: {self.positions[traded_token]}")
        #     pass # Skip complex in-memory logic, rely on DB post-confirmation
        # except Exception as e:
        #     self.logger.error(f"Error updating in-memory position after trade {trade_id}: {e}")
        #     # self.circuit_breaker.increment_failures() # Careful with CB here

    async def close(self):
        """Closes any resources owned by OrderManager."""
        # Since http_client is shared, we don't close it here.
        # If OrderManager created other resources (e.g., specific listeners), close them.
        logger.info("OrderManager closed (no owned resources).")

    # --- Position and Order Management (DB Interaction) ---

    async def load_state(self):
        """Load active positions and orders from the database."""
        try:
            # Use the new method names without owner_address
            if hasattr(self.db, 'fetch_active_positions'):
                 self.positions = await self.db.fetch_active_positions()
                 self.logger.info(f"Loaded {len(self.positions)} active positions from DB.")
            else:
                 self.logger.error("Database object missing 'fetch_active_positions' method.")
                 self.positions = []
            
            if hasattr(self.db, 'fetch_active_orders'):
                 self.orders = await self.db.fetch_active_orders()
                 self.logger.info(f"Loaded {len(self.orders)} active orders from DB.")
            else:
                 self.logger.error("Database object missing 'fetch_active_orders' method.")
                 self.orders = []
            
            # Log the fetched data for debugging
            self.logger.debug(f"Fetched positions: {self.positions}")
            self.logger.debug(f"Fetched orders: {self.orders}")
            
            self.logger.info("OrderManager state initialized (positions/orders loaded).")
            
        except Exception as e:
            self.logger.error(f"Error loading OrderManager state: {e}", exc_info=True)
            # Decide how to handle failure - maybe start with empty state?
            self.positions = []
            self.orders = []

    async def _save_order(self, order_data: Dict):
        """Saves or updates an order in the database."""
        trade_id = order_data.get('trade_id')
        self.logger.debug(f"Saving/Updating order {trade_id} to DB (placeholder)... Order data: {order_data}")
        try:
            # Assuming a DB method like upsert_order or similar
            # await self.db.upsert_order(order_data)
            # Update local cache if needed
            if trade_id:
                self.orders[trade_id] = order_data
            self.logger.info(f"Order {trade_id} saved/updated in DB (simulated). Status: {order_data.get('status')}")
        except AttributeError:
            self.logger.error(f"Database object does not have required method for saving order {trade_id}.")
        except Exception as e:
            self.logger.error(f"Error saving order {trade_id} to DB: {e}", exc_info=True)

    async def _update_position(self, token_address: str, quantity_change: float, cost_basis_change: float):
        """Updates a position in the database based on a filled order."""
        # This is a simplified example. Real implementation needs careful handling
        # of average price, quantity, realized/unrealized PnL etc.
        self.logger.debug(f"Updating position {token_address} in DB (placeholder)... Change: {quantity_change}")
        try:
            # Assuming a DB method like update_position_from_fill exists
            # current_position = self.positions.get(token_address, {})
            # await self.db.update_position_from_fill(self.wallet_pubkey, token_address, quantity_change, cost_basis_change)
            # Refresh local cache after update
            # await self._load_positions() # Or update local dict directly
            self.logger.info(f"Position {token_address} updated in DB (simulated).")
        except AttributeError:
            self.logger.error(f"Database object does not have required method for updating position {token_address}.")
        except Exception as e:
            self.logger.error(f"Error updating position {token_address} in DB: {e}", exc_info=True)

    # --- Placeholder methods for updating state (called internally or by strategies) ---
    # These would interact with self.db and update self.positions/self.orders

    async def _update_order_in_cache(self, order_data: Dict):
        """Updates the local cache of orders."""
        trade_id = order_data.get('trade_id')
        if trade_id:
            self.orders[trade_id] = order_data
            logger.debug(f"Updated order cache for trade_id {trade_id}")
        else:
            logger.warning("Attempted to update order cache with missing trade_id")

    async def _update_position_in_cache(self, position_data: Dict):
        """Updates the local cache of positions."""
        token_address = position_data.get('token_address')
        if token_address:
             self.positions[token_address] = position_data
             logger.debug(f"Updated position cache for {token_address}")
        else:
             logger.warning("Attempted to update position cache with missing token_address")
             
    async def _remove_order_from_cache(self, trade_id: int):
        """Removes an order from the local cache (e.g., when finalized/cancelled)."""
        if trade_id in self.orders:
            del self.orders[trade_id]
            logger.debug(f"Removed order {trade_id} from cache.")
            
    async def _remove_position_from_cache(self, token_address: str):
        """Removes a position from the local cache (e.g., when closed)."""
        if token_address in self.positions:
            del self.positions[token_address]
            logger.debug(f"Removed position {token_address} from cache.")

    # --- Public methods for accessing state --- 
    # Provide read-only access to the cached state

    def get_position(self, token_address: str) -> Optional[Dict]:
        """Gets the current position for a token from the loaded state."""
        return self.positions.get(token_address)

    def get_order(self, trade_id: int) -> Optional[Dict]:
        """Gets an order by its ID from the loaded state."""
        return self.orders.get(trade_id)

    def get_all_positions(self) -> Dict[str, Dict]:
        """Returns all currently loaded positions."""
        # Return a copy to prevent external modification
        return self.positions.copy()
        
    def get_all_active_orders(self) -> Dict[int, Dict]:
        """Returns all currently loaded active orders."""
        # Return a copy to prevent external modification
        return self.orders.copy()

    # Removed old place_order, get_balance as they were placeholders or handled elsewhere.
    # Removed _save_order and _update_position placeholders - DB interaction should 
    # happen in specific methods (like execute_swap updating status, or dedicated 
    # position update methods called after trade confirmation).