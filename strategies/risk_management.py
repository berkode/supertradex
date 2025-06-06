import os
import logging
from config import Settings
from execution.transaction_tracker import TransactionTracker
from execution.order_manager import OrderManager
import asyncio
import collections
from typing import Dict, Optional, TYPE_CHECKING, Any
from datetime import datetime, timedelta, timezone
from utils.logger import get_logger
from execution.trade_queue import TradePriority, TradeRequest
from strategies.alert_system import AlertSystem

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RiskManagement")

# Use TYPE_CHECKING for imports to avoid circular dependencies
if TYPE_CHECKING:
    from data.token_database import TokenDatabase
    from data.market_data import MarketData
    from execution.trade_queue import TradeQueue
    # Optional API clients
    # from filters.rugcheck_api import RugcheckAPI
    # from filters.solsniffer_api import SolsnifferAPI

class RiskManagement:
    def __init__(self, 
                 settings: Settings,
                 thresholds: Any,
                 alert_system: "AlertSystem",
                 db: "TokenDatabase",
                 transaction_tracker: TransactionTracker,
                 order_manager: OrderManager
                 ):
        self.settings = settings
        self.thresholds = thresholds
        self.alert_system = alert_system
        self.db = db
        self.transaction_tracker = transaction_tracker
        self.order_manager = order_manager

    def calculate_stop_loss(self, entry_price: float, position_size: float, strategy: str) -> float:
        """
        Calculate the stop-loss price dynamically based on strategy and max position loss.
        """
        # Calculate risk percentage from settings and strategy deviations
        risk_percentage = self.settings.RISK_PER_TRADE * 100
        strategy_deviation = self.settings.STRATEGY_DEVIATIONS.get(strategy, {}).get("risk_percentage_deviation", 0)
        effective_risk_percentage = risk_percentage + strategy_deviation

        # Calculate the maximum allowable loss per position
        max_position_loss = self.settings.__getattribute__(f"{strategy}_MAX_POSITION_LOSS")
        max_loss_price_delta = max_position_loss / position_size

        # Stop-loss is the tighter constraint between risk percentage and max position loss
        calculated_stop_loss = entry_price * (1 - effective_risk_percentage / 100)
        stop_loss = max(entry_price - max_loss_price_delta, calculated_stop_loss)

        logger.debug(
            f"{strategy}: Calculated stop-loss {stop_loss} for entry price {entry_price}, "
            f"risk percentage {effective_risk_percentage}, and max position loss {max_position_loss}."
        )
        return round(stop_loss, 2)

    def calculate_take_profit(self, entry_price: float, strategy: str) -> float:
        """
        Calculate the take-profit price dynamically based on the strategy and settings.
        """
        reward_ratio = self.settings.__getattribute__(f"{strategy}_POSITION_GAIN_TARGET") * 100
        strategy_deviation = self.settings.STRATEGY_DEVIATIONS.get(strategy, {}).get("reward_ratio_deviation", 0)
        effective_reward_ratio = reward_ratio + strategy_deviation
        take_profit = entry_price * (1 + effective_reward_ratio / 100)

        logger.debug(
            f"{strategy}: Calculated take-profit {take_profit} for entry price {entry_price} with "
            f"reward ratio {effective_reward_ratio}."
        )
        return round(take_profit, 2)

    def enforce_exposure_limit(self, symbol: str, current_exposure: float, strategy: str):
        """
        Enforce exposure limits for a symbol dynamically based on strategy and settings.
        """
        max_exposure = self.settings.DAILY_MAX_RISK * self.settings.TRADE_SIZE
        strategy_deviation = self.settings.STRATEGY_DEVIATIONS.get(strategy, {}).get("exposure_limit_deviation", 0)
        effective_max_exposure = max_exposure + strategy_deviation

        if current_exposure > effective_max_exposure:
            logger.warning(
                f"{symbol} ({strategy}): Exposure {current_exposure} exceeds allowed {effective_max_exposure}. Reducing position."
            )
            exposure_to_reduce = current_exposure - effective_max_exposure
            trade_details = {"symbol": symbol, "quantity": -exposure_to_reduce, "action": "reduce_exposure"}
            try:
                self.transaction_tracker.execute_trade(trade_details)
                logger.info(f"Reduced exposure for {symbol} ({strategy}). Trade details: {trade_details}.")
            except Exception as e:
                logger.error(f"{symbol} ({strategy}): Failed to reduce exposure: {e}")

    def monitor_trades(self, positions: list):
        """
        Monitor active trades for stop-loss, take-profit, and trailing stop adjustments.
        """
        logger.info("Monitoring trades for risk management.")

        for position in positions:
            symbol = position["symbol"]
            strategy = position.get("strategy", "default")
            entry_price = position["entry_price"]
            current_price = position["current_price"]
            position_size = position["size"]

            # Calculate dynamic risk parameters
            stop_loss = position.get("stop_loss") or self.calculate_stop_loss(entry_price, position_size, strategy)
            take_profit = position.get("take_profit") or self.calculate_take_profit(entry_price, strategy)

            # Check stop-loss and take-profit conditions
            if current_price <= stop_loss:
                logger.warning(f"{symbol} ({strategy}): Current price {current_price} hit stop-loss {stop_loss}. Closing position.")
                trade_details = {"symbol": symbol, "quantity": -position_size, "price": current_price}
                self.transaction_tracker.execute_trade(trade_details)
                continue

            if current_price >= take_profit:
                logger.info(f"{symbol} ({strategy}): Current price {current_price} reached take-profit {take_profit}. Closing position.")
                trade_details = {"symbol": symbol, "quantity": -position_size, "price": current_price}
                self.transaction_tracker.execute_trade(trade_details)
                continue

        logger.info("Trade monitoring completed.")

    def manage_risk(self, positions: list, total_account_balance: float):
        """
        Comprehensive risk management including exposure limits and trade monitoring.
        """
        logger.info("Starting comprehensive risk management.")

        for position in positions:
            symbol = position["symbol"]
            strategy = position.get("strategy", "default")
            position_value = position["current_price"] * position["size"]

            # Enforce exposure limits
            self.enforce_exposure_limit(symbol, position_value, strategy)

        # Monitor active trades
        self.monitor_trades(positions)
        logger.info("Risk management process completed.")

