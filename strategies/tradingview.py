import logging
from datetime import datetime
from data.models import db, TradingViewAlert, Strategy, Trade, Coin, Token
from typing import Optional, Dict, Any
from .paper_trading import PaperTrading
from config.settings import Settings
from flask_sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

db = SQLAlchemy()

class TradingViewManager:
    def __init__(self):
        """Initialize the TradingView manager."""
        self.logger = logging.getLogger(__name__)
        self.settings = Settings()
        self.paper_trading = PaperTrading()
        self.logger.info("Initializing TradingView manager")

    def process_webhook(self, user_id: int, data: Dict[str, Any]) -> bool:
        """
        Process a webhook from TradingView.
        
        Args:
            user_id: The ID of the user who owns the alert
            data: The webhook data from TradingView
            
        Returns:
            bool: True if the webhook was processed successfully
        """
        ticker = data.get('ticker', data.get('symbol'))
        action = data.get('action')
        price = data.get('price')
        mint = data.get('mint')

        if not all([action, ticker, price]):
            self.logger.warning(f"Incomplete webhook data received: {data}")
            return False

        try:
            price = float(price)
        except (ValueError, TypeError):
            self.logger.error(f"Invalid price format received for ticker {ticker}: {price}")
            return False

        base_token_symbol = ticker.split('/')[0] if '/' in ticker else ticker

        self.logger.info(f"Processing webhook for User {user_id}: Action={action}, Ticker={ticker}, Price={price}")

        token_obj = None
        log_prefix = f"{base_token_symbol} (Mint N/A)"

        try:
            if mint:
                token_obj = db.session.query(Token).filter(Token.user_id == user_id, Token.mint == mint).first()
                if token_obj:
                    log_prefix = f"{token_obj.token} ({token_obj.mint})"
                else:
                    self.logger.warning(f"Token with mint {mint} not found for user {user_id}. Trying symbol lookup.")
                    tokens_found = db.session.query(Token).filter(Token.user_id == user_id, Token.token == base_token_symbol).all()
                    if len(tokens_found) == 1:
                        token_obj = tokens_found[0]
                        log_prefix = f"{token_obj.token} ({token_obj.mint})"
                    elif len(tokens_found) > 1:
                        self.logger.warning(f"Multiple tokens found for symbol {base_token_symbol} for user {user_id}. Cannot uniquely identify.")
                    else:
                        self.logger.warning(f"Token with symbol {base_token_symbol} also not found for user {user_id}.")

            else:
                tokens_found = db.session.query(Token).filter(Token.user_id == user_id, Token.token == base_token_symbol).all()
                if len(tokens_found) == 1:
                    token_obj = tokens_found[0]
                    log_prefix = f"{token_obj.token} ({token_obj.mint})"
                elif len(tokens_found) > 1:
                    self.logger.warning(f"Multiple tokens found for symbol {base_token_symbol} for user {user_id}. Cannot uniquely identify.")
                else:
                    self.logger.warning(f"Token with symbol {base_token_symbol} not found for user {user_id}.")
        except Exception as e:
            self.logger.error(f"Database error looking up token for {base_token_symbol} / {mint}: {e}")

        try:
            if action.lower() == 'buy':
                self.logger.info(f"{log_prefix}: Executing simulated BUY order at {price}")
                success = True
            elif action.lower() == 'sell':
                self.logger.info(f"{log_prefix}: Executing simulated SELL order at {price}")
                success = True
            else:
                self.logger.warning(f"{log_prefix}: Unknown action '{action}' received in webhook.")
                success = False

            if not success:
                self.logger.error(f"{log_prefix}: Failed to execute {action} action.")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error executing action for {log_prefix} from webhook: {e}", exc_info=True)
            db.session.rollback()
            return False

    def get_positions(self, user_id: int) -> Dict[str, Dict[str, Any]]:
        """
        Get all paper trading positions for a user.
        
        Args:
            user_id: The user ID
            
        Returns:
            Dictionary of positions by token symbol (MINT). Example: {"SOL (So111...)": {...position_details}}
        """
        positions = {}
        try:
            user_tokens = db.session.query(Token).filter(Token.user_id == user_id).all()

            for token_obj in user_tokens:
                position_details = self.paper_trading.get_position(user_id, token_obj.id)

                if position_details and position_details.get('amount', 0) != 0:
                    position_key = f"{token_obj.token} ({token_obj.mint})"
                    positions[position_key] = position_details
                    self.logger.debug(f"Retrieved position for user {user_id}: {position_key} - Amount: {position_details.get('amount')}")

            self.logger.info(f"Fetched {len(positions)} active positions for user {user_id}.")
            return positions

        except Exception as e:
            self.logger.error(f"Error getting positions for user {user_id}: {e}", exc_info=True)
            return {}

    def close(self):
        """Clean up resources."""
        self.logger.info("Closing TradingView manager")
        if self.paper_trading:
            self.paper_trading.close() 