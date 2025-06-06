import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from config.settings import Settings
from data.token_database import TokenDatabase
from data.market_data import MarketData
from execution.order_manager import OrderManager
from execution.transaction_tracker import TransactionTracker
from wallet.wallet_manager import WalletManager
from utils.logger import get_logger

logger = get_logger(__name__)

class TradeExecutor:
    """
    Handles the execution of trades based on signals from the StrategyEvaluator.
    """
    def __init__(self,
                 settings: Settings,
                 order_manager: OrderManager,
                 transaction_tracker: TransactionTracker,
                 db: TokenDatabase, # Maintained for compatibility, might not be directly used
                 wallet_manager: WalletManager, # Maintained for compatibility
                 market_data: MarketData # Maintained for compatibility, price info comes in signal
                 ):
        self.settings = settings
        self.order_manager = order_manager
        self.transaction_tracker = transaction_tracker # Will be used to track executed trades
        self.db = db
        self.wallet_manager = wallet_manager
        self.market_data = market_data
        logger.info("TradeExecutor initialized.")

    async def initialize(self):
        """
        Async initialization for TradeExecutor.
        Can be used for any setup requiring await.
        """
        logger.info("TradeExecutor asynchronous initialization complete.")
        # Example: await self.transaction_tracker.load_pending_transactions()
        pass

    async def execute_trade_from_signal(self, order_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a trade based on the provided order_details dictionary from a signal.

        Args:
            order_details: A dictionary containing all necessary information for the trade.
                           Expected keys include:
                           - 'mint': The token mint address.
                           - 'action': 'BUY' or 'SELL'.
                           - 'amount_usd': Optional. The amount in USD to trade.
                           - 'base_token_amount': Optional. The amount in base tokens to trade.
                           - 'price': Optional. The price at which the signal was generated.
                           - 'slippage_bps': Slippage tolerance in basis points.
                           - 'signal_details': The original signal dictionary for metadata.

        Returns:
            A dictionary with:
                - 'success': bool, True if the trade was successfully submitted, False otherwise.
                - 'transaction_id': Optional[str], the transaction signature if successful.
                - 'error': Optional[str], an error message if unsuccessful.
        """
        logger.info(f"TradeExecutor received signal to execute: {order_details}")

        mint_address = order_details.get('mint')
        action = order_details.get('action')
        amount_usd = order_details.get('amount_usd')
        base_token_amount = order_details.get('base_token_amount')
        price = order_details.get('price') # Price at signal generation
        slippage_bps = order_details.get('slippage_bps', self.settings.DEFAULT_SLIPPAGE_BPS if hasattr(self.settings, 'DEFAULT_SLIPPAGE_BPS') else 50) # Default 0.5%

        if not all([mint_address, action]):
            logger.error("TradeExecutor: Missing mint_address or action in order_details.")
            return {"success": False, "error": "Missing mint_address or action"}

        if action.upper() not in ["BUY", "SELL"]:
            logger.error(f"TradeExecutor: Invalid action '{action}'. Must be 'BUY' or 'SELL'.")
            return {"success": False, "error": f"Invalid action: {action}"}

        # Determine trade amount in USD
        final_amount_usd: Optional[float] = None
        if amount_usd:
            final_amount_usd = float(amount_usd)
        elif base_token_amount and price and price > 0:
            final_amount_usd = float(base_token_amount) * float(price)
            logger.info(f"Calculated amount_usd: {final_amount_usd} from base_token_amount: {base_token_amount} and price: {price}")
        else:
            logger.error("TradeExecutor: Insufficient information to determine trade amount (need amount_usd, or base_token_amount and price).")
            return {"success": False, "error": "Insufficient amount information"}

        if final_amount_usd is None or final_amount_usd <= 0:
            logger.error(f"TradeExecutor: Invalid trade amount_usd: {final_amount_usd}")
            return {"success": False, "error": "Invalid trade amount_usd"}
        
        # Prepare metadata for OrderManager
        # The 'signal_details' from StrategyEvaluator contains the raw signal
        # and other context which might be useful for logging or OrderManager.
        # We also add some executor-specific context.
        execution_metadata = {
            "source": "StrategyEvaluatorSignal",
            "signal_details": order_details.get("signal_details", {}), # Original signal
            "executor_received_at": datetime.now(timezone.utc).isoformat(),
            "calculated_amount_usd": final_amount_usd,
            "slippage_bps": slippage_bps
            # Add other relevant details from order_details if needed by OrderManager
        }
        
        # Merge with any existing metadata in order_details if necessary,
        # but for now, signal_details should cover it.
        # metadata.update(order_details.get('metadata', {}))


        transaction_id: Optional[str] = None
        try:
            if action.upper() == "BUY":
                logger.info(f"Executing BUY for {mint_address}, amount_usd: {final_amount_usd}")
                transaction_id = await self.order_manager.execute_buy(
                    token_address=mint_address,
                    amount_usd=final_amount_usd,
                    slippage_bps=slippage_bps,
                    metadata=execution_metadata
                )
            elif action.upper() == "SELL":
                logger.info(f"Executing SELL for {mint_address}, amount_usd: {final_amount_usd}")
                # For SELL, OrderManager might expect amount in tokens or USD.
                # Assuming execute_sell also takes amount_usd for consistency.
                # If it needs token amount, we'd use base_token_amount or calculate it.
                transaction_id = await self.order_manager.execute_sell(
                    token_address=mint_address,
                    amount_usd=final_amount_usd, # Or base_token_amount if OrderManager prefers
                    slippage_bps=slippage_bps,
                    metadata=execution_metadata
                )

            if transaction_id:
                logger.info(f"Trade for {mint_address} ({action}) submitted. Transaction ID: {transaction_id}")
                # Optionally, start tracking with TransactionTracker here if OrderManager doesn't do it.
                # Example: await self.transaction_tracker.add_pending_transaction(transaction_id, order_details)
                return {"success": True, "transaction_id": transaction_id}
            else:
                logger.error(f"OrderManager failed to return a transaction ID for {action} {mint_address}.")
                return {"success": False, "error": "OrderManager did not return transaction ID"}

        except Exception as e:
            logger.error(f"Error during trade execution via OrderManager for {action} {mint_address}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def close(self):
        """
        Clean up any resources used by the TradeExecutor.
        """
        logger.info("TradeExecutor closing.")
        # Example: await self.transaction_tracker.cancel_all_pending()
        pass 