class TokenRiskMonitor:
    """
    Monitors tokens for real-time risks like sharp price drops or liquidity drains.
    """
    def __init__(self,
                 settings: 'Settings',
                 db: 'TokenDatabase',
                 market_data: 'MarketData',
                 trade_queue: 'TradeQueue',
                 order_manager: 'OrderManager',
                 # Optional API Clients
                 # rugcheck_api: Optional['RugcheckAPI'] = None,
                 # solsniffer_api: Optional['SolsnifferAPI'] = None
                 ):
        """Initialize the TokenRiskMonitor."""
        self.settings = settings
        self.db = db
        self.market_data = market_data
        self.trade_queue = trade_queue
        self.order_manager = order_manager
        # self.rugcheck_api = rugcheck_api
        # self.solsniffer_api = solsniffer_api
        self._initialized = False
        self.logger = get_logger(__name__)

        # --- State for Price Drop Detection ---
        # Stores tuples of (timestamp, price)
        self.recent_prices: Dict[str, collections.deque] = {}
        self.price_drop_window_seconds = getattr(settings, 'RISK_PRICE_DROP_WINDOW_SECONDS', 300) # Default 5 mins
        self.price_drop_threshold_pct = getattr(settings, 'RISK_PRICE_DROP_PCT', 0.20) # Default 20% drop
        self.logger.info(f"Price drop detection window: {self.price_drop_window_seconds}s, Threshold: {self.price_drop_threshold_pct*100}%")

        # --- State for Periodic Checks ---
        self.liquidity_threshold_usd = getattr(settings, 'CRITICAL_LIQUIDITY_THRESHOLD_USD', 1000) # Default $1k
        self.risk_check_interval_seconds = getattr(settings, 'RISK_CHECK_INTERVAL_SECONDS', 60) # Default 1 min

        # --- Internal Tracking ---
        # Keep track of tokens for which an exit has already been triggered by this monitor
        # to avoid redundant triggers.
        self._exit_triggered: Dict[str, bool] = {}

    async def initialize(self):
        """Subscribe to necessary events."""
        if not all([self.settings, self.db, self.market_data, self.trade_queue, self.order_manager]):
            self.logger.error("TokenRiskMonitor missing required components during initialization.")
            return False

        self.market_data.subscribe("realtime_price_update", self.handle_realtime_price_update)
        # Consider subscribing to blockchain events later if needed for more complex analysis
        # self.market_data.subscribe("blockchain_event", self.handle_blockchain_event)
        self._initialized = True
        self.logger.info("TokenRiskMonitor initialized and subscribed to price updates.")
        return True

    async def handle_realtime_price_update(self, event_data: Dict):
        """Handle incoming price updates to check for sharp drops."""
        if not self._initialized: return

        mint = event_data.get('mint')
        price = event_data.get('price')
        timestamp_ms = event_data.get('timestamp') # Assuming timestamp is in milliseconds

        if not mint or price is None or timestamp_ms is None:
            return # Ignore incomplete events

        # Ignore if we don't have an active position for this token
        if not self.order_manager.has_position(mint):
            # Clean up price history if we no longer hold the position
            if mint in self.recent_prices:
                del self.recent_prices[mint]
            return

        # Ignore if an exit has already been triggered for this token
        if self._exit_triggered.get(mint):
            return

        try:
            current_price = float(price)
            if current_price <= 0: return # Ignore invalid prices
            current_timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        except (ValueError, TypeError):
            self.logger.warning(f"Invalid price/timestamp in event for {mint}: {event_data}")
            return

        # --- Update Price History for Drop Detection ---
        if mint not in self.recent_prices:
            self.recent_prices[mint] = collections.deque()
        self.recent_prices[mint].append((current_timestamp, current_price))

        # --- Prune Old Prices ---
        cutoff_time = current_timestamp - timedelta(seconds=self.price_drop_window_seconds)
        while self.recent_prices[mint] and self.recent_prices[mint][0][0] < cutoff_time:
            self.recent_prices[mint].popleft()

        # --- Check for Price Drop ---
        if len(self.recent_prices[mint]) > 1: # Need at least two points to compare
            start_price = self.recent_prices[mint][0][1] # Price at the start of the window (or earliest available)
            price_drop_pct = (start_price - current_price) / start_price if start_price > 0 else 0

            if price_drop_pct >= self.price_drop_threshold_pct:
                reason = f"Price drop >= {self.price_drop_threshold_pct*100}% detected in {self.price_drop_window_seconds}s ({start_price:.6f} -> {current_price:.6f})"
                self.logger.warning(f"RISK DETECTED ({mint}): {reason}")
                await self._trigger_urgent_exit(mint, reason)


    async def run_periodic_checks(self):
        """
        Perform periodic checks for risks like low liquidity or degraded scores.
        To be called by TradeScheduler.
        """
        if not self._initialized: return
        self.logger.info("Running periodic risk checks...")

        active_positions = self.order_manager.get_all_positions()
        if not active_positions:
            self.logger.info("No active positions to perform periodic risk checks on.")
            return

        for mint, position_data in list(active_positions.items()): # Iterate over copy
            # Ignore if an exit has already been triggered
            if self._exit_triggered.get(mint):
                continue

            try:
                # --- Check Liquidity ---
                # Fetch liquidity data (implementation depends on MarketData or DB)
                # Example: Assuming MarketData provides a method
                liquidity_data = await self.market_data.get_liquidity(mint) # Needs implementation in MarketData
                current_liquidity_usd = liquidity_data.get('usd') if liquidity_data else None

                if current_liquidity_usd is not None:
                    if current_liquidity_usd < self.liquidity_threshold_usd:
                        reason = f"Critical low liquidity detected: ${current_liquidity_usd:.2f} < Threshold ${self.liquidity_threshold_usd:.2f}"
                        self.logger.warning(f"RISK DETECTED ({mint}): {reason}")
                        await self._trigger_urgent_exit(mint, reason)
                        continue # Move to next token once exit is triggered
                else:
                    self.logger.warning(f"Could not fetch liquidity data for periodic check on {mint}")

                # --- Optional: Check Risk Scores (Requires API clients) ---
                # if self.rugcheck_api:
                #     # Fetch latest score, compare with initial score (stored in position_data or DB?)
                #     pass
                # if self.solsniffer_api:
                #     # Fetch latest score, compare
                #     pass

            except Exception as e:
                self.logger.error(f"Error during periodic risk check for {mint}: {e}", exc_info=True)

        self.logger.info("Finished periodic risk checks.")


    async def _trigger_urgent_exit(self, mint: str, reason: str):
        """Enqueues an urgent SELL trade for the given mint."""
        if self._exit_triggered.get(mint):
            self.logger.info(f"Urgent exit already triggered for {mint}. Ignoring duplicate request.")
            return

        self.logger.warning(f"Attempting to trigger URGENT EXIT for {mint} due to: {reason}")

        position_data = self.order_manager.get_position(mint)
        if not position_data:
            self.logger.error(f"Cannot trigger urgent exit for {mint}: Position data not found.")
            return

        try:
            position_size = float(position_data.get('size'))
            if position_size <= 0:
                self.logger.error(f"Cannot trigger urgent exit for {mint}: Invalid position size ({position_size}).")
                return
        except (TypeError, ValueError) as e:
            self.logger.error(f"Cannot trigger urgent exit for {mint}: Invalid position size format ({position_data.get('size')}). Error: {e}")
            return

        # Prepare Trade Request
        # Assuming OrderManager needs token quantity for sell requests
        trade_request = TradeRequest(
            token_address=mint,
            amount=position_size, # Use the actual token amount
            is_buy=False,
            priority=TradePriority.CRITICAL_SELL, # Highest priority
            strategy_id="risk_monitor",
            timestamp=datetime.now(timezone.utc),
            metadata={
                'exit_reason': 'risk_monitor_trigger',
                'risk_details': reason,
                'entry_tx_hash': position_data.get('entry_tx_hash'),
                'position_id': position_data.get('id') # Assuming position has an ID
            }
            # callback=? # Optional: Define a callback if needed after trade execution attempt
        )

        # Enqueue the trade
        enqueue_success = await self.trade_queue.enqueue_trade(trade_request)

        if enqueue_success:
            self.logger.warning(f"Successfully enqueued URGENT SELL trade for {mint}.")
            self._exit_triggered[mint] = True # Mark as triggered

            # Optional: Blacklist the token
            try:
                await self.db.add_to_blacklist(mint, reason=f"Risk Monitor: {reason}")
                self.logger.info(f"Blacklisted token {mint}.")
            except Exception as db_err:
                self.logger.error(f"Failed to blacklist token {mint}: {db_err}")

            # Optional: Clean up price history for this token
            if mint in self.recent_prices:
                del self.recent_prices[mint]
        else:
            self.logger.error(f"Failed to enqueue URGENT SELL trade for {mint}.")
            # Consider retry logic or alternative alerting here if enqueue fails critically

    async def close(self):
        """Clean up resources or unsubscribe from events if necessary."""
        self.logger.info("Closing TokenRiskMonitor.")
        # Unsubscribe if MarketData requires it
        # self.market_data.unsubscribe("realtime_price_update", self.handle_realtime_price_update)
        self.recent_prices.clear()
        self._exit_triggered.clear()

