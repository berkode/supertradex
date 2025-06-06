"""
Trading manager module for handling trading operations.
"""

import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from config.settings import Settings
from data.token_database import TokenDatabase
from execution.trade_queue import TradeQueue, TradeRequest, TradePriority
from .wallet_manager import WalletManager

logger = logging.getLogger(__name__)

class TradingManager:
    """
    Manages trading operations, including position closing during shutdown.
    """
    
    def __init__(self, 
                 settings: Settings, 
                 wallet_manager: WalletManager, 
                 db: TokenDatabase,
                 trade_queue: TradeQueue):
        """
        Initialize the trading manager.
        
        Args:
            settings: Application settings
            wallet_manager: Wallet manager instance
            db: TokenDatabase instance
            trade_queue: TradeQueue instance
        """
        self.settings = settings
        self.wallet_manager = wallet_manager
        self.db = db
        self.trade_queue = trade_queue
        logger.info("Trading manager initialized with DB and TradeQueue")
        
    async def execute_strategy(self, token: Dict[str, Any]) -> bool:
        """
        Execute trading strategy for a given token.
        
        Args:
            token: Token information dictionary
            
        Returns:
            bool: True if strategy execution was successful, False otherwise
        """
        try:
            # Log token being processed
            logger.info(f"Processing token: {token.get('symbol', 'Unknown')}")
            
            # Check if we have sufficient balance
            balance = await self.wallet_manager.get_balance()
            min_trade_amount = getattr(self.settings, 'MIN_TRADE_AMOUNT_USD', 1.0)
            if balance < min_trade_amount:
                logger.warning(f"Insufficient balance for trading: {balance} < {min_trade_amount}")
                return False
                
            # Implement your trading strategy logic here
            # For now, we'll just log the token details
            logger.info(f"Token details: {token}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error executing strategy for token {token.get('symbol', 'Unknown')}: {str(e)}")
            return False 

    async def close_all_positions(self):
        """Fetches all open positions from the database and enqueues SELL requests for them."""
        logger.warning("Initiating closing of all open positions...")
        
        if not self.db or not self.trade_queue:
            logger.error("Database or TradeQueue not available. Cannot close positions.")
            return

        try:
            open_positions = await self.db.fetch_active_positions()
            
            if not open_positions:
                logger.info("No open positions found to close.")
                return

            logger.info(f"Found {len(open_positions)} open positions to close.")
            closed_count = 0
            enqueue_tasks = []

            for position in open_positions:
                token_mint = position.get('token_mint')
                position_amount = position.get('amount')
                position_id = position.get('id')

                if not token_mint or position_amount is None or position_amount <= 0:
                    logger.warning(f"Skipping position ID {position_id} due to missing mint ({token_mint}) or invalid amount ({position_amount}).")
                    continue
                
                logger.info(f"Creating SELL request for position ID {position_id} (Token: {token_mint}, Amount: {position_amount})")
                
                trade_request = TradeRequest(
                    token_address=token_mint,
                    amount=position_amount,
                    is_buy=False,
                    priority=TradePriority.CRITICAL,
                    strategy_id="shutdown_close",
                    timestamp=datetime.now(timezone.utc),
                    metadata={
                        'reason': 'Graceful shutdown requested',
                        'position_id': position_id
                    }
                )
                
                enqueue_tasks.append(self.trade_queue.add_trade(trade_request))

            results = await asyncio.gather(*enqueue_tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                position = open_positions[i]
                if isinstance(result, Exception):
                    logger.error(f"Failed to enqueue closing trade for position ID {position.get('id')}: {result}")
                elif result:
                    closed_count += 1
                    logger.info(f"Successfully enqueued closing trade for position ID {position.get('id')}")
                else:
                    logger.warning(f"Failed to enqueue closing trade for position ID {position.get('id')} (add_trade returned False)")

            logger.warning(f"Finished enqueueing closing trades. Successfully enqueued {closed_count}/{len(open_positions)} positions.")

        except Exception as e:
            logger.error(f"An error occurred during the close_all_positions process: {e}", exc_info=True) 