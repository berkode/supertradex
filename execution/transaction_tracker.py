import logging
import asyncio
import os
from typing import Optional, Dict, List
from dotenv import load_dotenv
import time
from datetime import datetime, timezone

# Import Solana-related types
from solana.rpc.async_api import AsyncClient
from solders.signature import Signature
from solana.rpc.types import TxOpts  # Changed from solders
from solana.rpc.commitment import Commitment, Confirmed, Processed # Changed from solders
from solana.rpc.core import RPCException # Changed import location again
from solders.transaction_status import TransactionConfirmationStatus

# Import settings and database
from config.settings import Settings
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType
from data.token_database import TokenDatabase # Explicitly import for type hint
from utils.logger import get_logger
from sqlalchemy import text # Added import
from data.models import Trade as TradeModel # Import the specific model if needed for type hinting

load_dotenv()
logger = logging.getLogger(__name__)

class TransactionTracker:
    """
    Monitors transaction statuses based on signatures stored in the database.
    Focuses on confirming transactions that have been sent ('completed' status).
    Logs confirmed BUY trades to the trade_log.
    """

    def __init__(self, solana_client: AsyncClient, db: TokenDatabase, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.max_retries = getattr(self.settings, 'TX_CONFIRM_MAX_RETRIES', 10)
        self.base_retry_delay = getattr(self.settings, 'TX_CONFIRM_DELAY_SECONDS', 1.0)
        self.confirmation_commitment = "confirmed"
        self.solana_client = solana_client
        self.db = db
        
        # Initialize circuit breaker with more lenient settings
        self.circuit_breaker = CircuitBreaker(
            breaker_type=CircuitBreakerType.COMPONENT,
            identifier="transaction_tracker",
            on_activate=self._on_circuit_breaker_activate,
            on_reset=self._on_circuit_breaker_reset
        )
        
        # Transaction tracking
        self._pending_transactions = {}  # Track transactions being monitored
        self._transaction_history = {}   # Track transaction history
        
        if not self.solana_client:
            logger.error("TransactionTracker initialized without a valid Solana client!")
        if not self.db:
            logger.error("TransactionTracker initialized without a valid Database client!")
            
        logger.info(f"TransactionTracker initialized. Max Retries: {self.max_retries}, Base Delay: {self.base_retry_delay}s")

        self.logger = get_logger(__name__)
        self.lock = asyncio.Lock()

    def _on_circuit_breaker_activate(self) -> None:
        """Callback when circuit breaker activates."""
        logger.error("Circuit breaker activated - transaction tracking operations suspended")
        # TODO: Add notification to admin/telegram

    def _on_circuit_breaker_reset(self) -> None:
        """Callback when circuit breaker resets."""
        logger.info("Circuit breaker reset - transaction tracking operations resumed")
        # TODO: Add notification to admin/telegram

    async def track_transaction(self, tx_hash: str, trade_id: int) -> bool:
        """Track a new transaction.
        
        Args:
            tx_hash: Transaction hash to track, or paper trade placeholder
            trade_id: Associated trade ID
            
        Returns:
            bool: True if transaction was added for tracking or paper trade handled, False otherwise
        """
        async with self.lock:
            try:
                # Handle Paper Trading Placeholder
                if tx_hash.startswith("PAPER_TRADE_SUCCESS_"):
                    self.logger.info(f"Paper trade {trade_id} (placeholder: {tx_hash}) marked as completed by OrderManager.")
                    # TransactionTracker doesn't need to do more for paper trades here,
                    # as OrderManager already updated DB status to 'paper_completed'.
                    # We could add it to _transaction_history if desired for local tracking.
                    self._transaction_history[tx_hash] = {
                        'trade_id': trade_id,
                        'status': 'paper_completed',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                    return True

                if tx_hash in self._pending_transactions:
                    self.logger.warning(f"Transaction {tx_hash} is already being tracked")
                    return False
                    
                self._pending_transactions[tx_hash] = {
                    'trade_id': trade_id,
                    'status': 'pending'
                }
                
                # Update trade status in database
                await self.db.update_trade_status(trade_id, 'submitted', tx_hash)
                
                self.logger.info(f"Started tracking transaction {tx_hash} for trade {trade_id}")
                return True
                
            except Exception as e:
                self.logger.error(f"Error tracking transaction {tx_hash}: {e}")
                return False

    async def check_and_confirm_transactions(self):
        """Check the status of pending transactions and update the database."""
        try:
            # Get trades with statuses indicating they might need checking
            # Use the ORM method we confirmed exists in TokenDatabase
            pending_trades = await self.db.get_pending_trades()
            
            if not pending_trades:
                # self.logger.debug("No pending transactions to check.")
                return

            self.logger.info(f"Checking status for {len(pending_trades)} pending trade(s)...")
            
            # Prepare tasks for checking each transaction
            tasks = [
                self._check_single_transaction(trade)
                for trade in pending_trades
            ]
            
            # Run checks concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results (log errors, etc.)
            for i, result in enumerate(results):
                trade_id = pending_trades[i].id # Assuming TradeModel has an id
                if isinstance(result, Exception):
                    self.logger.error(f"Error checking transaction for trade {trade_id}: {result}", exc_info=result)
                    # Optionally update trade status to an error state here
                elif result: # If _check_single_transaction returned something (e.g., True on update)
                    self.logger.debug(f"Successfully processed status check for trade {trade_id}")

        except Exception as e:
            self.logger.error(f"Error fetching or processing pending trades: {e}", exc_info=True)
            self.circuit_breaker.increment_failures()

    async def _check_single_transaction(self, trade: TradeModel) -> bool:
        """Check status of a single transaction signature."""
        tx_hash = trade.transaction_hash
        trade_id = trade.id

        if not tx_hash:
            self.logger.warning(f"Trade {trade_id} has status '{trade.status}' but no transaction hash. Skipping check.")
            return False

        # If it's a paper trade placeholder that somehow reached here (e.g., DB status was not 'paper_completed')
        # we can treat it as confirmed immediately.
        if tx_hash.startswith("PAPER_TRADE_SUCCESS_"):
            self.logger.info(f"Paper trade {trade_id} (placeholder: {tx_hash}) encountered in _check_single_transaction. Marking as confirmed.")
            await self.db.update_trade_status(trade_id, 'paper_completed', notes="Paper trade confirmed by tracker.")
            # Potentially update position if PaperTrading class doesn't or if a unified position manager is used
            # await self.db.update_position_from_trade(trade) # This might need adjustment for paper trades
            return True

        try:
            # Use Solana client to get transaction status
            self.logger.debug(f"Checking signature: {tx_hash} for trade {trade_id}")
            response = await self.solana_client.get_signature_statuses([tx_hash], search_transaction_history=True)
            
            if not response or not response['result'] or not response['result']['value'] or response['result']['value'][0] is None:
                self.logger.warning(f"Could not get status for signature {tx_hash} (trade {trade_id}). Still pending or TX not found?")
                # Decide if we should retry later or mark as potentially failed after N attempts
                return False
                
            status = response['result']['value'][0]
            confirmation_status = status.get('confirmationStatus')
            err = status.get('err')
            
            self.logger.debug(f"Signature {tx_hash} status: Confirmation='{confirmation_status}', Error='{err}'")

            if err:
                error_message = f"Transaction failed: {err}"
                self.logger.error(error_message + f" (Trade ID: {trade_id})")
                # Update trade status to failed in DB
                await self.db.update_trade_status(trade_id, 'failed', details={'error_message': str(err)})
                # If it was a BUY, we need to potentially revert position or mark as failed entry
                if trade.action == 'BUY':
                     # Add logic here if needed to handle failed buy impacting positions
                     pass 
                # If it was a SELL that failed, the position remains open. Log and potentially retry sell later?
                elif trade.action == 'SELL':
                     # Add logic here if needed for failed sells
                     pass
                return True # Indicate processing occurred

            elif confirmation_status in ['confirmed', 'finalized']:
                self.logger.info(f"Transaction {tx_hash} confirmed/finalized for trade {trade_id}.")
                # Fetch detailed transaction to get actual amounts if needed
                actual_output_amount = await self._get_actual_output_from_tx(tx_hash) 
                
                # Update trade status to confirmed in DB
                await self.db.update_trade_status(trade_id, 'confirmed', details={'actual_output_amount': actual_output_amount})
                
                # Update position based on confirmed trade
                await self.db.update_position_from_trade(trade)
                return True # Indicate processing occurred

            else: # Status is 'processed' but not confirmed/finalized yet
                self.logger.debug(f"Transaction {tx_hash} is processed but awaiting further confirmation ('{confirmation_status}'). Trade {trade_id}")
                return False # Still pending

        except Exception as e:
            self.logger.error(f"Error checking signature {tx_hash} (trade {trade_id}): {e}", exc_info=True)
            # Do not increment circuit breaker here, handled in the calling function
            raise # Re-raise exception to be caught by asyncio.gather

    async def _get_actual_output_from_tx(self, tx_hash: str) -> Optional[float]:
        """Fetch detailed transaction and attempt to parse actual output amount."""
        try:
            # Fetch the full transaction details
            # Adjust encoding and commitment level as needed
            tx_response = await self.solana_client.get_transaction(
                tx_hash, 
                encoding='jsonParsed', 
                max_supported_transaction_version=0 # Specify version if needed
            )
            
            if not tx_response or not tx_response['result']:
                self.logger.warning(f"Could not fetch detailed transaction for {tx_hash}")
                return None
                
            tx_details = tx_response['result']
            meta = tx_details.get('meta')
            if not meta or meta.get('err'):
                self.logger.warning(f"Transaction {tx_hash} meta contains error or is missing, cannot get output amount.")
                return None

            # --- Parsing Logic (Highly Dependent on DEX/Program) ---
            # This is a simplified example, real parsing is complex.
            # Look at pre/post token balances for the user's wallet.
            # Need user's public key (WalletManager?)
            # Need input/output token mint addresses (from the trade record)
            
            # Placeholder: Return None for now
            self.logger.debug(f"Placeholder: Actual output amount parsing not implemented for {tx_hash}")
            return None 
            
            # Example (Conceptual - Needs real implementation):
            # owner_pubkey = self.wallet_manager.get_public_key() 
            # output_token_mint = trade.output_token_address
            # 
            # pre_balances = meta.get('preTokenBalances', [])
            # post_balances = meta.get('postTokenBalances', [])
            # 
            # pre_amount = 0
            # post_amount = 0
            # 
            # for balance in pre_balances:
            #     if balance.get('owner') == owner_pubkey and balance.get('mint') == output_token_mint:
            #         pre_amount = float(balance.get('uiTokenAmount', {}).get('uiAmount', 0))
            #         break
            #         
            # for balance in post_balances:
            #     if balance.get('owner') == owner_pubkey and balance.get('mint') == output_token_mint:
            #         post_amount = float(balance.get('uiTokenAmount', {}).get('uiAmount', 0))
            #         break
            #         
            # if post_amount > pre_amount:
            #     actual_output = post_amount - pre_amount
            #     self.logger.info(f"Parsed actual output for {tx_hash}: {actual_output}")
            #     return actual_output
            # else:
            #     self.logger.warning(f"Could not determine actual output increase for {tx_hash}")
            #     return None

        except Exception as e:
            self.logger.error(f"Error parsing transaction details for {tx_hash}: {e}", exc_info=True)
            return None

    def get_pending_transactions(self) -> List[str]:
        """Returns a list of transaction hashes currently being tracked (placeholder)."""
        # This method might need actual implementation based on how pending trades are managed
        # For now, return empty list as an example
        self.logger.warning("get_pending_transactions is a placeholder.")
        return []
        
    # ... (other methods like add_tracked_transaction if needed) ...

    async def _log_confirmed_trade(self, trade_id: int, tx_hash: str, actual_output_amount: Optional[float]) -> None:
        """Logs a confirmed trade (BUY or SELL) to the trade_log table."""
        try:
            # Fetch the original trade details from the 'trades' table
            trade_details = await self.db.fetch_one_dict("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
            
            if not trade_details:
                logger.error(f"Cannot log trade for trade_id {trade_id}: Details not found in 'trades' table.")
                return

            # Determine if it's a BUY or SELL trade
            output_token = trade_details.get('output_token_address')
            input_token = trade_details.get('input_token_address')
            QUOTE_MINTS = ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]
            
            is_buy_trade = input_token in QUOTE_MINTS and output_token not in QUOTE_MINTS
            is_sell_trade = output_token in QUOTE_MINTS and input_token not in QUOTE_MINTS
            
            if not (is_buy_trade or is_sell_trade):
                logger.debug(f"Skipping trade log entry for trade_id {trade_id}: Not identified as a BUY or SELL trade.")
                return
                
            # Calculate price
            entry_price = trade_details.get('entry_price')
            if not entry_price and trade_details.get('input_amount') and actual_output_amount:
                try:
                    entry_price = float(trade_details['input_amount']) / actual_output_amount
                except (TypeError, ZeroDivisionError):
                    entry_price = None
                    
            if not entry_price:
                logger.warning(f"Could not determine price for trade_id {trade_id} to log.")
                entry_price = 0.0

            if is_buy_trade:
                # Log BUY trade entry
                entry_data = {
                    'trade_ref_id': trade_id,
                    'token_address': output_token,
                    'entry_timestamp': trade_details.get('confirmed_at') or datetime.now(timezone.utc),
                    'entry_price': entry_price,
                    'entry_quantity': actual_output_amount or 0.0,
                    'entry_tx_hash': tx_hash,
                    'entry_strategy': trade_details.get('strategy')
                }
                await self.db.log_trade_entry(entry_data)
            else:
                # Log SELL trade exit
                exit_data = {
                    'trade_ref_id': trade_id,
                    'token_address': input_token,
                    'exit_timestamp': trade_details.get('confirmed_at') or datetime.now(timezone.utc),
                    'exit_price': entry_price,
                    'exit_quantity': actual_output_amount or 0.0,
                    'exit_tx_hash': tx_hash,
                    'exit_reason': trade_details.get('metadata', {}).get('exit_reason', 'strategy'),
                    'entry_tx_hash': trade_details.get('metadata', {}).get('entry_tx_hash')
                }
                await self.db.log_trade_exit(exit_data)
            
        except Exception as e:
            logger.error(f"Error during _log_confirmed_trade for trade_id {trade_id}: {e}", exc_info=True)

    async def _confirm_tx_with_retries(self, trade_id: int, tx_hash: str):
        """Attempts to confirm a transaction signature with retries and exponential backoff."""
        if tx_hash not in self._pending_transactions:
            logger.warning(f"Transaction {tx_hash} not found in pending transactions. Starting new tracking.")
            await self.track_transaction(tx_hash, trade_id)
            
        tx_info = self._pending_transactions[tx_hash]
        tx_info["attempts"] += 1
        tx_info["last_check"] = datetime.now().isoformat()
        
        try:
            signature = Signature.from_string(tx_hash)
        except ValueError:
            logger.error(f"Invalid transaction hash format for trade_id {trade_id}: {tx_hash}")
            await self._update_trade_status(trade_id, 'failed', f"Invalid signature format: {tx_hash}")
            return

        start_time = time.monotonic()
        for attempt in range(self.max_retries):
            delay = self.base_retry_delay * (1.5 ** attempt)
            max_delay = 30
            actual_delay = min(delay, max_delay)

            if attempt > 0:
                logger.debug(f"Retrying confirmation for {tx_hash} (Attempt {attempt + 1}/{self.max_retries}), waiting {actual_delay:.2f}s...")
                await asyncio.sleep(actual_delay)

            try:
                status_response = await self.solana_client.get_signature_statuses([signature])

                if not status_response or not status_response.value or status_response.value[0] is None:
                    logger.debug(f"Transaction {tx_hash} not yet found (Attempt {attempt + 1}).")
                    continue

                tx_status = status_response.value[0]

                if tx_status.err:
                    error_message = f"Transaction failed on-chain: {tx_status.err}"
                    logger.warning(f"{error_message} (Trade ID: {trade_id}, Tx: {tx_hash})")
                    await self._update_trade_status(trade_id, 'failed', error_message)
                    self._record_transaction_history(tx_hash, 'failed', error_message)
                    return

                current_commitment = tx_status.confirmation_status
                target_reached = False
                
                if self.confirmation_commitment == Commitment.Processed:
                    target_reached = True
                elif self.confirmation_commitment == Commitment.Confirmed:
                    target_reached = current_commitment in [TransactionConfirmationStatus.Confirmed, TransactionConfirmationStatus.Finalized]
                elif self.confirmation_commitment == Commitment.Finalized:
                    target_reached = current_commitment == TransactionConfirmationStatus.Finalized

                if current_commitment:
                    logger.debug(f"Tx {tx_hash} status: {current_commitment} (Target: {self.confirmation_commitment})")
                    
                    if target_reached and self.confirmation_commitment != Commitment.Processed:
                        elapsed = time.monotonic() - start_time
                        logger.info(f"Transaction {tx_hash} confirmed successfully at {current_commitment} level for trade ID {trade_id} after {elapsed:.2f}s.")
                        
                        # Get actual output amount if possible
                        actual_output_amount = await self._get_transaction_output_amount(signature, trade_id)
                        
                        # Update trade status
                        update_ok = await self._update_trade_status(trade_id, 'confirmed', actual_output_amount=actual_output_amount)
                        
                        if update_ok:
                            logger.info(f"Triggering position update for confirmed trade {trade_id}...")
                            # Log the trade (BUY or SELL) before updating position
                            await self._log_confirmed_trade(trade_id, tx_hash, actual_output_amount)
                            
                            pos_update_ok = await self.db.update_position_from_trade(trade_id)
                            if not pos_update_ok:
                                logger.critical(f"CRITICAL: Trade {trade_id} status set to 'confirmed', but position update failed!")
                            else:
                                logger.error(f"Failed to update trade {trade_id} status to 'confirmed' in DB.")
                            
                        self._record_transaction_history(tx_hash, 'confirmed', None, actual_output_amount)
                        return
                        
                    elif target_reached:
                        logger.info(f"Transaction {tx_hash} reached Processed state for trade {trade_id}.")
                        self._record_transaction_history(tx_hash, 'processed')
                        return

            except RPCException as e: # Catch RPCException from core
                logger.warning(f"RPC error checking status for {tx_hash} (Attempt {attempt + 1}): {e}")
            except asyncio.TimeoutError:
                logger.warning(f"Timeout checking status for {tx_hash} (Attempt {attempt + 1}). Retrying...")
            except Exception as e:
                logger.error(f"Unexpected error confirming tx {tx_hash}: {e}", exc_info=True)
                await self._update_trade_status(trade_id, 'failed', f"Unexpected confirmation error: {str(e)[:100]}")
                self._record_transaction_history(tx_hash, 'failed', str(e))
                return

        elapsed = time.monotonic() - start_time
        timeout_message = f"Confirmation timed out after {self.max_retries} retries ({elapsed:.2f}s)."
        logger.critical(f"{timeout_message} (Trade ID: {trade_id}, Tx: {tx_hash}).")
        await self._update_trade_status(trade_id, 'failed', timeout_message)
        self._record_transaction_history(tx_hash, 'failed', timeout_message)

    async def _get_transaction_output_amount(self, signature: Signature, trade_id: int) -> Optional[float]:
        """Attempts to get the actual output amount from a confirmed transaction."""
        try:
            tx_details_response = await self.solana_client.get_transaction(
                signature,
                max_supported_transaction_version=0,
                commitment=self.confirmation_commitment
            )
            
            if tx_details_response and tx_details_response.value:
                tx_details = tx_details_response.value
                meta = tx_details.transaction.meta
                if meta:
                    # TODO: Implement robust parsing of token balances
                    # This would compare pre and post token balances
                    # for the owner's account and output token mint
                    # This is complex and requires knowing the owner address and output mint
                    # For now, we might rely on Jupiter quote or pass amount if known
                    pass
                    
            return None
            
        except Exception as e:
            logger.warning(f"Error getting transaction output amount: {e}")
            return None

    async def _update_trade_status(self, trade_id: int, new_status: str, error_message: Optional[str] = None, actual_output_amount: Optional[float] = None) -> bool:
        """Helper method to update trade status in the database."""
        try:
            update_successful = await self.db.update_trade_status(
                trade_id=trade_id,
                new_status=new_status,
                error_message=error_message,
                actual_output_amount=actual_output_amount
            )
            
            if not update_successful:
                logger.error(f"Failed to update trade status in DB for trade_id {trade_id}")
                # Optionally increment circuit breaker here if DB update fails
            else:
                logger.info(f"Updated trade status for trade_id {trade_id} to {new_status}")
                # Clear from pending if it was being actively tracked
                # (Only if _pending_transactions key is tx_hash)
                # if tx_hash and tx_hash in self._pending_transactions:
                #     del self._pending_transactions[tx_hash]
            
            return update_successful
            
        except Exception as e:
            logger.error(f"Error updating trade status for trade_id {trade_id}: {e}", exc_info=True)
            return False

    def _record_transaction_history(self, signature: str, status: str, error_message: Optional[str] = None, output_amount: Optional[float] = None) -> None:
        """Records transaction history for tracking and analysis."""
        if signature in self._pending_transactions:
            tx_info = self._pending_transactions[signature]
            self._transaction_history[signature] = {
                "trade_id": tx_info["trade_id"],
                "start_time": tx_info["start_time"],
                "end_time": datetime.now().isoformat(),
                "attempts": tx_info["attempts"],
                "final_status": status,
                "error_message": error_message,
                "output_amount": output_amount
            }
            del self._pending_transactions[signature]

    def get_transaction_status(self, signature: str) -> Optional[Dict]:
        """Get the current status of a transaction."""
        if signature in self._pending_transactions:
            return self._pending_transactions[signature]
        return self._transaction_history.get(signature)

    def get_transaction_history(self) -> Dict[str, Dict]:
        """Get transaction history."""
        return self._transaction_history.copy()

    def __repr__(self):
        return f"TransactionTracker(Commitment: {self.confirmation_commitment}, Max Retries: {self.max_retries})"

    async def confirm_transaction(self, tx_hash: str, actual_output_amount: Optional[float] = None) -> bool:
        """Mark a transaction as confirmed.
        
        Args:
            tx_hash: Transaction hash to confirm
            actual_output_amount: Actual amount received in the transaction
            
        Returns:
            bool: True if transaction was confirmed, False otherwise
        """
        async with self.lock:
            try:
                if tx_hash not in self._pending_transactions:
                    self.logger.warning(f"Transaction {tx_hash} is not being tracked")
                    return False
                    
                trade_id = self._pending_transactions[tx_hash]['trade_id']
                
                # Update trade status in database
                await self.db.update_trade_status(
                    trade_id=trade_id,
                    new_status='confirmed',
                    actual_output_amount=actual_output_amount
                )
                
                # Remove from pending transactions
                del self._pending_transactions[tx_hash]
                
                self.logger.info(f"Confirmed transaction {tx_hash} for trade {trade_id}")
                return True
                
            except Exception as e:
                self.logger.error(f"Error confirming transaction {tx_hash}: {e}")
                return False
                
    async def fail_transaction(self, tx_hash: str, error_message: str) -> bool:
        """Mark a transaction as failed.
        
        Args:
            tx_hash: Transaction hash that failed
            error_message: Error message explaining the failure
            
        Returns:
            bool: True if transaction was marked as failed, False otherwise
        """
        async with self.lock:
            try:
                if tx_hash not in self._pending_transactions:
                    self.logger.warning(f"Transaction {tx_hash} is not being tracked")
                    return False
                    
                trade_id = self._pending_transactions[tx_hash]['trade_id']
                
                # Update trade status in database
                await self.db.update_trade_status(
                    trade_id=trade_id,
                    new_status='failed',
                    error_message=error_message
                )
                
                # Remove from pending transactions
                del self._pending_transactions[tx_hash]
                
                self.logger.error(f"Transaction {tx_hash} failed for trade {trade_id}: {error_message}")
                return True
                
            except Exception as e:
                self.logger.error(f"Error marking transaction {tx_hash} as failed: {e}")
                return False

    async def close(self):
        """Clean up resources."""
        self.logger.info("Closing TransactionTracker")