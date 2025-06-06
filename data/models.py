from datetime import datetime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
import logging
import pandas as pd
from typing import Optional, Dict, Any
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs

Base = declarative_base()

logger = logging.getLogger(__name__)

class Strategy(Base):
    __tablename__ = 'strategy'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    parameters = Column(JSON)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    trades = relationship('Trade', foreign_keys='Trade.strategy_id', backref='strategy', lazy=True)
    alerts = relationship('Alert', backref='strategy', lazy=True)

class Token(AsyncAttrs, Base):
    __tablename__ = 'tokens'
    id = Column(Integer, primary_key=True)
    mint = Column(String(64), nullable=True, unique=True)
    pair_address = Column(String(64), nullable=True)
    symbol = Column(String(50), nullable=True)
    name = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=True)
    liquidity = Column(Float, nullable=True)
    volume_24h = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)
    age_minutes = Column(Float, nullable=True)
    category = Column(String(20), nullable=True)
    twitter = Column(String(100), nullable=True)
    website = Column(String(200), nullable=True)
    telegram = Column(String(100), nullable=True)
    discord = Column(String(100), nullable=True)
    api_data = Column(JSON, nullable=True)
    scan_results = Column(JSON, nullable=True)
    is_valid = Column(Boolean, default=True)
    overall_filter_passed = Column(Boolean, nullable=True)
    monitoring_status = Column(String(20), nullable=True, index=True, default='pending') # e.g., pending, active, stopped
    last_updated = Column(DateTime, default=datetime.utcnow)
    last_filter_update = Column(DateTime, nullable=True)
    last_scanned_at = Column(DateTime, nullable=True)
    dex_id = Column(String(50), nullable=True)

    # RugCheck.xyz specific fields
    rugcheck_score = Column(Float, nullable=True)
    rugcheck_risk = Column(String(50), nullable=True) # e.g., LOW, MEDIUM, HIGH, CRITICAL
    rugcheck_raw_json = Column(JSON, nullable=True) # Stores the full JSON response from RugCheck
    rugcheck_last_scan = Column(DateTime, nullable=True)
    is_rugpull = Column(Boolean, nullable=True) # True if RugCheck identifies it as a likely rugpull

    # Volume fields - ensuring all expected fields are present
    # total_volume = Column(Float, nullable=True) # Removing this as volume_24h will be used

    trades = relationship('Trade', backref='token_info', lazy=True)
    alerts = relationship('Alert', backref='token_info', lazy=True)

    def __repr__(self):
        return f'<Token {self.symbol} ({self.mint})>'

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('tokens.id'), nullable=False)
    strategy_id = Column(Integer, ForeignKey('strategy.id'), nullable=True)
    coin_id = Column(Integer, ForeignKey('coins.id'), nullable=True)
    action = Column(String(10), nullable=False)
    type = Column(String(10), nullable=True)  # 'BUY' or 'SELL' type
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    total = Column(Float, nullable=True)  # total value of the trade
    status = Column(String(20), nullable=True, default='PENDING')  # PENDING, COMPLETED, FAILED, etc.
    notes = Column(Text, nullable=True)  # Additional notes about the trade
    timestamp = Column(DateTime, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = 'alerts'
    id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('tokens.id'), nullable=True)
    strategy_id = Column(Integer, ForeignKey('strategy.id'), nullable=True)
    message = Column(Text, nullable=False)
    level = Column(String(20), nullable=False)  # info, warning, error, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    last_triggered = Column(DateTime, nullable=True)
    coin_id = Column(Integer, ForeignKey('coins.id'), nullable=True)

