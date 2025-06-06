import logging
from datetime import datetime
from .models import db, TradingViewAlert, Strategy, Trade, Coin
from typing import Optional, Dict, Any
from .paper_trading import PaperTrading
from config.settings import Settings

logger = logging.getLogger(__name__)

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
        try:
            # Find the matching alert
            alert = TradingViewAlert.query.filter_by(
                user_id=user_id,
                symbol=data.get('symbol'),
                condition=data.get('condition')
            ).first()
            
            if not alert or not alert.is_active:
                self.logger.warning(f"No active alert found for user {user_id}")
                return False
                
            # Get the associated strategy
            strategy = Strategy.query.get(alert.strategy_id)
            if not strategy or not strategy.is_active:
                self.logger.warning(f"No active strategy found for alert {alert.id}")
                return False
                
            # Get the coin
            coin = Coin.query.filter_by(
                user_id=user_id,
                coin=data.get('symbol').split('/')[0],
                pair=data.get('symbol').split('/')[1]
            ).first()
            
            if not coin:
                self.logger.warning(f"No coin found for symbol {data.get('symbol')}")
                return False
                
            # Execute the trade using paper trading
            trade = self.paper_trading.process_tradingview_alert(data, strategy, coin)
            if not trade:
                self.logger.error("Failed to execute paper trade")
                return False
                
            # Update alert last triggered time
            alert.last_triggered = datetime.utcnow()
            db.session.commit()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing TradingView webhook: {str(e)}")
            return False

    def get_positions(self, user_id: int) -> Dict[str, Dict[str, Any]]:
        """
        Get all paper trading positions for a user.
        
        Args:
            user_id: The user ID
            
        Returns:
            Dictionary of positions by coin symbol
        """
        try:
            positions = {}
            coins = Coin.query.filter_by(user_id=user_id).all()
            
            for coin in coins:
                position = self.paper_trading.get_position(user_id, coin.id)
                if position['amount'] != 0:  # Only include active positions
                    symbol = f"{coin.coin}/{coin.pair}"
                    positions[symbol] = position
                    
            return positions
            
        except Exception as e:
            self.logger.error(f"Error getting positions: {str(e)}")
            return {}

    def close(self):
        """Clean up resources."""
        self.logger.info("Closing TradingView manager")
        if self.paper_trading:
            self.paper_trading.close() 