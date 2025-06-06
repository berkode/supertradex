"""
Entry and exit strategy implementation for SupertradeX.
"""
import logging
import asyncio
from typing import Optional, Dict, List, TYPE_CHECKING
from datetime import datetime, timezone, timedelta
import collections
import pandas as pd

from data.indicators import Indicators as IndicatorCalculator
from filters.whitelist import Whitelist
from filters.blacklist import Blacklist
from config.thresholds import Thresholds
from utils.logger import get_logger
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType
from config import Settings
from data.token_database import TokenDatabase
from data.market_data import MarketData
from wallet.wallet_manager import WalletManager
from execution.trade_queue import TradePriority

logger = get_logger("EntryExitStrategy")

# Define minimum periods for indicator calculations
MIN_RSI_PERIOD = 14
MIN_MACD_PERIOD = 26 # Slow period
MIN_BB_PERIOD = 20
MIN_INDICATOR_PERIOD = max(MIN_RSI_PERIOD, MIN_MACD_PERIOD, MIN_BB_PERIOD)

class EntryExitStrategy:
    def __init__(self, settings: Settings, db: 'TokenDatabase',
                 trade_queue: Optional['TradeQueue'],
                 market_data: 'MarketData',
                 whitelist: Whitelist = None,
                 blacklist: Blacklist = None,
                 thresholds: 'Thresholds' = None,
                 wallet_manager = None):
        """Initialize the EntryExitStrategy with required components."""
        self.logger = get_logger(__name__)
        self.settings = settings
        self.db = db
        self.trade_queue = trade_queue
        self.market_data = market_data
        self.whitelist = whitelist
        self.blacklist = blacklist
        if thresholds is None:
             self.logger.error("EntryExitStrategy initialized without a Thresholds instance! Defaulting logic might fail if thresholds are not properly handled by strategy methods.")
             self.thresholds = thresholds
        else:
             self.thresholds = thresholds
        self.wallet_manager = wallet_manager
        self.order_manager = None  # Initialize order_manager to None, will be set during initialize()
        self._initialized = False
        self.active_mint = None  # Initialize active_mint to None
        self.logger.info("Initialized active_mint to None.")

        # --- Internal State for Price History ---
        self.price_history: Dict[str, collections.deque] = {}
        self.max_history_len = getattr(settings, 'MAX_PRICE_HISTORY_LEN', 200)
        self.logger.info(f"Initialized price history deque with max length {self.max_history_len}")

        # --- Internal State for TSL High Water Mark --- #
        self.position_hwm: Dict[str, float] = {}
        self.logger.info("Initialized TSL High-Water Mark tracking dictionary.")

        # Initialize watchlists
        self.entry_watchlist = []
        self.exit_watchlist = []

        # --- Circuit Breaker --- #
        self.circuit_breaker = CircuitBreaker(
            breaker_type=CircuitBreakerType.COMPONENT,
            identifier="entry_exit_strategy",
            on_activate=self._on_circuit_breaker_activate,
            on_reset=self._on_circuit_breaker_reset
        )
        
        # Validate required components
        if not self.db:
            self.logger.error("TokenDatabase instance is required for EntryExitStrategy")
        if self.trade_queue is None:
            self.logger.info("EntryExitStrategy initialized without a TradeQueue. Assumes signals will be returned (signal generation mode).")
        if not self.market_data:
             self.logger.error("MarketData instance is required for EntryExitStrategy")
            
    async def initialize(self, order_manager: Optional['OrderManager'] = None,
                        transaction_tracker: Optional['TransactionTracker'] = None,
                        balance_checker: Optional['BalanceChecker'] = None,
                        trade_validator: Optional['TradeValidator'] = None) -> bool:
        """Initialize the strategy and validate all required components."""
        try:
            # Core components check (essential for any mode)
            if not all([self.settings, self.db, self.market_data]):
                self.logger.error("Missing required core components (Settings, DB, MarketData) for EES initialization.")
                return False

            self._initialized = True
            self.order_manager = order_manager
            self.transaction_tracker = transaction_tracker
            self.balance_checker = balance_checker
            self.trade_validator = trade_validator
            
            # Validate components required for direct trade execution (if trade_queue is present)
            if self.trade_queue:
                self.logger.info("EES Initializing in direct trading mode (trade_queue is present). Validating trade execution components.")
                required_trade_components = [
                    (self.order_manager, "OrderManager"),
                    (self.transaction_tracker, "TransactionTracker"),
                    (self.balance_checker, "BalanceChecker"),
                    (self.trade_validator, "TradeValidator")
                ]
                missing_trade_components = []
                for component, name in required_trade_components:
                    if not component:
                        self.logger.error(f"{name} instance is required for EES direct trading mode but not provided.")
                        missing_trade_components.append(name)
                if missing_trade_components:
                    self.logger.error(f"EES direct trading mode initialization failed due to missing components: {', '.join(missing_trade_components)}")
                    return False # Critical failure for this mode
                self.logger.info("All required components for direct trading mode are present.")
                
                # If in direct trading mode, EES might subscribe to MarketData itself.
                # However, if StrategyEvaluator is managing EES, SE should be the one subscribing and feeding data.
                # For now, let's assume if trade_queue is present, EES might manage its own subscription.
                # This logic needs to be very clear: who subscribes when?
                # Decision: If EES is initialized with a trade_queue, it subscribes itself.
                # Otherwise, it expects StrategyEvaluator to feed it data.
                if self.market_data:
                    self.market_data.subscribe("realtime_price_update", self.handle_realtime_price_update)
                    self.logger.info("EES (direct trading mode) subscribed to realtime_price_update events from MarketData.")
                else:
                    # This case should have been caught by the core component check earlier.
                    self.logger.error("MarketData not available during EES direct trading mode initialization, cannot subscribe.")
                    return False
            else:
                self.logger.info("EES Initializing in signal generation mode (trade_queue is None). MarketData subscription will be managed externally (e.g., by StrategyEvaluator).")
            
            self.logger.info("EntryExitStrategy initialized successfully.")
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing EntryExitStrategy: {str(e)}", exc_info=True)
            return False

    def _on_circuit_breaker_activate(self) -> None:
        """Callback when circuit breaker activates."""
        self.logger.error("Circuit breaker activated - trading operations suspended")
        # TODO: Add notification to admin/telegram

    def _on_circuit_breaker_reset(self) -> None:
        """Callback when circuit breaker resets."""
        self.logger.info("Circuit breaker reset - trading operations resumed")
        # TODO: Add notification to admin/telegram

    # --- OLD Signal Generation (Likely Obsolete/Refactored) ---
    # async def generate_signals(self, token: Dict, strategy: str) -> Optional[Dict]:
    # ... (Keep commented out or remove later if fully replaced by handle_realtime_price_update)

    # --- Basic Criteria Check (May still be useful within handler) ---
    def _check_basic_criteria(self, token_db_data) -> bool:
        """Check if token meets basic entry criteria based on Token model data."""
        try:
            # token_db_data is a Token model instance from the database
            mint = token_db_data.mint
            
            # Check overall filter pass (essential)
            if not token_db_data.overall_filter_passed:
                self.logger.debug(f"Token {mint} did not pass overall filters.")
                return False
                
            # Check volume
            if hasattr(self.settings, 'MIN_VOLUME_24H') and self.settings.MIN_VOLUME_24H:
                volume_24h = getattr(token_db_data, 'volume_24h', 0) or 0
                if volume_24h < self.settings.MIN_VOLUME_24H:
                    self.logger.debug(f"Token {mint} volume ({volume_24h}) < min {self.settings.MIN_VOLUME_24H}")
                    return False
                    
            # Check liquidity
            if hasattr(self.settings, 'MIN_LIQUIDITY') and self.settings.MIN_LIQUIDITY:
                liquidity = getattr(token_db_data, 'liquidity', 0) or 0
                if liquidity < self.settings.MIN_LIQUIDITY:
                    self.logger.debug(f"Token {mint} liquidity ({liquidity}) < min {self.settings.MIN_LIQUIDITY}")
                    return False
                    
            # Check market cap (if available)
            if hasattr(self.settings, 'MIN_MARKET_CAP') and self.settings.MIN_MARKET_CAP:
                market_cap = getattr(token_db_data, 'market_cap', 0) or getattr(token_db_data, 'fdv', 0) or 0
                if market_cap < self.settings.MIN_MARKET_CAP:
                    self.logger.debug(f"Token {mint} mcap ({market_cap}) < min {self.settings.MIN_MARKET_CAP}")
                    return False
                
            return True
            
        except Exception as e:
            mint = getattr(token_db_data, 'mint', 'unknown') if token_db_data else 'unknown'
            self.logger.error(f"Error checking basic criteria for {mint}: {str(e)}", exc_info=True)
            return False

    # --- Strategy Signal Generation Helpers (To be called from handler) ---
    # These methods now need access to CALCULATED indicators, not just raw token data

    def _generate_breakout_signals(self, latest_price: float, indicators: Dict, token_category: str) -> Optional[Dict]:
        """Generate signals for breakout strategy based on calculated indicators."""
        try:
            # Example: Use BBWidth or ATR for volatility, check volume trend
            # This needs defining based on the actual breakout logic required.
            # Placeholder logic:
            volume_trend = indicators.get('volume_trend') # Need this calculated
            if volume_trend is not None and volume_trend > 0.1: # Example: Volume increasing
                return {
                    'action': 'BUY',
                    'reason': 'Breakout signal (Volume Trend)',
                    'confidence': 0.8,
                    'priority': TradePriority.NORMAL_BUY # Assign priority
                }
            return None
        except Exception as e:
            self.logger.error(f"Error generating breakout signals: {e}", exc_info=True)
            return None

    def _generate_trend_signals(self, latest_price: float, indicators: Dict, token_category: str) -> Optional[Dict]:
        """Generate signals for trend following strategy based on calculated indicators."""
        try:
            rsi = indicators.get('rsi')
            adx = indicators.get('adx')
            macd_hist = indicators.get('macd_histogram')

            # Use category-specific thresholds if available (TEMPORARILY MORE SENSITIVE)
            rsi_oversold = self.thresholds.get(f'{token_category}_RSI_OVERSOLD', 40)  # More sensitive: 40 instead of 30
            rsi_overbought = self.thresholds.get(f'{token_category}_RSI_OVERBOUGHT', 60)  # More sensitive: 60 instead of 70
            adx_threshold = self.thresholds.get('MIN_ADX_THRESHOLD', 20)  # More sensitive: 20 instead of 25
            
            # Check trend conditions
            if (adx is not None and adx > adx_threshold and
               rsi is not None and rsi > rsi_oversold and rsi < rsi_overbought and
               macd_hist is not None and macd_hist > 0):
                return {
                    'action': 'BUY',
                    'reason': 'Trend following signal',
                    'confidence': 0.7,
                    'priority': TradePriority.NORMAL_BUY # Assign priority
                }
            return None
        except Exception as e:
            self.logger.error(f"Error generating trend signals: {e}", exc_info=True)
            return None

    def _generate_reversion_signals(self, latest_price: float, indicators: Dict, token_category: str) -> Optional[Dict]:
        """Generate signals for mean reversion strategy based on calculated indicators."""
        try:
            rsi = indicators.get('rsi')
            lower_bb = indicators.get('bollinger_bands', {}).get('lower')

            # Use category-specific thresholds (TEMPORARILY MORE SENSITIVE)
            rsi_oversold = self.thresholds.get(f'{token_category}_RSI_OVERSOLD', 40)  # More sensitive: 40 instead of 30
            
            # Check oversold conditions
            if (rsi is not None and rsi < rsi_oversold and
                lower_bb is not None and latest_price < lower_bb):
                return {
                    'action': 'BUY',
                    'reason': 'Mean reversion signal (RSI oversold & below Lower BB)',
                    'confidence': 0.6,
                    'priority': TradePriority.NORMAL_BUY # Assign priority
                }
            return None
        except Exception as e:
            self.logger.error(f"Error generating reversion signals: {e}", exc_info=True)
            return None

    def _generate_default_signals(self, latest_price: float, indicators: Dict, token_category: str) -> Optional[Dict]:
        """Generate default signals based on calculated indicators."""
        try:
            rsi = indicators.get('rsi')
            volume_trend = indicators.get('volume_trend') # Example dependency
            
            # Basic signal generation (TEMPORARILY MORE SENSITIVE)
            if rsi is not None and rsi > 35 and rsi < 65 and volume_trend is not None and volume_trend > -0.1: # More sensitive: wider RSI range and allow slight volume decrease
                return {
                    'action': 'BUY',
                    'reason': 'Default signal (Neutral RSI & Volume Up)',
                    'confidence': 0.5,
                    'priority': TradePriority.NORMAL_BUY # Assign priority
                }
            return None
        except Exception as e:
            self.logger.error(f"Error generating default signals: {e}", exc_info=True)
            return None

    # --- SL/TP Calculation (Remains mostly the same, uses latest price) ---
    def _calculate_stop_loss(self, price: float, strategy: str) -> float:
        """Calculate stop loss price (USD-based for backward compatibility)."""
        return self._calculate_stop_loss_sol(price, strategy)
    
    def _calculate_stop_loss_sol(self, price_sol: float, strategy: str) -> float:
        """Calculate stop loss price in SOL (PRIMARY METHOD FOR SOL-BASED TRADING)."""
        try:
            # Get settings
            default_sl = float(self.settings.get('DEFAULT_STOP_LOSS', 0.05))
            tight_sl = float(self.settings.get('TIGHT_STOP_LOSS', 0.02))
            wide_sl = float(self.settings.get('WIDE_STOP_LOSS', 0.1))
            
            # Strategy-specific stop losses
            if strategy == 'breakout':
                sl_price_sol = price_sol * (1 - tight_sl)
            elif strategy == 'trend_following':
                sl_price_sol = price_sol * (1 - wide_sl)
            elif strategy == 'mean_reversion':
                sl_price_sol = price_sol * (1 - default_sl)
            else:
                sl_price_sol = price_sol * (1 - default_sl)
            
            self.logger.debug(f"SOL Stop Loss: {sl_price_sol:.8f} SOL (Entry: {price_sol:.8f} SOL, Strategy: {strategy})")
            return sl_price_sol
            
        except Exception as e:
            self.logger.error(f"Error calculating SOL stop loss: {e}", exc_info=True)
            return price_sol * (1 - 0.05)  # 5% fallback

    def _calculate_take_profit(self, price: float, strategy: str) -> float:
        """Calculate take profit based on strategy (USD-based for backward compatibility)."""
        return self._calculate_take_profit_sol(price, strategy)
    
    def _calculate_take_profit_sol(self, price_sol: float, strategy: str) -> float:
        """Calculate take profit price in SOL (PRIMARY METHOD FOR SOL-BASED TRADING)."""
        try:
            # Get settings
            default_tp = float(self.settings.get('DEFAULT_TAKE_PROFIT', 0.1))
            aggressive_tp = float(self.settings.get('AGGRESSIVE_TAKE_PROFIT', 0.2))
            conservative_tp = float(self.settings.get('CONSERVATIVE_TAKE_PROFIT', 0.05))
            
            # Strategy-specific take profits
            if strategy == 'breakout':
                tp_price_sol = price_sol * (1 + aggressive_tp)
            elif strategy == 'trend_following':
                tp_price_sol = price_sol * (1 + default_tp)
            elif strategy == 'mean_reversion':
                tp_price_sol = price_sol * (1 + conservative_tp)
            else:
                tp_price_sol = price_sol * (1 + default_tp)
            
            self.logger.debug(f"SOL Take Profit: {tp_price_sol:.8f} SOL (Entry: {price_sol:.8f} SOL, Strategy: {strategy})")
            return tp_price_sol
            
        except Exception as e:
            self.logger.error(f"Error calculating SOL take profit: {e}", exc_info=True)
            return price_sol * (1 + 0.1)  # 10% fallback

    # --- Specific Strategy Execution Methods (May become obsolete) ---
    # async def trend_following(self, tokens: List[Dict]): ...
    # async def mean_reversion(self, tokens: List[Dict]): ...

    # --- Entry/Exit Check Methods (Logic moved to handler or PositionManagement) ---
    # async def check_entry_criteria(self, token: Dict) -> bool:
    # async def check_exit_criteria(self, token: Dict) -> bool:
    # async def _check_technical_criteria(self, token: Dict) -> bool:
    # def _check_risk_criteria(self, token: Dict) -> bool:
    # def _check_stop_loss(self, token: Dict) -> bool:
    # def _check_take_profit(self, token: Dict) -> bool:
    # async def _check_technical_exit(self, position_data: Dict) -> bool:

    # --- Indicator Calculation Helpers (REMOVED - Use static methods from data.indicators) ---
    # def _calculate_rsi(self, price_data: List[Dict], period: int = 14) -> float:
    # def _calculate_macd(self, price_data: List[Dict]) -> float:
    # def _calculate_ema(self, prices: List[float], period: int) -> float:
    # def _calculate_volume_trend(self, price_data: List[Dict], period: int = 24) -> float:
    # def _calculate_net_volume(self, price_data: List[Dict], period: int = 24) -> float:
    # def _calculate_sma(self, price_data: List[Dict], period: int) -> float:

    # --- Watchlist/Entry Price Methods (Need rethinking/removal) ---
    # def _get_entry_price(self, token_mint: str) -> Optional[float]:
    # async def _load_watchlists(self):

    # --- NEW: Modified Real-Time Event Handler with TSL --- #
    async def handle_realtime_price_update(self, event_data: Dict):
        """
        Handles incoming real-time price updates. 

        Behavior depends on EES operation mode:
        1. Direct Subscription Mode (if `self.trade_queue` is present):
           - EES subscribes directly to MarketData.
           - This method is the primary handler for price events.
           - It updates internal price history (`self.price_history`).
           - If the event is for `self.active_mint` (if set for focused trading), 
             it might trigger internal signal evaluation logic (though currently, periodic evaluators are primary for this mode).
        2. Signal Generation Mode (if `self.trade_queue` is None):
           - EES is typically managed by StrategyEvaluator (SE).
           - SE subscribes to MarketData and calls `get_signal_on_price_event` with event data.
           - If this method (`handle_realtime_price_update`) is ALSO called (e.g., due to an EES-internal subscription 
             that wasn't disabled), its main role here is to update `self.price_history`.
             Signal generation itself is handled by `get_signal_on_price_event`.

        Args:
            event_data (Dict): The price update event data from MarketData, typically includes
                               {'mint': str, 'price': float, 'timestamp': datetime, 'source': str}.
        """
        # This method's role changes. If EES subscribes itself (has trade_queue), it uses this.
        # If SE subscribes, SE calls get_signal_on_price_event.

        mint = event_data.get('mint')
        price = event_data.get('price')
        timestamp = event_data.get('timestamp')

        self.logger.debug(f"EES.handle_realtime_price_update (direct sub mode) for {mint} at {timestamp} with price {price}")

        if not mint or price is None:
            self.logger.debug(f"EES.handle_realtime_price_update: Incomplete event (ignored): {event_data}")
            return

        try:
            current_price = float(price)
            if current_price <= 0:
                self.logger.debug(f"EES.handle_realtime_price_update: Ignoring non-positive price {price} for {mint}")
                return

            if mint not in self.price_history:
                self.price_history[mint] = collections.deque(maxlen=self.max_history_len)
            self.price_history[mint].append(current_price)
            
            # If EES is in direct trading mode and this specific mint is its active_mint (e.g. for single token focus)
            # it could trigger its own signal evaluation here.
            if self.trade_queue and mint == self.active_mint:
                 self.logger.debug(f"EES.handle_realtime_price_update: Active mint {mint} updated. Consider triggering internal eval if in standalone mode.")
                 # Potentially call a consolidated signal check method that returns a signal or acts.
                 # For now, standalone operation uses the periodic evaluators.
                 pass


        except (ValueError, TypeError) as e:
            self.logger.warning(f"EES.handle_realtime_price_update: Invalid price ({price}) for {mint}: {e}")
        except Exception as e:
            self.logger.error(f"EES.handle_realtime_price_update: Error handling price update for {mint}: {e}", exc_info=True)

    async def get_signal_on_price_event(self, event_data: Dict, pool_address: Optional[str] = None, dex_id: Optional[str] = None) -> Optional[Dict]:
        """
        Evaluates signals for the currently active_mint based on a new price event.
        This method is intended to be called by an external orchestrator like StrategyEvaluator.
        Returns a trade signal dictionary if action is warranted, otherwise None.
        """
        mint_event = event_data.get('mint')
        price_event = event_data.get('price')
        timestamp_event = event_data.get('timestamp')

        if not self.active_mint or mint_event != self.active_mint:
            # self.logger.debug(f"EES.get_signal_on_price_event: Received event for {mint_event} but active_mint is {self.active_mint}. Ignoring.")
            return None

        if price_event is None:
            self.logger.warning(f"EES.get_signal_on_price_event: Received event for active mint {self.active_mint} with no price. Data: {event_data}")
            return None

        try:
            # Handle different price formats
            if isinstance(price_event, dict):
                # Extract price from dictionary - try different possible keys
                current_price = None
                for price_key in ['price_usd', 'price_sol', 'price', 'priceUsd']:
                    if price_key in price_event and price_event[price_key] is not None:
                        current_price = float(price_event[price_key])
                        break
                
                if current_price is None:
                    self.logger.warning(f"EES.get_signal_on_price_event: Could not extract price from dict {price_event} for active mint {self.active_mint}")
                    return None
            else:
                # Handle simple numeric price
                current_price = float(price_event)
            
            if current_price <= 0:
                self.logger.warning(f"EES.get_signal_on_price_event: Ignoring non-positive price {current_price} for active mint {self.active_mint}")
                return None
        except (ValueError, TypeError) as e:
            self.logger.warning(f"EES.get_signal_on_price_event: Invalid price ({price_event}) for active mint {self.active_mint}: {e}")
            return None

        # Update internal price history for the active_mint with SOL price
        if self.active_mint not in self.price_history: # Should have been set by set_active_mint
            self.price_history[self.active_mint] = collections.deque(maxlen=self.max_history_len)
        
        # Convert current_price to SOL if it's in USD (for SOL-based trading)
        current_price_sol = await self._convert_price_to_sol(current_price, self.active_mint)
        self.price_history[self.active_mint].append(current_price_sol)
        history = self.price_history[self.active_mint]
        
        # self.logger.debug(f"EES.get_signal_on_price_event: Updated price history for {self.active_mint}. Price: {current_price}, History len: {len(history)}")

        if len(history) < MIN_INDICATOR_PERIOD:
            # self.logger.debug(f"EES.get_signal_on_price_event: Not enough history for {self.active_mint} ({len(history)}/{MIN_INDICATOR_PERIOD}) to generate signal.")
            return None

        # --- Check if already holding position (for entry logic) ---
        # This requires access to position data. OrderManager is available.
        has_open_position = False
        current_position_data = None
        if self.order_manager:
            current_position_data = self.order_manager.get_position(self.active_mint) # OrderManager has get_position
            if current_position_data and current_position_data.get('quantity', 0) > 0:
                has_open_position = True
        else:
            self.logger.warning("EES.get_signal_on_price_event: OrderManager not available, cannot check current position.")
            # Decide behavior: assume no position, or skip signal generation? For now, assume no position if OM is missing.


        # --- Calculate Indicators ---
        # This part is from evaluate_entry_signals_periodically
        prices_series = pd.Series(list(history))
        calculated_indicators = {}
        try:
            rsi_series = IndicatorCalculator.rsi(prices_series, period=MIN_RSI_PERIOD)
            calculated_indicators['rsi'] = rsi_series.iloc[-1] if not rsi_series.empty else None
            
            macd_fast = self.thresholds.get('MACD_FAST_PERIOD', 12) if self.thresholds else 12
            macd_slow = self.thresholds.get('MACD_SLOW_PERIOD', 26)
            macd_signal_p = self.thresholds.get('MACD_SIGNAL_PERIOD', 9)
            macd_line, signal_line, hist_macd = IndicatorCalculator.macd(prices_series,
                                                                   fast_period=macd_fast,
                                                                   slow_period=macd_slow,
                                                                   signal_period=macd_signal_p)
            calculated_indicators['macd_histogram'] = hist_macd.iloc[-1] if not hist_macd.empty else None
            
            bb_period = self.thresholds.get('BB_PERIOD', 20)
            bb_std = self.thresholds.get('BB_STD_DEV', 2.0)
            upper, middle, lower = IndicatorCalculator.bollinger_bands(prices_series, period=bb_period, std_dev=bb_std)
            calculated_indicators['bollinger_bands'] = {
                'upper': upper.iloc[-1] if not upper.empty else None,
                'middle': middle.iloc[-1] if not middle.empty else None,
                'lower': lower.iloc[-1] if not lower.empty else None
            }
            # self.logger.debug(f"EES.get_signal_on_price_event: Indicators for {self.active_mint}: {calculated_indicators}")
        except Exception as indi_calc_e:
            self.logger.error(f"EES.get_signal_on_price_event: Error calculating indicators for {self.active_mint}: {indi_calc_e}", exc_info=True)
            return None # Skip if indicators fail

        # --- ENTRY LOGIC ---
        if not has_open_position:
            # Fetch Token Data from DB & Check Basic Criteria for entry
            token_db_data = await self.db.get_token(self.active_mint) # Token model instance
            if not token_db_data:
                self.logger.warning(f"EES.get_signal_on_price_event: Could not find token data in DB for {self.active_mint} during entry eval.")
                return None

            # Prepare token_data for _check_basic_criteria, it expects a dict with 'api_data' and 'latest_price'
            # We need to map Token model fields to something _check_basic_criteria can use, or refactor _check_basic_criteria.
            # For now, let's try to construct something plausible or acknowledge this needs refactoring.
            # Assuming token_db_data (Token model) has fields like price, volume_24h, liquidity, market_cap (fdv), overall_filter_passed
            # _check_basic_criteria uses: token_data.get('latest_price'), api_data.get('volume')['h24'], api_data.get('liquidity')['usd'], api_data.get('fdv'), token_data.get('overall_filter_passed')
            
            # Simplification: _check_basic_criteria directly uses fields from token_db_data (Token model)
            # and current_price from event. This means _check_basic_criteria needs adjustment.
            # For now, we call a refactored version or assume it's refactored.
            
            # Let's assume _check_basic_criteria is adapted to use token_db_data (Token model) and current_price
            # Or we inline a simplified check here.
            
            # Basic check based on Token model data (example)
            if not token_db_data.overall_filter_passed:
                 self.logger.debug(f"EES.get_signal_on_price_event: Token {self.active_mint} did not pass overall filters according to DB.")
                 return None
            if self.settings.MIN_VOLUME_24H and (token_db_data.volume_24h or 0) < self.settings.MIN_VOLUME_24H:
                 self.logger.debug(f"EES.get_signal_on_price_event: Token {self.active_mint} volume {token_db_data.volume_24h} < min {self.settings.MIN_VOLUME_24H}")
                 return None
            if self.settings.MIN_LIQUIDITY and (token_db_data.liquidity or 0) < self.settings.MIN_LIQUIDITY:
                 self.logger.debug(f"EES.get_signal_on_price_event: Token {self.active_mint} liquidity {token_db_data.liquidity} < min {self.settings.MIN_LIQUIDITY}")
                 return None
            # Add other checks from _check_basic_criteria as needed (e.g. market cap if available on Token model)

            token_category = getattr(token_db_data, 'category', 'FRESH').upper() # Use getattr for safety
            
            # --- Call Signal Generation Logic (e.g., _generate_default_signals) ---
            # These methods need to be callable with (latest_price, indicators, token_category)
            # and return a signal dict or None.
            entry_signal_details = self._generate_default_signals(current_price, calculated_indicators, token_category) # Example

            if entry_signal_details and entry_signal_details.get('action') == 'BUY':
                self.logger.info(f"EES.get_signal_on_price_event: ENTRY SIGNAL generated for {self.active_mint}: {entry_signal_details}")
                
                # Construct the full signal to return to StrategyEvaluator
                # StrategyEvaluator will determine actual trade size based on its settings/wallet.
                # EES provides the intent and context.
                trade_amount_usd_config_key = f'{token_category}_TRADE_AMOUNT_USD'
                default_trade_amount_usd = self.settings.DEFAULT_TRADE_AMOUNT_USD if hasattr(self.settings, 'DEFAULT_TRADE_AMOUNT_USD') else 10.0 # Default if not in settings
                
                # Get trade amount from settings, fallback to a general default.
                # Thresholds class might be a better place for these if settings don't have them directly.
                trade_amount_usd = default_trade_amount_usd
                if self.thresholds and hasattr(self.thresholds, 'get_value'): # Check if thresholds is proper instance
                    trade_amount_usd = self.thresholds.get_value(trade_amount_usd_config_key, default_trade_amount_usd)
                elif hasattr(self.settings, trade_amount_usd_config_key): # Fallback to direct settings attribute
                     trade_amount_usd = getattr(self.settings, trade_amount_usd_config_key)
                
                # Signal needs 'mint', 'action', 'price', 'reason', 'confidence', 'order_type' (optional), 'amount_usd' or 'base_token_amount'
                signal_to_return = {
                    "mint": self.active_mint,
                    "action": "BUY",
                    "price": current_price, # Current price at time of signal
                    "reason": entry_signal_details.get('reason', "Default entry signal"),
                    "confidence": entry_signal_details.get('confidence', 0.7), # Default confidence
                    "order_type": entry_signal_details.get('order_type', 'MARKET'), # Default order type
                    "strategy_name": entry_signal_details.get('strategy', 'default'), # From EES internal strategy assignment
                    "amount_usd": trade_amount_usd, # Suggested trade size from EES config
                    # "base_token_amount": None, # SE can calculate this from amount_usd and price
                    "indicators": {k: v for k, v in calculated_indicators.items() if v is not None},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "pool_address": pool_address, # Pass through from SE
                    "dex_id": dex_id, # Pass through from SE
                }
                # Initialize TSL High Water Mark (or SE can do this upon successful buy)
                self.position_hwm[self.active_mint] = current_price
                self.logger.info(f"EES: Initialized TSL HWM for potential position {self.active_mint} at {current_price:.6f}")
                return signal_to_return
            # else: self.logger.debug(f"EES.get_signal_on_price_event: No entry signal for {self.active_mint} at price {current_price}.")

        # --- EXIT LOGIC ---
        elif has_open_position:
            # self.logger.debug(f"EES.get_signal_on_price_event: Has open position for {self.active_mint}. Evaluating exit signals at price {current_price}.")
            # This part needs to adapt logic from `monitor_and_manage_positions`
            
            exit_reason = None
            entry_price_float = None
            strategy = current_position_data.get('strategy', 'default') if current_position_data else 'default'

            # --- Trailing Stop Loss (TSL) Check ---
            # Ensure OrderManager provided position_data and it contains entry_price
            entry_price_from_position = current_position_data.get('entry_price')
            if entry_price_from_position is None:
                self.logger.warning(f"EES.get_signal_on_price_event: Missing entry_price in position_data for TSL check on {self.active_mint}. Cannot evaluate TSL.")
            else:
                entry_price_float = float(entry_price_from_position)
                trailing_stop_pct_str = getattr(self.settings, 'TRAILING_STOP_PCT', "0.05") # Default to 5% if not in settings
                
                try:
                    trailing_stop_pct = float(trailing_stop_pct_str)
                except ValueError:
                    self.logger.error(f"EES: Invalid TRAILING_STOP_PCT format: '{trailing_stop_pct_str}'. Defaulting to 0.05.")
                    trailing_stop_pct = 0.05

                if trailing_stop_pct > 0:
                    hwm = self.position_hwm.get(self.active_mint, entry_price_float) # Initialize with entry_price if not set
                    new_hwm = max(hwm, current_price)
                    if new_hwm > hwm:
                        self.logger.info(f"EES: Updating TSL HWM for {self.active_mint}: {hwm:.6f} -> {new_hwm:.6f}")
                        self.position_hwm[self.active_mint] = new_hwm
                    else:
                         hwm = new_hwm 
                    
                    tsl_price = hwm * (1 - trailing_stop_pct)
                    
                    if current_price <= tsl_price:
                        self.logger.info(f"EES.get_signal_on_price_event: TSL TRIGGER for {self.active_mint}. Price {current_price:.6f} <= TSL Price {tsl_price:.6f} (HWM {hwm:.6f})")
                        exit_reason = "trailing_stop_loss"

            # --- Fixed Stop Loss (SL) Check (Only if TSL didn't trigger and entry_price is available) ---
            if not exit_reason and entry_price_float is not None:
                sl_price = self._calculate_stop_loss(entry_price_float, strategy) 
                if current_price <= sl_price:
                    self.logger.info(f"EES.get_signal_on_price_event: SL TRIGGER for {self.active_mint}. Price {current_price:.6f} <= SL Price {sl_price:.6f}")
                    exit_reason = "stop_loss"

            # --- Fixed Take Profit (TP) Check (Only if TSL/SL didn't trigger and entry_price is available) ---
            if not exit_reason and entry_price_float is not None:
                tp_price = self._calculate_take_profit(entry_price_float, strategy)
                if current_price >= tp_price:
                    self.logger.info(f"EES.get_signal_on_price_event: TP TRIGGER for {self.active_mint}. Price {current_price:.6f} >= TP Price {tp_price:.6f}")
                    exit_reason = "take_profit"

            # --- Time-Based Exit Check (Only if TSL/SL/TP didn't trigger) ---
            if not exit_reason and current_position_data: # current_position_data needed for _check_time_based_exit
                if self._check_time_based_exit(current_position_data):
                    self.logger.info(f"EES.get_signal_on_price_event: TIME_BASED TRIGGER for {self.active_mint}.")
                    exit_reason = "time_based"

            # Finalize SELL signal construction if an exit reason was set
            if exit_reason and current_position_data: # Ensure current_position_data is available
                position_quantity = current_position_data.get('quantity', 0.0)
                # Ensure quantity is a float, default to 0.0 if not convertible
                try:
                    position_quantity_float = float(position_quantity)
                except (ValueError, TypeError):
                    self.logger.warning(f"EES: Invalid quantity '{position_quantity}' in position_data for {self.active_mint}. Defaulting to 0.0.")
                    position_quantity_float = 0.0

                if position_quantity_float > 0:
                    exit_signal_to_return = {
                        "mint": self.active_mint,
                        "action": "SELL",
                        "price": current_price, # Current price at time of signal
                        "reason": exit_reason,
                        "confidence": 0.95, # Default high confidence for TSL/SL/TP/Time exits
                        "order_type": "MARKET",
                        "quantity": position_quantity_float, 
                        "pool_address": pool_address, # Pass through from SE
                        "dex_id": dex_id, # Pass through from SE
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "indicators": {k: v for k, v in calculated_indicators.items() if v is not None},
                        "strategy_name": current_position_data.get('strategy', 'default') # Get strategy from position data
                    }
                    self.logger.info(f"EES: Prepared SELL signal for {self.active_mint} due to {exit_reason}. Quantity: {position_quantity_float}")
                    
                    # Clean up TSL High Water Mark for this position as we are about to signal an exit
                    if self.active_mint in self.position_hwm:
                        self.position_hwm.pop(self.active_mint, None)
                        self.logger.info(f"EES: Cleared TSL HWM for {self.active_mint} after generating SELL signal.")

                    return exit_signal_to_return
                else:
                    self.logger.warning(f"EES: Exit reason '{exit_reason}' for {self.active_mint}, but position quantity is {position_quantity_float}. No SELL signal generated.")
            # pass # TODO: Implement exit logic here -> This comment is now fully outdated

        return None # No signal generated

    # --- Periodic Entry Signal Evaluation --- #
    async def evaluate_entry_signals_periodically(self):
        """
        Periodically evaluates entry signals for tokens with sufficient history.
        To be called by TradeScheduler every INDICATORS_PERIOD seconds.
        """
        if not self._initialized:
            self.logger.warning("Strategy not initialized, skipping entry evaluation.")
            return
        if self.circuit_breaker.check():
            self.logger.warning("Circuit breaker active, skipping entry evaluation.")
            return

        self.logger.info(f"Starting periodic entry signal evaluation for {len(self.price_history)} tracked tokens...")
        evaluated_count = 0
        signal_count = 0

        # Create a copy of keys to avoid issues if dict changes during iteration
        mints_to_evaluate = list(self.price_history.keys())

        for mint in mints_to_evaluate:
            try:
                # --- Check Minimum History Length --- #
                history = self.price_history.get(mint)
                if not history or len(history) < MIN_INDICATOR_PERIOD:
                    # self.logger.debug(f"Not enough price history for {mint} ({len(history) if history else 0}/{MIN_INDICATOR_PERIOD}) for entry eval.")
                    continue

                current_price = history[-1] # Use the latest price from history
                evaluated_count += 1

                # --- Check if already holding position --- #
                if self.order_manager and self.order_manager.has_position(mint):
                     # self.logger.debug(f"Already holding position for {mint}, skipping entry eval.")
                     continue

                # --- Fetch Token Data & Check Basic Criteria --- #
                token_db_data = await self.db.get_token(mint)
                if not token_db_data:
                    self.logger.warning(f"Could not find token data in DB for {mint} during entry eval.")
                    continue
                if not self._check_basic_criteria(token_db_data):
                    # self.logger.debug(f"Token {mint} failed basic criteria check during entry eval.")
                    continue

                # --- Calculate Indicators --- #
                prices_series = pd.Series(list(history))
                calculated_indicators = {}
                try:
            # Calculate RSI
                    rsi_series = IndicatorCalculator.rsi(prices_series, period=MIN_RSI_PERIOD)
                    calculated_indicators['rsi'] = rsi_series.iloc[-1] if not rsi_series.empty else None
            # Calculate MACD
                    macd_fast = self.thresholds.get('MACD_FAST_PERIOD', 12)
                    macd_slow = self.thresholds.get('MACD_SLOW_PERIOD', 26)
                    macd_signal_p = self.thresholds.get('MACD_SIGNAL_PERIOD', 9)
                    macd_line, signal_line, hist = IndicatorCalculator.macd(prices_series,
                                                                           fast_period=macd_fast,
                                                                           slow_period=macd_slow,
                                                                           signal_period=macd_signal_p)
                    calculated_indicators['macd_histogram'] = hist.iloc[-1] if not hist.empty else None
                    # Calculate Bollinger Bands
                    bb_period = self.thresholds.get('BB_PERIOD', 20)
                    bb_std = self.thresholds.get('BB_STD_DEV', 2.0)
                    upper, middle, lower = IndicatorCalculator.bollinger_bands(prices_series, period=bb_period, std_dev=bb_std)
                    calculated_indicators['bollinger_bands'] = {
                        'upper': upper.iloc[-1] if not upper.empty else None,
                        'middle': middle.iloc[-1] if not middle.empty else None,
                        'lower': lower.iloc[-1] if not lower.empty else None
                    }
                    # Add other indicator calcs here if needed
                    # self.logger.debug(f"Calculated indicators for entry eval {mint}: {calculated_indicators}")
                except Exception as indi_calc_e:
                    self.logger.error(f"Error calculating indicators for entry eval {mint}: {indi_calc_e}", exc_info=True)
                    continue # Skip if indicators fail

                # --- Evaluate Entry Signal --- #
                token_category = token_db_data.get('category', 'FRESH').upper()
                entry_signal = self._generate_default_signals(current_price, calculated_indicators, token_category) # Use default for now

                # Assign strategy based on signal type if possible (optional enhancement)
                if entry_signal:
                     if 'Breakout' in entry_signal.get('reason', ''): entry_signal['strategy'] = 'breakout'
                     elif 'Trend' in entry_signal.get('reason', ''): entry_signal['strategy'] = 'trend_following'
                     elif 'Reversion' in entry_signal.get('reason', ''): entry_signal['strategy'] = 'mean_reversion'
                     else: entry_signal['strategy'] = 'default' # Fallback

                if entry_signal and entry_signal.get('action') == 'BUY':
                    signal_count += 1
                    self.logger.info(f"ENTRY SIGNAL generated for {mint}: {entry_signal}")
                    # --- Enqueue BUY Trade --- #
                    try:
                        trade_amount_usd = float(self.settings.get(f'{token_category}_TRADE_AMOUNT_USD', self.settings.DEFAULT_TRADE_AMOUNT_USD))
                        quantity = trade_amount_usd / current_price if current_price > 0 else 0

                        if quantity <= 0:
                            self.logger.warning(f"Calculated zero or negative quantity for BUY {mint}. Skipping.")
                            continue

                        # --- Validations --- #
                        quote_mint = self.settings.QUOTE_MINT_ADDRESS # e.g., USDC or SOL address
                        quote_decimals = self.settings.QUOTE_MINT_DECIMALS # e.g., 6 for USDC, 9 for SOL
                        atomic_amount = int(trade_amount_usd * (10**quote_decimals)) # Amount in atomic units for validation

                        if self.balance_checker:
                            # Check if we have enough QUOTE currency (e.g., USDC, SOL)
                            has_balance, balance_msg = await self.balance_checker.check_balance(quote_mint, trade_amount_usd)
                            if not has_balance:
                                self.logger.warning(f"Insufficient QUOTE balance ({quote_mint}) for BUY {mint}: {balance_msg}")
                                continue # Skip trade if not enough quote currency

                        if self.trade_validator:
                            # Use validate_trade_params which expects atomic amount and input/output mints
                            input_mint_val = quote_mint
                            output_mint_val = mint
                            is_valid = await self.trade_validator.validate_trade_params(
                                input_mint=input_mint_val,
                                output_mint=output_mint_val,
                                amount_atomic=atomic_amount
                                # slippage_bps can be added later if needed by validator
                            )
                            if not is_valid:
                                self.logger.warning(f"Trade validation failed for BUY {mint}.")
                                continue # Skip trade if validation fails
                        # --- End Validations --- #

                        priority = entry_signal.get('priority', TradePriority.NORMAL_BUY)
                        trade_request = {
                            "mint": mint, # Target token to buy
                            "action": "BUY",
                            "quantity": trade_amount_usd, # OrderManager expects amount in USD for buys
                            "price": current_price, # Include price for reference
                            "priority": priority.value,
                            "metadata": {
                                "signal_reason": entry_signal.get('reason'),
                                "confidence": entry_signal.get('confidence'),
                                "strategy": entry_signal.get('strategy'),
                                "indicators": {k: v for k, v in calculated_indicators.items() if v is not None}, # Store non-None indicators
                                "expected_quantity": quantity, # Expected token quantity
                                "timestamp": datetime.now(timezone.utc).isoformat()
                                # Slippage/priority fee can be added by OrderManager or here
                            }
                        }
                        await self.trade_queue.enqueue_trade(trade_request)
                        self.logger.info(f"Enqueued BUY trade request for {mint} (Priority: {priority.name}). Reason: {entry_signal.get('reason')}")

                        # Initialize TSL High Water Mark upon enqueueing buy
                        # Note: Ideally, this happens *after* successful execution confirmation
                        # But for simplicity, initialize now. Consider moving to tracker callback.
                        self.position_hwm[mint] = current_price
                        self.logger.info(f"Initialized TSL HWM for potential position {mint} at {current_price:.6f}")

                    except Exception as trade_err:
                        self.logger.error(f"Error creating/enqueuing BUY trade for {mint}: {trade_err}", exc_info=True)
                # else: self.logger.debug(f"No entry signal for {mint}.")

            except Exception as eval_err:
                self.logger.error(f"Error evaluating entry for mint {mint}: {eval_err}", exc_info=True)

        self.logger.info(f"Finished periodic entry signal evaluation. Evaluated: {evaluated_count}, Signals Found: {signal_count}")

    # --- Periodic Exit Monitoring (SL/TP/TSL) --- #
    async def monitor_and_manage_positions(self):
        """
        Monitors existing positions and triggers exits (SL/TP/TSL) if criteria are met.
        To be called by TradeScheduler every SLTP_CHECK_PERIOD seconds.
        """
        if not self._initialized:
            self.logger.warning("Strategy not initialized, skipping position monitoring.")
            return
        if not self.order_manager:
             self.logger.error("OrderManager not available, cannot monitor positions.")
             return
        if self.circuit_breaker.check():
            self.logger.warning("Circuit breaker active, skipping position monitoring.")
            return

        # Check and confirm sent transactions first if transaction_tracker available
        # This updates OrderManager's position state based on confirmed trades
        if self.transaction_tracker:
                try:
                    await self.transaction_tracker.check_and_confirm_transactions()
                except Exception as tracker_err:
                    self.logger.error(f"Error while checking transactions in monitor loop: {tracker_err}", exc_info=True)
            
        active_positions = self.order_manager.get_all_positions() # Get currently loaded positions
        if not active_positions:
            self.logger.debug("No active positions to monitor.")
            return

        self.logger.info(f"Starting position monitoring for {len(active_positions)} position(s)...")
        exit_count = 0

        # Create a copy of items to avoid issues if dict changes during iteration
        positions_to_monitor = list(active_positions.items())

        for mint, position_data in positions_to_monitor:
            exit_reason = None
            exit_priority = TradePriority.HIGH_SELL # Default exit priority
            tsl_price = None # Variable to store calculated TSL price if triggered
            try:
                if not isinstance(position_data, dict) or 'entry_price' not in position_data or 'size' not in position_data:
                    self.logger.error(f"Invalid position data format for {mint}: {position_data}. Removing from OrderManager.")
                    # Consider removing the position if data is corrupt
                    # await self.order_manager.remove_position(mint)
                    continue

                entry_price_str = position_data.get('entry_price')
                position_size_str = position_data.get('size')
                
                if entry_price_str is None or position_size_str is None:
                    self.logger.error(f"Missing entry_price or size for position {mint}. Skipping.")
                    continue
                    
                entry_price = float(entry_price_str)
                position_size = float(position_size_str)
                strategy = position_data.get('strategy', 'default')

                if position_size <= 0:
                    self.logger.warning(f"Position size is zero or negative for {mint}. Skipping exit check.")
                    continue
                    
                # --- Get Current Price ---
                current_price = None
                price_history = self.price_history.get(mint)
                price_staleness_threshold_seconds = 60 # Example: Use history if price is < 60s old

                # Simplification: Always try to fetch the latest price for exits for accuracy
                # if price_history:
                #     # Check timestamp if available - for now, just use latest
                #     # TODO: Add timestamp check to history entries
                #     current_price = price_history[-1]

                # Always try fetching for critical exit checks
                try:
                    fetched_price_data = await self.market_data.get_current_price(mint)
                    if fetched_price_data and fetched_price_data.get('price') is not None:
                        current_price = float(fetched_price_data.get('price'))
                        # Optionally update history here too
                        # if mint in self.price_history:
                        #      self.price_history[mint].append(current_price)
                        # else:
                        #      self.price_history[mint] = collections.deque([current_price], maxlen=self.max_history_len)
                    else:
                         self.logger.warning(f"Fetched price data invalid for {mint} during exit check.")
                except Exception as price_fetch_err:
                     self.logger.error(f"Failed to fetch current price for {mint} during exit check: {price_fetch_err}")

                if current_price is None or current_price <= 0:
                    self.logger.warning(f"Could not determine valid current price ({current_price}) for {mint}. Skipping exit check.")
                    continue
                # current_price = float(current_price) # Already ensured float

                # --- TSL Check ---
                trailing_stop_pct_str = self.settings.get('TRAILING_STOP_PCT')
                trailing_stop_pct = float(trailing_stop_pct_str) if trailing_stop_pct_str is not None else 0.0

                if trailing_stop_pct > 0: # Only check if TSL is enabled (percentage > 0)
                    # Get current HWM, initializing with entry price if not set
                    hwm = self.position_hwm.get(mint, entry_price)
                    # Update HWM if new high is reached
                    new_hwm = max(hwm, current_price)
                    if new_hwm > hwm: # Log HWM updates
                         self.logger.info(f"Updating HWM for {mint}: {hwm:.6f} -> {new_hwm:.6f}")
                         self.position_hwm[mint] = new_hwm
                    else:
                         hwm = new_hwm # Ensure hwm variable has the latest value

                    # Calculate TSL level
                    tsl_price = hwm * (1 - trailing_stop_pct)
                    # Check if TSL is hit
                    if current_price <= tsl_price:
                        exit_reason = "trailing_stop_loss"
                        self.logger.warning(f"TRAILING STOP LOSS trigger for {mint}: Price={current_price:.6f} <= TSL={tsl_price:.6f} (HWM={hwm:.6f})")
                        exit_priority = TradePriority.CRITICAL_SELL # TSL hits should be highest priority

                # --- Fixed Stop Loss (SL) Check (Only if TSL didn't trigger and entry_price is available) ---
                if not exit_reason and entry_price is not None:
                    sl_price = self._calculate_stop_loss(entry_price, strategy) 
                    if current_price <= sl_price:
                        self.logger.warning(f"STOP LOSS trigger for {mint}: Price={current_price:.6f} <= SL={sl_price:.6f}")
                        exit_reason = "stop_loss"
                        exit_priority = TradePriority.HIGH_SELL

                # --- Fixed Take Profit (TP) Check (Only if TSL/SL didn't trigger and entry_price is available) ---
                if not exit_reason and entry_price is not None:
                    tp_price = self._calculate_take_profit(entry_price, strategy)
                    if current_price >= tp_price:
                        self.logger.info(f"TAKE PROFIT trigger for {mint}: Price={current_price:.6f} >= TP={tp_price:.6f}")
                        exit_reason = "take_profit"
                        exit_priority = TradePriority.NORMAL_SELL

                # --- Time-Based Exit Check (Only if TSL/SL/TP didn't trigger) ---
                if not exit_reason: # position_data needed for _check_time_based_exit
                    if self._check_time_based_exit(position_data):
                        self.logger.info(f"TIME-BASED EXIT trigger for {mint}.")
                        exit_reason = "time_based"
                        exit_priority = TradePriority.NORMAL_SELL

                # --- Execute Exit Trade if Reason Found ---
                if exit_reason:
                    exit_count += 1
                    self.logger.warning(f"EXIT TRIGGER for {mint}: {exit_reason.upper()}")
                    
                    try:
                        # Create exit trade request
                        trade_request = {
                            "mint": mint,
                            "action": "SELL",
                            "quantity": position_size, # Sell entire position
                            "price": current_price,
                            "priority": exit_priority.value,
                            "metadata": {
                                "exit_reason": exit_reason,
                                "entry_price": entry_price,
                                "current_price": current_price,
                                "strategy": strategy,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "tsl_price": tsl_price if exit_reason == "trailing_stop_loss" else None
                            }
                        }
                        
                        if self.trade_queue:
                            await self.trade_queue.enqueue_trade(trade_request)
                            self.logger.info(f"Enqueued SELL trade for {mint} due to {exit_reason} (Priority: {exit_priority.name})")
                        
                        # Clean up TSL High Water Mark for this position
                        if mint in self.position_hwm:
                            self.position_hwm.pop(mint, None)
                            self.logger.info(f"Cleared TSL HWM for {mint} after exit trigger")
                            
                    except Exception as trade_err:
                        self.logger.error(f"Error creating/enqueuing SELL trade for {mint}: {trade_err}", exc_info=True)

            except (ValueError, TypeError) as num_err:
                self.logger.error(f"Numeric conversion error monitoring position {mint}: {num_err}. Data: {position_data}")
            except Exception as monitor_err:
                self.logger.error(f"Error monitoring position {mint}: {monitor_err}", exc_info=True)
                self.circuit_breaker.increment_failures() # Increment on unexpected errors

        self.logger.info(f"Finished position monitoring. Exits triggered: {exit_count}")

    # --- Helper Methods (Used by monitor_and_manage_positions) ---
    def _calculate_position_duration(self, position_data: Dict) -> float:
        """Calculate the duration of the position in hours."""
        entry_time_str = position_data.get('entry_timestamp') # Assuming OrderManager stores entry timestamp
        if not entry_time_str:
            # Fallback to using creation time if entry timestamp isn't set yet
            entry_time_str = position_data.get('created_at')
        if not entry_time_str:
            self.logger.warning(f"Missing entry_timestamp/created_at for position {position_data.get('mint')}, cannot calculate duration.")
            return 0.0
            
        try:
            # Handle potential timezone info (e.g., 'Z' or '+00:00')
            if isinstance(entry_time_str, datetime):
                 entry_dt = entry_time_str # Already a datetime object
            else:
                 # Try parsing ISO format, handling potential 'Z' for UTC
                 entry_dt = pd.to_datetime(entry_time_str).tz_convert(timezone.utc)

            if entry_dt.tzinfo is None: # Ensure timezone aware
                 self.logger.warning(f"Entry time {entry_time_str} parsed as naive datetime, assuming UTC.")
                 entry_dt = entry_dt.replace(tzinfo=timezone.utc)

            current_dt = datetime.now(timezone.utc)
            duration = (current_dt - entry_dt).total_seconds() / 3600  # Convert to hours
            return round(duration, 2)
        except Exception as e:
            self.logger.error(f"Error calculating position duration for {position_data.get('mint')} from '{entry_time_str}': {e}")
            return 0.0

    async def _calculate_profit_loss(self, position_data: Dict) -> Dict:
        """Calculate profit/loss metrics for the position (USD-based for backward compatibility)."""
        return await self._calculate_profit_loss_sol(position_data)
    
    async def _calculate_profit_loss_sol(self, position_data: Dict) -> Dict:
        """Calculate profit/loss metrics for the position in SOL (PRIMARY METHOD)."""
        mint = position_data.get('mint')
        entry_price_sol = position_data.get('entry_price_sol')  # SOL entry price
        entry_price_usd = position_data.get('entry_price')      # USD entry price (fallback)
        size = position_data.get('size')

        # Get current SOL price from price history (assumes SOL prices are being stored)
        current_price_sol = None
        current_price_usd = None
        
        if mint and mint in self.price_history:
             try:
                 # Assume price history now stores SOL prices after enhancement
                 current_price_sol = self.price_history[mint][-1]
             except IndexError:
                 pass # History might be empty

        # Fallback to getting current SOL price from market data
        if current_price_sol is None and self.market_data:
            try:
                current_price_sol = await self.market_data.get_token_price_sol(mint)
                if current_price_sol:
                    current_price_usd = await self.market_data.get_token_price_usd(mint)
            except Exception as e:
                self.logger.debug(f"Could not get current SOL price for {mint}: {e}")

        # Determine entry price (prefer SOL, fallback to USD estimation)
        if entry_price_sol is None and entry_price_usd is not None:
            # Estimate SOL entry price from USD if not available
            try:
                sol_price_usd = await self.market_data._get_sol_price_usd() if self.market_data else 150.0
                entry_price_sol = entry_price_usd / sol_price_usd if sol_price_usd > 0 else None
            except:
                entry_price_sol = None

        # Use fallback USD calculation if SOL data unavailable
        if entry_price_sol is None or current_price_sol is None:
            # Fallback to USD calculation
            entry_price = entry_price_usd or position_data.get('price', 0)
            current_price = current_price_usd or position_data.get('price', 0)
            
            if not all(isinstance(x, (int, float)) and x is not None for x in [entry_price, current_price, size]) or entry_price <= 0 or size <= 0:
                return {'amount_sol': 0.0, 'amount_usd': 0.0, 'percentage': 0.0}

            try:
                profit_loss_amount_usd = (current_price - entry_price) * size
                profit_loss_percentage = ((current_price - entry_price) / entry_price) * 100
                return {
                    'amount_sol': 0.0,  # Could not calculate SOL P&L
                    'amount_usd': round(profit_loss_amount_usd, 4),
                    'percentage': round(profit_loss_percentage, 2)
                }
            except ZeroDivisionError:
                self.logger.error(f"Division by zero calculating USD P/L for {mint} (entry price={entry_price})")
                return {'amount_sol': 0.0, 'amount_usd': 0.0, 'percentage': 0.0}

        # SOL-based calculation (PRIMARY)
        if not all(isinstance(x, (int, float)) and x is not None for x in [entry_price_sol, current_price_sol, size]) or entry_price_sol <= 0 or size <= 0:
            return {'amount_sol': 0.0, 'amount_usd': 0.0, 'percentage': 0.0}

        try:
            profit_loss_amount_sol = (current_price_sol - entry_price_sol) * size
            profit_loss_percentage = ((current_price_sol - entry_price_sol) / entry_price_sol) * 100
            
            # Also calculate USD equivalent for display
            profit_loss_amount_usd = 0.0
            if current_price_usd and entry_price_usd:
                profit_loss_amount_usd = (current_price_usd - entry_price_usd) * size
        
            return {
                'amount_sol': round(profit_loss_amount_sol, 8),   # PRIMARY: SOL P&L
                'amount_usd': round(profit_loss_amount_usd, 4),   # SECONDARY: USD P&L for display
                'percentage': round(profit_loss_percentage, 2)    # Percentage based on SOL
            }
        except ZeroDivisionError:
            self.logger.error(f"Division by zero calculating SOL P/L for {mint} (entry price={entry_price_sol} SOL)")
            return {'amount_sol': 0.0, 'amount_usd': 0.0, 'percentage': 0.0}
        except Exception as e:
            self.logger.error(f"Error calculating SOL P/L for {mint}: {e}")
            return {'amount_sol': 0.0, 'amount_usd': 0.0, 'percentage': 0.0}

    def _check_time_based_exit(self, position_data: Dict) -> bool:
        """Check if position should be exited based on time criteria."""
        max_duration_str = self.settings.get('MAX_POSITION_DURATION_HOURS')
        if max_duration_str is None:
             return False # Time-based exit disabled if setting is missing
        try:
             max_duration = float(max_duration_str)
             if max_duration <= 0:
                  return False # Disabled if zero or negative

             duration = self._calculate_position_duration(position_data)
             # Check duration > 0 to avoid exit on calculation error or brand new position
             return duration > 0 and duration >= max_duration
        except ValueError:
             self.logger.error(f"Invalid MAX_POSITION_DURATION_HOURS setting: {max_duration_str}")
        return False

    # --- Cleanup ---
    async def close(self):
        """Clean up resources."""
        try:
            self.logger.info("Closing EntryExitStrategy resources")
            # Unsubscribe if needed (MarketData might handle this)
            # if self.market_data:
            #      self.market_data.unsubscribe("realtime_price_update", self.handle_realtime_price_update)
            self.price_history.clear()
            self.position_hwm.clear() # Clear HWM tracking
        except Exception as e:
            self.logger.error(f"Error closing EntryExitStrategy: {str(e)}")
    
    async def _convert_price_to_sol(self, price: float, mint: str) -> float:
        """Convert a price to SOL if needed. Assumes price might be in USD and converts to SOL."""
        try:
            if self.market_data:
                # Try to get SOL price directly
                sol_price = await self.market_data.get_token_price_sol(mint)
                if sol_price and sol_price > 0:
                    return sol_price
                
                # Fallback: convert USD price to SOL
                usd_price = price  # Assume input price is in USD
                sol_price_usd = await self.market_data._get_sol_price_usd()
                if sol_price_usd and sol_price_usd > 0:
                    converted_sol_price = usd_price / sol_price_usd
                    return converted_sol_price
            
            # Final fallback: return original price (might be already in SOL)
            return price
            
        except Exception as e:
            self.logger.debug(f"Error converting price to SOL for {mint}: {e}")
            return price  # Return original price on error

    def set_active_mint(self, mint: str):
        self.logger.info(f"EES: Setting active mint to: {mint}")
        self.active_mint = mint
        # Ensure price history deque exists for this mint
        if mint not in self.price_history:
            self.price_history[mint] = collections.deque(maxlen=self.max_history_len)
            self.logger.info(f"EES: Initialized price history for new active mint: {mint}")
        # Reset other token-specific states if necessary, e.g., high-water marks for TSL
        if mint in self.position_hwm: # Reset HWM if it exists for this token
            del self.position_hwm[mint]
            self.logger.info(f"EES: Reset TSL high-water mark for new active mint: {mint}")

    def clear_active_mint(self, mint_to_clear: Optional[str] = None):
        cleared_mint = self.active_mint
        if mint_to_clear is None or self.active_mint == mint_to_clear:
            self.logger.info(f"EES: Clearing active mint (was: {self.active_mint}, requested for: {mint_to_clear if mint_to_clear else 'any'}).")
            self.active_mint = None
            # Optionally, clean up state for `cleared_mint` if it's no longer active.
            # For example, if price_history for non-active mints should be pruned:
            # if cleared_mint and cleared_mint in self.price_history and self.settings.PRUNE_INACTIVE_PRICE_HISTORY:
            #     del self.price_history[cleared_mint]
            #     self.logger.info(f"EES: Pruned price history for inactive mint: {cleared_mint}")
        else:
            self.logger.info(f"EES: Request to clear active mint {mint_to_clear}, but current active mint is {self.active_mint}. No change.")
                 