class MemeTokenStrategy:
    """
    Handles trading logic for meme tokens based on predefined criteria.
    """
    def __init__(self, initial_capital: float, token_data: dict, settings: dict):
        """Initialize meme token trading strategy."""
        self.capital = initial_capital
        self.token = token_data
        self.settings = settings
        self.trades = []
        self.position = 0
        self.entry_price = 0
        self.mint = token_data.get('mint', 'UNKNOWN_MINT')
        self.symbol = token_data.get('symbol', 'UNKNOWN_SYMBOL')
        logger.info(f"Initialized MemeTokenStrategy for {self.symbol} ({self.mint}) with capital: ${initial_capital:.2f}")

    def _log_trade(self, action: str, price: float, quantity: float, reason: str):
        """Logs trade details."""
        trade_info = {
            "token_mint": self.mint,
            "token_symbol": self.symbol,
            "action": action,
            "price": price,
            "quantity": quantity,
            "capital_impact": -quantity * price if action == "BUY" else quantity * price,
            "timestamp": datetime.utcnow(),
            "reason": reason
        }
        self.trades.append(trade_info)
        logger.info(f"Trade executed for {self.symbol} ({self.mint}): {action} {quantity:.4f} @ ${price:.6f}. Reason: {reason}")

    def decide_action(self, current_price: float, market_data: dict) -> Optional[str]:
        """Determine BUY, SELL, or HOLD based on token metrics and strategy rules."""

        if current_price <= 0:
            logger.warning(f"{self.symbol} ({self.mint}): Invalid current price ({current_price}). Holding.")
            return "HOLD"

        volume_threshold = self.settings.get("MIN_VOLUME_ENTRY", self.settings.get("MIN_VOLUME_24H", 500))
        price_change_threshold = self.settings.get("MIN_PRICE_CHANGE_ENTRY", 0.05)

        if self.position == 0:
            volume_24h = market_data.get("volume_24h", 0)
            price_change_24h = market_data.get("price_change_24h", 0)

            if volume_24h > volume_threshold and price_change_24h > price_change_threshold:
                logger.info(f"{self.symbol} ({self.mint}): Entry condition met (Volume > {volume_threshold}, Price Change > {price_change_threshold}%).")
                return "BUY"

        elif self.position > 0:
            stop_loss_price = self.entry_price * (1 - self.settings.get("STOP_LOSS_PCT", 0.10))
            take_profit_price = self.entry_price * (1 + self.settings.get("TAKE_PROFIT_PCT", 0.20))

            if current_price <= stop_loss_price:
                logger.info(f"{self.symbol} ({self.mint}): Stop loss triggered at ${current_price:.6f} (Entry: ${self.entry_price:.6f}).")
                return "SELL"
            elif current_price >= take_profit_price:
                logger.info(f"{self.symbol} ({self.mint}): Take profit triggered at ${current_price:.6f} (Entry: ${self.entry_price:.6f}).")
                return "SELL"

            volume_exit_threshold_ratio = self.settings.get("VOLUME_EXIT_RATIO", 0.5)
            if market_data.get("volume_24h", 0) < volume_threshold * volume_exit_threshold_ratio:
                logger.info(f"{self.symbol} ({self.mint}): Exit condition met (Volume dropped significantly).")
                return "SELL"

        return "HOLD"

    def execute_trade(self, action: str, price: float, reason: str = "Strategy decision"):
        """Simulates executing a trade."""
        if action == "BUY":
            if self.capital > 0:
                quantity = (self.capital * self.settings.get("POSITION_SIZE_PCT", 0.95)) / price
                if quantity * price > self.capital:
                    quantity = self.capital / price

                self.position += quantity
                self.capital -= quantity * price
                self.entry_price = price
                self._log_trade("BUY", price, quantity, reason)
                logger.info(f"{self.symbol} ({self.mint}): Bought {quantity:.4f}. New capital: ${self.capital:.2f}, Position: {self.position:.4f}")
            else:
                logger.warning(f"{self.symbol} ({self.mint}): Cannot BUY, insufficient capital.")

        elif action == "SELL":
            if self.position > 0:
                sell_quantity = self.position
                self.capital += sell_quantity * price
                self._log_trade("SELL", price, sell_quantity, reason)
                logger.info(f"{self.symbol} ({self.mint}): Sold {sell_quantity:.4f}. New capital: ${self.capital:.2f}, Position: 0")
                self.position = 0
                self.entry_price = 0
            else:
                logger.warning(f"{self.symbol} ({self.mint}): Cannot SELL, no position held.")

    def run_simulation(self, historical_data):
        """Runs the trading simulation over historical data."""
        logger.info(f"Running simulation for {self.symbol} ({self.mint}) over {len(historical_data)} data points.")
        for index, data_point in historical_data.iterrows():
            current_price = data_point['close']
            market_data = {
                "volume_24h": data_point.get("volume", 0),
                "price_change_24h": data_point.get("price_change_pct", 0),
            }

            action = self.decide_action(current_price, market_data)
            if action in ["BUY", "SELL"]:
                self.execute_trade(action, current_price)

        final_value = self.capital + self.position * historical_data.iloc[-1]['close']
        logger.info(f"Simulation complete for {self.symbol} ({self.mint}). Final portfolio value: ${final_value:.2f}")
        return final_value, self.trades

class Coin(Base):
    """Model for storing coin investor strategy data."""
    __tablename__ = 'coins'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), unique=True, nullable=False)
    pair = Column(String(12))
    timeframe = Column(String(3), default='4h')
    fiat_limit = Column(Integer, default=200)
    close_price = Column(Float)
    uptrend_previous = Column(Boolean, default=True)
    uptrend_last = Column(Boolean, default=True)
    buy_position = Column(Boolean, default=True)
    sell_position = Column(Boolean, default=True)
    trend_change = Column(Boolean, default=False)
    strategy_running = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Coin {self.symbol}>'

class Position(Base):
    __tablename__ = 'positions'
    id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('tokens.id'), nullable=False)
    amount = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default='OPEN') # e.g., OPEN, CLOSED

    token = relationship('Token') # Add relationship for easier access if needed

    def __repr__(self):
        return f'<Position {self.id} TokenID: {self.token_id} Amount: {self.amount}>'

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trades.id'), nullable=False)
    token_id = Column(Integer, ForeignKey('tokens.id'), nullable=False)
    type = Column(String(10), nullable=False)  # 'BUY' or 'SELL'
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    total = Column(Float, nullable=True)  # total value of the order
    status = Column(String(20), nullable=True, default='PENDING')  # PENDING, COMPLETED, FAILED, etc.
    notes = Column(Text, nullable=True)  # Additional notes about the order
    timestamp = Column(DateTime, default=datetime.utcnow)

    token = relationship('Token') # Add relationship
    trade = relationship('Trade') # Add relationship

    def __repr__(self):
        return f'<Order {self.id} TradeID: {self.trade_id} TokenID: {self.token_id} Status: {self.status}>'

# --- Paper Trading Persistence Models ---

class PaperPosition(AsyncAttrs, Base):
    __tablename__ = 'paper_positions'
    # Using mint as primary key for simplicity, assuming one paper position per token globally for now.
    # If multi-user paper trading is added later, a composite key or user_id FK would be needed.
    mint = Column(String(64), primary_key=True)
    quantity = Column(Float, nullable=False, default=0.0)
    # total_cost_usd stores the cumulative USD cost of acquiring the current quantity.
    # Average price can be derived: total_cost_usd / quantity.
    total_cost_usd = Column(Float, nullable=False, default=0.0) 
    average_price_usd = Column(Float, nullable=False, default=0.0) # Store calculated average for convenience
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<PaperPosition mint={self.mint} quantity={self.quantity} avg_price_usd={self.average_price_usd:.4f}>"

class PaperWalletSummary(AsyncAttrs, Base):
    __tablename__ = 'paper_wallet_summary'
    key = Column(String(50), primary_key=True) # e.g., 'paper_sol_balance'
    value_float = Column(Float, nullable=True)
    value_str = Column(String, nullable=True)
    value_json = Column(JSON, nullable=True) # For more complex summary data if needed
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<PaperWalletSummary key={self.key} value_float={self.value_float} value_str={self.value_str}>"

def main():
    # ... (load settings, data etc.) ...

    example_token = {
        "mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "symbol": "RAY",
    }

    initial_capital = 10000
    strategy_settings = {
        "MIN_VOLUME_ENTRY": 500,  # Use env variable value
        "MIN_PRICE_CHANGE_ENTRY": 0.03,
        "STOP_LOSS_PCT": 0.08,
        "TAKE_PROFIT_PCT": 0.15,
        "POSITION_SIZE_PCT": 0.95,
        "VOLUME_EXIT_RATIO": 0.4
    }

    strategy = MemeTokenStrategy(
        initial_capital=initial_capital,
        token_data=example_token,
        settings=strategy_settings
    )

    historical_data = pd.DataFrame({
        'timestamp': pd.to_datetime(['2023-01-01 10:00', '2023-01-01 11:00', '2023-01-01 12:00']),
        'close': [1.0, 1.1, 1.05],
        'volume': [60000, 70000, 55000],
        'price_change_pct': [0.0, 0.1, -0.045]
    }).set_index('timestamp')

    if not historical_data.empty:
        final_value, trades = strategy.run_simulation(historical_data)
        print(f"\n--- Strategy Results for {example_token['symbol']} ({example_token['mint']}) ---")
        print(f"Initial Capital: ${initial_capital:.2f}")
        print(f"Final Portfolio Value: ${final_value:.2f}")
        print(f"Total Trades: {len(trades)}")
        print("\nTrades Log:")
        for trade in trades:
            print(f"  - {trade['timestamp']} {trade['action']} {trade['quantity']:.4f} {trade['token_symbol']} @ ${trade['price']:.6f}")

        print("\nMeme Token Metrics:")
    else:
        print(f"Could not load historical data for {example_token['symbol']} ({example_token['mint']}).")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    main() 