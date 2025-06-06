import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from config.settings import Settings
from config.thresholds import Thresholds
from config.filters_config import FiltersConfig
from utils import get_logger
from filters.whitelist import Whitelist
from data.token_database import TokenDatabase
from data.indicators import Indicators
from data.price_monitor import PriceMonitor
from filters.blacklist import Blacklist
from datetime import datetime, timezone
import logging
import json
from typing import List, Dict, Optional, TYPE_CHECKING, Any
from solana.rpc.async_api import AsyncClient
import httpx
from wallet.wallet_manager import WalletManager

if TYPE_CHECKING:
    from .entry_exit import EntryExitStrategy
    from execution.trade_queue import TradeQueue, TradeRequest, TradePriority
    from execution.order_manager import OrderManager
    from execution.transaction_tracker import TransactionTracker
    from wallet.balance_checker import BalanceChecker
    from wallet.trade_validator import TradeValidator
    from .risk_management import RiskManagement
    from .position_management import PositionManagement
    from .alert_system import AlertSystem

logger = logging.getLogger(__name__)

class StrategyEvaluator:
    """
    Evaluates market data for a specific token and generates trading signals.
    Works with real-time market data to determine entry and exit points.
    """
    
    def __init__(self, 
                 settings: Optional[Settings] = None,
                 db: Optional['TokenDatabase'] = None,
                 market_data = None,
                 indicators = None,
                 trade_queue = None,
                 order_manager = None):
        """
        Initialize the StrategyEvaluator with required components.
        
        Args:
            settings: Application settings
            db: TokenDatabase instance
            market_data: MarketData instance for price and market data
            indicators: Indicators instance for technical analysis
            trade_queue: TradeQueue for submitting trade orders
            order_manager: OrderManager for executing trades
        """
        self.settings = settings
        self.db = db
        self.market_data = market_data
        self.indicators = indicators
        self.trade_queue = trade_queue
        self.order_manager = order_manager
        
        # State tracking for each monitored token
        self._market_data_cache = {}  # Stores latest market data by mint
        self._trade_signals_cache = {}  # Stores latest signals by mint
        self._indicator_values = {}  # Stores calculated indicators by mint
        
        # Configuration for signal generation
        self._entry_conditions = {
            "rsi": {"below": 30},  # Buy when RSI below 30
            "macd": {"crossover": True},  # Buy on MACD crossover
            "volume": {"min_increase": 2.0}  # Buy when volume increases 2x
        }
        
        self._exit_conditions = {
            "rsi": {"above": 70},  # Sell when RSI above 70
            "macd": {"crossunder": True},  # Sell on MACD crossunder
            "profit": {"take_profit": 0.1}  # Take profit at 10%
        }
        
        self.logger = get_logger("StrategyEvaluator")
        self.logger.info("StrategyEvaluator initialized")
    
    async def update_market_data(self, mint: str, market_data: Dict) -> None:
        """
        Update cached market data for a specific token.
        
        Args:
            mint: Token mint address
            market_data: Latest market data from MarketData service
        """
        self.logger.debug(f"Updating market data for {mint}")
        self._market_data_cache[mint] = {
            "data": market_data,
            "timestamp": datetime.now(timezone.utc)
        }
        
        # Calculate indicators based on new data
        await self._update_indicators(mint, market_data)
    
    async def _update_indicators(self, mint: str, market_data: Dict) -> None:
        """
        Calculate and update technical indicators for a token.
        
        Args:
            mint: Token mint address
            market_data: Latest market data
        """
        try:
            # Extract price data from market data
            price_data = market_data.get("price", {})
            current_price = price_data.get("price", 0)
            
            # Get historical data if available
            historical_data = market_data.get("historical", [])
            
            # Initialize indicators dictionary for this token if it doesn't exist
            if mint not in self._indicator_values:
                self._indicator_values[mint] = {}
            
            # Calculate basic indicators if we have enough data
            if len(historical_data) >= 14:  # Minimum data points for RSI
                # Convert historical data to a format usable for indicators
                prices = [entry.get("price", 0) for entry in historical_data]
                
                # Calculate RSI if indicators service is available
                if self.indicators:
                    rsi = await self.indicators.calculate_rsi(prices)
                    self._indicator_values[mint]["rsi"] = rsi
                    
                    # Calculate MACD
                    macd, signal, histogram = await self.indicators.calculate_macd(prices)
                    self._indicator_values[mint]["macd"] = macd
                    self._indicator_values[mint]["signal"] = signal
                    self._indicator_values[mint]["histogram"] = histogram
                    
                    # Calculate moving averages
                    sma_20 = await self.indicators.calculate_sma(prices, 20)
                    sma_50 = await self.indicators.calculate_sma(prices, 50)
                    self._indicator_values[mint]["sma_20"] = sma_20
                    self._indicator_values[mint]["sma_50"] = sma_50
                    
                    self.logger.debug(f"Updated indicators for {mint}: RSI={rsi:.2f}, MACD={macd:.6f}")
                else:
                    self.logger.warning(f"Indicators service not available for {mint}")
            else:
                self.logger.debug(f"Not enough historical data for {mint} to calculate indicators")
        
        except Exception as e:
            self.logger.error(f"Error updating indicators for {mint}: {str(e)}")
            # Don't update indicators on error to avoid making decisions on bad data
    
    async def evaluate_trading_conditions(self, mint: str) -> Optional[Dict]:
        """
        Evaluate token data against strategy conditions to generate trading signals.
        
        Args:
            mint: Token mint address
            
        Returns:
            Dict containing trade signals or None if no signal
        """
        try:
            # Check if we have market data and indicators for this token
            if mint not in self._market_data_cache or mint not in self._indicator_values:
                self.logger.warning(f"No market data or indicators available for {mint}")
                return None
            
            # Get the latest market data and indicators
            market_data = self._market_data_cache[mint]["data"]
            indicators = self._indicator_values[mint]
            
            # Get current price
            current_price = market_data.get("price", {}).get("price", 0)
            if current_price <= 0:
                self.logger.warning(f"Invalid price {current_price} for {mint}")
                return None
            
            # Check if we have an active position for this token
            has_position = await self._check_active_position(mint)
            
            # Generate signals based on position status
            if has_position:
                return await self._generate_exit_signal(mint, current_price, indicators, market_data)
            else:
                return await self._generate_entry_signal(mint, current_price, indicators, market_data)
        
        except Exception as e:
            self.logger.error(f"Error evaluating trading conditions for {mint}: {str(e)}")
            return None
    
    async def _check_active_position(self, mint: str) -> bool:
        """
        Check if there's an active position for this token.
        
        Args:
            mint: Token mint address
            
        Returns:
            True if active position exists, False otherwise
        """
        # Check with OrderManager if available
        if self.order_manager and hasattr(self.order_manager, "has_active_position"):
            return await self.order_manager.has_active_position(mint)
        
        # Check with database if available
        if self.db and hasattr(self.db, "has_open_position"):
            return await self.db.has_open_position(mint)
        
        # If neither is available, assume no position
        self.logger.warning(f"Cannot determine position status for {mint}, assuming no position")
        return False
    
    async def _generate_entry_signal(self, mint: str, price: float, indicators: Dict, market_data: Dict) -> Optional[Dict]:
        """
        Generate entry (buy) signal based on current conditions.
        
        Args:
            mint: Token mint address
            price: Current token price
            indicators: Dictionary of calculated indicators
            market_data: Full market data
            
        Returns:
            Signal dictionary or None if no signal
        """
        # Default to no signal
        signal = None
        
        # Get indicators
        rsi = indicators.get("rsi")
        macd = indicators.get("macd")
        signal_line = indicators.get("signal")
        sma_20 = indicators.get("sma_20")
        sma_50 = indicators.get("sma_50")
        
        # Check if we have enough indicators to make a decision
        if rsi is None or macd is None or signal_line is None:
            self.logger.debug(f"Not enough indicator data for {mint} entry decision")
            return None
        
        # Strategy 1: RSI Oversold + MACD Crossover
        is_rsi_oversold = rsi < self._entry_conditions["rsi"]["below"]
        is_macd_crossover = macd > signal_line and indicators.get("histogram", 0) > 0
        
        # Strategy 2: Moving Average Trend
        is_uptrend = price > sma_20 > sma_50 if sma_20 and sma_50 else False
        
        # Strategy 3: Volume Analysis
        volume_24h = market_data.get("token_info", {}).get("volume_24h", 0)
        avg_volume = market_data.get("token_info", {}).get("avg_volume_24h", volume_24h / 2)
        is_volume_increasing = volume_24h > avg_volume * self._entry_conditions["volume"]["min_increase"]
        
        # Generate entry signal if conditions are met
        confidence = 0.0
        reasons = []
        
        if is_rsi_oversold:
            confidence += 0.3
            reasons.append(f"RSI oversold ({rsi:.2f})")
        
        if is_macd_crossover:
            confidence += 0.3
            reasons.append("MACD bullish crossover")
        
        if is_uptrend:
            confidence += 0.2
            reasons.append("Price above key moving averages")
        
        if is_volume_increasing:
            confidence += 0.2
            reasons.append(f"Volume increasing ({volume_24h:.2f} > {avg_volume:.2f})")
        
        # We need at least 0.5 confidence to generate a signal
        if confidence >= 0.5:
            signal = {
                "action": "BUY",
                "mint": mint,
                "price": price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": confidence,
                "reasons": reasons,
                "indicators": {
                    "rsi": rsi,
                    "macd": macd,
                    "signal_line": signal_line,
                    "volume_24h": volume_24h
                },
                "stop_loss": price * 0.95,  # 5% stop loss
                "take_profit": price * 1.15  # 15% take profit
            }
            
            self.logger.info(f"Generated BUY signal for {mint} at ${price:.6f} with {confidence:.2f} confidence")
        
        return signal
    
    async def _generate_exit_signal(self, mint: str, price: float, indicators: Dict, market_data: Dict) -> Optional[Dict]:
        """
        Generate exit (sell) signal based on current conditions.
        
        Args:
            mint: Token mint address
            price: Current token price
            indicators: Dictionary of calculated indicators
            market_data: Full market data
            
        Returns:
            Signal dictionary or None if no signal
        """
        # Default to no signal
        signal = None
        
        # Get indicators
        rsi = indicators.get("rsi")
        macd = indicators.get("macd")
        signal_line = indicators.get("signal")
        
        # Get position data if available
        position_data = await self._get_position_data(mint)
        entry_price = position_data.get("entry_price", price * 0.8)  # Default to 20% below current if unknown
        
        # Calculate profit/loss
        profit_pct = (price - entry_price) / entry_price if entry_price > 0 else 0
        
        # Strategy 1: RSI Overbought + MACD Crossunder
        is_rsi_overbought = rsi > self._exit_conditions["rsi"]["above"] if rsi else False
        is_macd_crossunder = macd < signal_line and indicators.get("histogram", 0) < 0 if macd and signal_line else False
        
        # Strategy 2: Take Profit
        take_profit_threshold = self._exit_conditions["profit"]["take_profit"]
        is_take_profit = profit_pct >= take_profit_threshold
        
        # Strategy 3: Stop Loss
        stop_loss_threshold = -0.05  # 5% loss
        is_stop_loss = profit_pct <= stop_loss_threshold
        
        # Generate exit signal if conditions are met
        confidence = 0.0
        reasons = []
        
        if is_rsi_overbought:
            confidence += 0.3
            reasons.append(f"RSI overbought ({rsi:.2f})")
        
        if is_macd_crossunder:
            confidence += 0.3
            reasons.append("MACD bearish crossunder")
        
        if is_take_profit:
            confidence += 0.4
            reasons.append(f"Take profit triggered ({profit_pct:.2%})")
        
        if is_stop_loss:
            confidence = 1.0  # Override confidence for stop loss
            reasons = [f"Stop loss triggered ({profit_pct:.2%})"]
        
        # We need at least 0.6 confidence to generate a sell signal
        if confidence >= 0.6:
            signal = {
                "action": "SELL",
                "mint": mint,
                "price": price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": confidence,
                "reasons": reasons,
                "indicators": {
                    "rsi": rsi,
                    "macd": macd,
                    "signal_line": signal_line,
                    "profit_pct": profit_pct
                },
                "entry_price": entry_price,
                "profit_pct": profit_pct
            }
            
            self.logger.info(f"Generated SELL signal for {mint} at ${price:.6f} with {confidence:.2f} confidence. Profit: {profit_pct:.2%}")
        
        return signal
    
    async def _get_position_data(self, mint: str) -> Dict:
        """
        Get data about an active position.
        
        Args:
            mint: Token mint address
            
        Returns:
            Dictionary with position data
        """
        # Check with OrderManager if available
        if self.order_manager and hasattr(self.order_manager, "get_position"):
            return await self.order_manager.get_position(mint)
        
        # Check with database if available
        if self.db and hasattr(self.db, "get_open_position"):
            return await self.db.get_open_position(mint)
        
        # If neither is available, return empty dict
        return {}
    
    async def execute_trade(self, trade_signal: Dict) -> bool:
        """
        Execute a trade based on the generated signal.
        
        Args:
            trade_signal: Trade signal dictionary
            
        Returns:
            True if trade was successfully queued, False otherwise
        """
        if not self.trade_queue:
            self.logger.error("Trade queue not available, cannot execute trade")
            return False
        
        try:
            mint = trade_signal.get("mint")
            action = trade_signal.get("action")
            price = trade_signal.get("price", 0)
            
            if not mint or not action or price <= 0:
                self.logger.error(f"Invalid trade signal: {trade_signal}")
                return False
            
            # Create trade request
            from execution.trade_queue import TradeRequest, TradePriority
            
            # Calculate trade amount (placeholder logic)
            trade_amount_usd = 10.0  # Default $10 per trade
            if hasattr(self.settings, "TRADE_AMOUNT_USD"):
                trade_amount_usd = getattr(self.settings, "TRADE_AMOUNT_USD")
            
            trade_amount_tokens = trade_amount_usd / price
            
            # Set priority based on confidence
            confidence = trade_signal.get("confidence", 0.6)
            priority = TradePriority.MEDIUM
            if confidence >= 0.8:
                priority = TradePriority.HIGH
            elif confidence < 0.5:
                priority = TradePriority.LOW
            
            # Create and enqueue trade request
            trade_request = TradeRequest(
                token_address=mint,
                amount=trade_amount_tokens,
                is_buy=(action == "BUY"),
                priority=priority,
                strategy_id="StrategyEvaluator",
                timestamp=datetime.now(timezone.utc),
                metadata={
                    "signal_details": trade_signal,
                    "token_price_at_signal": price
                }
            )
            
            success = await self.trade_queue.add_trade(trade_request)
            if success:
                self.logger.info(f"Successfully queued {action} trade for {mint} at ${price:.6f}")
                return True
            else:
                self.logger.warning(f"Failed to queue {action} trade for {mint}")
                return False
            
        except Exception as e:
            self.logger.error(f"Error executing trade: {str(e)}")
            return False

class StrategySelector:
    def __init__(self, 
                 settings: Optional[Settings] = None, 
                 thresholds: Optional[Thresholds] = None,
                 filters_config: Optional[FiltersConfig] = None,
                 db: Optional['TokenDatabase'] = None, 
                 market_data: Optional[Any] = None,
                 indicators: Optional['Indicators'] = None, 
                 price_monitor: Optional['PriceMonitor'] = None,
                 trade_queue: Optional['TradeQueue'] = None, 
                 wallet_manager: Optional[WalletManager] = None,
                 order_manager: Optional['OrderManager'] = None,
                 entry_exit_strategy: Optional['EntryExitStrategy'] = None,
                 risk_management: Optional['RiskManagement'] = None,
                 position_management: Optional['PositionManagement'] = None,
                 alert_system: Optional['AlertSystem'] = None,
                 whitelist: Optional[Whitelist] = None,
                 blacklist: Optional[Blacklist] = None):
        self.settings = settings
        self.thresholds = thresholds
        self.filters_config = filters_config
        self.db = db
        self.market_data = market_data
        self.indicators = indicators
        self.price_monitor = price_monitor
        self.trade_queue = trade_queue
        self.wallet_manager = wallet_manager
        self.order_manager = order_manager
        self.entry_exit_strategy = entry_exit_strategy
        self.risk_management = risk_management
        self.position_management = position_management
        self.alert_system = alert_system
        self.whitelist = whitelist
        self.blacklist = blacklist
        self.logger = get_logger(__name__) # Initialize logger
        
        if not self.thresholds:
            self.logger.error("StrategySelector initialized without a Thresholds instance! Behavior might be incorrect.")
            if self.filters_config is None:
                 self.logger.error("StrategySelector also missing FiltersConfig instance!")
            self.thresholds = thresholds
        else:
            self.thresholds = thresholds

        # Validate required components
        if not self.db:
            self.logger.error("TokenDatabase instance is required for StrategySelector")
        if not self.indicators:
            self.logger.error("Indicators instance is required for StrategySelector")
        if not self.price_monitor:
            self.logger.error("PriceMonitor instance is required for StrategySelector")
        if not self.trade_queue:
            self.logger.error("TradeQueue instance is required for StrategySelector")
        if not self.entry_exit_strategy:
            self.logger.error("EntryExitStrategy instance is required for StrategySelector")
        if not self.filters_config:
             self.logger.error("FiltersConfig instance is required for StrategySelector")
            
    def filter_whitelist_tokens(self, tokens):
        """
        Filter tokens based on the whitelist.
        Args:
            tokens (list): List of token data to filter.
        Returns:
            list: tokens that are in the whitelist.
        """
        if not self.filters_config or not self.filters_config.criteria:
             self.logger.error("FiltersConfig not available or criteria not loaded in filter_whitelist_tokens")
             return tokens
             
        whitelist = self.filters_config.criteria.get("whitelist", set())
        
        # Log whitelist status
        if not whitelist:
            self.logger.warning("Whitelist is empty. No tokens will pass this filter.")
        else:
            self.logger.info(f"Filtering tokens using whitelist with {len(whitelist)} entries: {list(whitelist)[:5]}")
        
        # Debug token mints
        token_mints = [token.get("mint", "NO_MINT") for token in tokens[:5]]
        self.logger.info(f"Token mints to check: {token_mints}")
        
        # Filter by whitelist
        filtered_tokens = []
        for token in tokens:
            mint = token.get("mint")
            if mint in whitelist:
                filtered_tokens.append(token)
            else:
                self.logger.debug(f"Token mint {mint} not in whitelist")
        
        self.logger.info(f"Whitelist filter: {len(tokens)} tokens → {len(filtered_tokens)} tokens passed")
        
        return filtered_tokens

    def analyze_market_conditions(self, tokens: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Analyze tokens and categorize them based on strategy criteria.
        Args:
            tokens (list): List of token data (dictionaries) to analyze.
        Returns:
            Dict[str, List[Dict]]: A dictionary mapping strategy names to lists of candidate tokens.
        """
        self.logger.info(f"Analyzing {len(tokens)} tokens for strategy conditions.")
        
        strategy_candidates = {
            'breakout': [],
            'trend_following': [],
            'mean_reversion': [],
            'default': []
        }
        
        # Ensure tokens are dictionaries before processing
        valid_tokens = [token for token in tokens if isinstance(token, dict)]

        for token in valid_tokens:
            # Add strategy indicators calculated elsewhere (e.g., TokenScanner or DataProcessing)
            # These flags determine candidacy
            is_breakout = token.get('is_breakout_candidate', False)
            is_trend = token.get('is_trend_candidate', False)
            is_reversion = token.get('is_mean_reversion_candidate', False)

            # Assign to strategies - A token might fit multiple, prioritize or handle accordingly.
            # Current logic: Assign to the first matching strategy, then default.
            assigned = False
            if is_breakout:
                strategy_candidates['breakout'].append(token)
                assigned = True
            if is_trend: # Can be both breakout and trend? Adjust logic if needed
                strategy_candidates['trend_following'].append(token)
                assigned = True
            if is_reversion:
                strategy_candidates['mean_reversion'].append(token)
                assigned = True
            
            if not assigned:
                strategy_candidates['default'].append(token)
                
        for strategy, candidates in strategy_candidates.items():
             if candidates:
                self.logger.info(f"Found {len(candidates)} candidates for '{strategy}' strategy.")

        return strategy_candidates

    async def select_and_execute(self, tokens: List[Dict]):
        """
        Analyzes tokens, generates trading signals using EntryExitStrategy,
        and enqueues valid signals into the TradeQueue.
        Args:
            tokens (list): List of token data (dictionaries) to analyze.
        """
        self.logger.info("Starting strategy selection and signal generation.")
        if not self.entry_exit_strategy:
             self.logger.error("EntryExitStrategy not available. Cannot generate signals.")
             return
        if not self.trade_queue:
             self.logger.error("TradeQueue not available. Cannot enqueue trades.")
             return

        # 1. Analyze tokens and categorize them
        strategy_candidates = self.analyze_market_conditions(tokens)

        # 2. Generate signals and enqueue TradeRequests
        trade_requests_added = 0
        for strategy_name, candidate_tokens in strategy_candidates.items():
            if not candidate_tokens:
                continue
                
            self.logger.info(f"Generating signals for {len(candidate_tokens)} candidates using '{strategy_name}' strategy.")
            
            # Use asyncio.gather for concurrent signal generation
            signal_tasks = [self.entry_exit_strategy.generate_signals(token, strategy_name) for token in candidate_tokens]
            results = await asyncio.gather(*signal_tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                token = candidate_tokens[i] # Get corresponding token
                token_address = token.get('mint') or token.get('address')
                
                if isinstance(result, Exception):
                    self.logger.error(f"Error generating signal for token {token_address} using strategy {strategy_name}: {result}")
                    continue
                
                signal: Optional[Dict] = result
                
                if signal and token_address:
                    self.logger.info(f"Generated signal for {token_address}: {signal}")
                    
                    # --- Create TradeRequest --- 
                    try:
                        # Determine trade amount (using setting as placeholder)
                        # TODO: Implement proper position sizing logic
                        trade_amount_usd = self.settings.TRADE_AMOUNT_USD or 10.0 # Default $10
                        token_price = float(token.get('priceUsd', 0)) or float(token.get('price', 0))
                        if token_price <= 0:
                             self.logger.warning(f"Cannot calculate trade amount for {token_address}: Price is zero or missing.")
                             continue
                        trade_amount_tokens = trade_amount_usd / token_price
                        
                        # Map signal confidence/strategy to priority
                        priority = TradePriority.LOW # Default
                        confidence = signal.get('confidence', 0.5)
                        if confidence >= 0.8:
                             priority = TradePriority.HIGH
                        elif confidence >= 0.6:
                             priority = TradePriority.MEDIUM
                             
                        is_buy = signal.get('action', '').upper() == 'BUY'
                        # We only handle BUY signals from scanner/selector for now
                        # Exit signals are handled separately by monitor_and_manage_positions
                        if not is_buy:
                            self.logger.debug(f"Ignoring non-BUY signal from generator for {token_address}: {signal}")
                            continue

                        trade_request = TradeRequest(
                            token_address=token_address,
                            amount=trade_amount_tokens,
                            is_buy=True, # Only creating BUY requests here
                            priority=priority,
                            strategy_id=strategy_name,
                            timestamp=datetime.now(timezone.utc),
                            metadata={
                                'signal_details': signal,
                                'token_price_at_signal': token_price
                            }
                            # callback= # Optional: Define a callback if needed
                        )
                        
                        # Enqueue the trade
                        success = await self.trade_queue.add_trade(trade_request)
                        if success:
                            trade_requests_added += 1
                            self.logger.info(f"Successfully enqueued trade request for {token_address}")
                        else:
                            self.logger.warning(f"Failed to enqueue trade request for {token_address}")
                            
                    except Exception as e:
                        self.logger.error(f"Error creating or enqueuing TradeRequest for {token_address}: {e}", exc_info=True)
                else:
                     self.logger.debug(f"No signal generated for {token_address} using strategy {strategy_name}")

        self.logger.info(f"Strategy selection and signal generation complete. Added {trade_requests_added} trade requests to the queue.")

    def run(self, tokens_df):
        """
        Entry point for the strategy selector. Runs all selected strategies.
        
        Args:
            tokens_df: DataFrame of tokens to analyze
        """
        self.logger.info("Starting strategy execution.")
        
        if not isinstance(tokens_df, pd.DataFrame):
            self.logger.warning(f"Expected DataFrame, got {type(tokens_df)}. Converting to DataFrame.")
            try:
                tokens_df = pd.DataFrame(tokens_df)
            except:
                self.logger.error("Could not convert input to DataFrame")
                return
        
        if tokens_df.empty:
            self.logger.warning("No tokens provided for strategy execution")
            return
        
        # Convert DataFrame to list for compatibility with existing code
        tokens_list = tokens_df.to_dict('records')
        self.logger.info(f"Analyzing {len(tokens_list)} tokens for strategy selection")
        
        # Run the async select_and_execute function
        # Note: If run() is called from a sync context, you need to manage the event loop.
        # Assuming run() is called from an async context or uses asyncio.run() externally.
        try:
            asyncio.run(self.select_and_execute(tokens_list))
        except RuntimeError as e:
             # Handle cases where asyncio.run() is called when a loop is already running
             if "cannot call run() while another loop is running" in str(e):
                 self.logger.warning("asyncio loop already running. Creating task for select_and_execute.")
                 # Schedule the task on the existing loop
                 asyncio.create_task(self.select_and_execute(tokens_list))
             else:
                 raise e # Re-raise other RuntimeErrors
        
        self.logger.info("Completed token analysis and signal enqueuing.")

    async def execute_trading_strategies(self):
        """
        Fetches tokens, analyzes, generates signals, and enqueues trades.
        """
        try:
            # Get tokens (example: from database whitelist)
            self.logger.info("Retrieving potential tokens from database")
            # Replace with actual token source, e.g., whitelisted or recently scanned
            # This is just an example placeholder
            tokens_to_analyze = await self.db.get_whitelisted_tokens() # Example source
            
            if not tokens_to_analyze:
                self.logger.warning("No tokens found to analyze for trading strategies")
                return

            self.logger.info(f"Loaded {len(tokens_to_analyze)} tokens for analysis")

            # Analyze, generate signals, and enqueue trades
            await self.select_and_execute(tokens_to_analyze)

        except Exception as e:
            self.logger.error(f"Error during execute_trading_strategies: {e}", exc_info=True)

    async def _analyze_token_for_strategy(self, token_data: dict) -> dict | None:
        """
        Analyzes a single whitelisted token against defined strategies.

        Current Strategy: Volume/RSI/Txn Flow
        - BUY: RSI < 30 AND 1h Buys > 1h Sells AND 24h Volume > Threshold (from config)
        - SELL: RSI > 70 AND 1h Sells > 1h Buys

        Args:
            token_data: Dictionary representing a whitelisted token from the DB.
                        Must include 'address', 'symbol', and 'filter_details'.

        Returns:
            A dictionary describing the triggered trade ('BUY' or 'SELL') and strategy details,
            or None if no strategy triggers.
        """
        address = token_data.get('address')
        symbol = token_data.get('symbol')
        filter_details_str = token_data.get('filter_details')

        if not address or not symbol or not filter_details_str:
            logger.warning(f"Skipping analysis for token - missing address, symbol, or filter_details. Data: {token_data}")
            return None

        logger.debug(f"Analyzing token {symbol} ({address}) for strategies...")

        try:
            # --- Load Data ---
            # Parse filter_details JSON
            try:
                filter_details = json.loads(filter_details_str)
            except json.JSONDecodeError:
                logger.error(f"Could not parse filter_details JSON for {symbol} ({address}). Skipping analysis.")
                return None

            # Get DexScreener data stored during scan
            dex_data = filter_details.get('dexscreener_data')
            if not dex_data:
                logger.warning(f"No dexscreener_data found in filter_details for {symbol} ({address}). Skipping analysis.")
                return None

            # Get current price (can use DB price or fetch live)
            # current_price = await self.price_monitor.get_price(address) # Option 1: Live price
            current_price = token_data.get('price') # Option 2: Price from last DB update
            if current_price is None:
                 logger.warning(f"Missing price data for {symbol} ({address}). Skipping analysis.")
                 return None

            # Get RSI (Requires Indicators module implementation)
            try:
                # Assuming get_rsi takes address and maybe timeframe (e.g., '1h')
                rsi = await self.indicators.get_rsi(address, timeframe='1h') # Needs implementation in Indicators module!
                if rsi is None:
                    logger.debug(f"Could not retrieve RSI for {symbol} ({address}). Skipping analysis.")
                    return None
            except Exception as e:
                 logger.error(f"Error getting RSI for {symbol} ({address}) from Indicators module: {e}", exc_info=True)
                 return None # Cannot proceed without RSI for this strategy

            # Get Transaction Counts and Volume from Dex data
            txns = dex_data.get('txns', {})
            h1_txns = txns.get('h1', {})
            buys_1h = h1_txns.get('buys', 0) or 0
            sells_1h = h1_txns.get('sells', 0) or 0

            volume = dex_data.get('volume', {})
            volume_24h = volume.get('h24', 0) or 0

            # --- Strategy Thresholds (Consider moving to config) ---
            rsi_oversold = 30
            rsi_overbought = 70
            min_volume_24h_for_buy = self.settings.MIN_VOLUME_FOR_TRADE # Example: Get threshold from settings

            # --- Strategy Logic ---
            strategy_name = "VolumeRsiTxnFlow"
            trade_signal = None

            # BUY Condition Check
            if rsi < rsi_oversold and buys_1h > sells_1h and volume_24h >= min_volume_24h_for_buy:
                trade_signal = 'BUY'
                confidence = 0.75 # Example confidence
                details = {
                    'condition': f'RSI ({rsi:.2f}) < {rsi_oversold} AND 1h Buys ({buys_1h}) > 1h Sells ({sells_1h}) AND Vol24h ({volume_24h:.2f}) >= {min_volume_24h_for_buy}',
                    'rsi': round(rsi, 2),
                    'buys_1h': buys_1h,
                    'sells_1h': sells_1h,
                    'volume_24h': round(volume_24h, 2)
                }
                logger.info(f"BUY Signal Triggered for {symbol} ({address}): {details['condition']}")

            # SELL Condition Check (Opposite RSI and Txn flow)
            elif rsi > rsi_overbought and sells_1h > buys_1h:
                trade_signal = 'SELL'
                confidence = 0.70 # Example confidence
                details = {
                    'condition': f'RSI ({rsi:.2f}) > {rsi_overbought} AND 1h Sells ({sells_1h}) > 1h Buys ({buys_1h})',
                    'rsi': round(rsi, 2),
                    'buys_1h': buys_1h,
                    'sells_1h': sells_1h,
                }
                logger.info(f"SELL Signal Triggered for {symbol} ({address}): {details['condition']}")

            # --- Return Trade Trigger Info ---
            if trade_signal:
                return {
                    'trade_type': trade_signal,
                    'strategy_name': strategy_name,
                    'confidence': confidence,
                    'details': details,
                    'entry_price': current_price, # Use current price as reference
                    # Optional: Define SL/TP based on strategy/price
                    'stop_loss': current_price * 0.95 if trade_signal == 'BUY' else current_price * 1.05,
                    'take_profit': current_price * 1.15 if trade_signal == 'BUY' else current_price * 0.85,
                }

            # --- No Signal ---
            logger.debug(f"No strategy signal triggered for token {symbol} ({address}). RSI: {rsi:.2f}, Buys1h: {buys_1h}, Sells1h: {sells_1h}, Vol24h: {volume_24h:.2f}")
            return None

        except Exception as e:
            logger.error(f"Error during strategy analysis for {symbol} ({address}): {e}", exc_info=True)
            return None

    async def initialize(self):
        """Initialize the StrategySelector and validate all required components."""
        try:
            if not self.entry_exit_strategy._initialized:
                self.logger.error("EntryExitStrategy not initialized")
                return False

            self.initialized = True
            return True

        except Exception as e:
            self.logger.error(f"Error initializing StrategySelector: {str(e)}")
            return False

    async def close(self):
        """Close the StrategySelector and clean up resources."""
        self.logger.info("Closing StrategySelector")
        
        # Close any open connections or resources
        if hasattr(self, 'http_client') and self.http_client:
            await self.http_client.aclose()
        
        # Close entry_exit_strategy if it has a close method
        if self.entry_exit_strategy and hasattr(self.entry_exit_strategy, 'close'):
            if asyncio.iscoroutinefunction(self.entry_exit_strategy.close):
                await self.entry_exit_strategy.close()
            else:
                self.entry_exit_strategy.close()
        
        self.logger.info("StrategySelector closed successfully")

    async def get_active_strategy_for_token(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Get the active trading strategy configuration for a specific token.
        
        Args:
            mint: Token mint address
            
        Returns:
            Dictionary containing strategy configuration or None if no strategy is active
        """
        try:
            # Get token data from database
            token = await self.db.get_token_by_mint(mint)
            if not token:
                self.logger.warning(f"Token {mint} not found in database")
                return None
            
            # Determine strategy based on token characteristics
            strategy_config = {
                "name": "EntryExitStrategy",
                "type": "momentum_based",
                "mint": mint,
                "symbol": token.symbol,
                "dex_id": token.dex_id,
                "pool_address": token.pair_address,
                "params": {
                    "rsi_oversold": 30,
                    "rsi_overbought": 70,
                    "volume_threshold": 2.0,
                    "price_change_threshold": 0.05,
                    "stop_loss_pct": 0.05,
                    "take_profit_pct": 0.10
                },
                "active": True,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            self.logger.debug(f"Active strategy for {mint}: {strategy_config['name']}")
            return strategy_config
            
        except Exception as e:
            self.logger.error(f"Error getting active strategy for token {mint}: {e}")
            return None

    async def evaluate_monitored_tokens(self, monitored_mints: List[str]):
        """ 
        Evaluates tokens currently being monitored for potential trade actions (BUY/SELL).
        This is called periodically by the main trading loop for tokens identified by the scanner 
        or those with existing open positions.
        Args:
            monitored_mints (List[str]): A list of mint addresses to evaluate.
        """
        self.logger.info(f"Starting evaluation cycle for {len(monitored_mints)} monitored tokens.")
        if not self.entry_exit_strategy:
             self.logger.error("EntryExitStrategy not available. Cannot evaluate monitored tokens.")
             return
        if not self.trade_queue:
             self.logger.error("TradeQueue not available. Cannot enqueue trades.")
             return
        if not self.db:
            self.logger.error("TokenDatabase not available. Cannot fetch token data.")
            return
        if not self.price_monitor:
            self.logger.error("PriceMonitor not available. Cannot get latest prices.")
            return
            
        trade_requests_added = 0
        evaluation_tasks = []

        # Create evaluation tasks for each monitored mint
        for mint_address in monitored_mints:
            evaluation_tasks.append(self._evaluate_single_token(mint_address))
        
        # Run evaluations concurrently
        results = await asyncio.gather(*evaluation_tasks, return_exceptions=True)
        
        # Process results (mainly for logging errors)
        for i, result in enumerate(results):
            mint_address = monitored_mints[i]
            if isinstance(result, Exception):
                self.logger.error(f"Error evaluating token {mint_address}: {result}", exc_info=False) # Avoid overly verbose logs for common errors
            elif result:
                 trade_requests_added +=1 # Count successful enqueues

        self.logger.info(f"Evaluation cycle complete. Added {trade_requests_added} trade requests to the queue.")

    async def _evaluate_single_token(self, mint_address: str) -> bool:
        """ Helper function to evaluate a single token and potentially enqueue a trade. """
        try:
            # 1. Fetch required data
            # Use a more targeted query than get_token_data if possible
            token_data = await self.db.get_token_data(mint_address) 
            if not token_data:
                self.logger.warning(f"Could not retrieve data for monitored token {mint_address}. Skipping evaluation.")
                return False
            
            # Get latest price from PriceMonitor
            latest_price_info = self.price_monitor.get_latest_price(mint_address)
            if not latest_price_info or latest_price_info.get('price') is None:
                self.logger.warning(f"Could not retrieve latest price for monitored token {mint_address}. Skipping evaluation.")
                return False
            current_price = latest_price_info['price']

            # Check for existing open position
            has_open_pos = await self.db.has_open_position(mint_address)

            # 2. Select Strategy (Placeholder: use EntryExitStrategy for all)
            # TODO: Implement more sophisticated strategy selection based on token category, market conditions etc.
            strategy_name = "default_entry_exit" # Placeholder name
            
            # 3. Generate Signal
            # Pass necessary data to the signal generator
            # The signal generator should handle both entry and exit logic based on position status
            signal: Optional[Dict] = await self.entry_exit_strategy.generate_signals(
                token_data, 
                strategy_name, 
                current_price=current_price, 
                has_open_position=has_open_pos
            )

            # 4. Process Signal and Enqueue Trade if needed
            if signal:
                action = signal.get('action', '').upper()
                self.logger.info(f"Generated signal for {mint_address}: {signal}")
                
                if action in ['BUY', 'SELL']:
                    # TODO: Implement proper position sizing based on risk, capital, etc.
                    # Placeholder: Use fixed USD amount or percentage of portfolio
                    trade_amount_usd = self.settings.TRADE_AMOUNT_USD or 10.0 # Default $10
                    if current_price <= 0:
                         self.logger.warning(f"Cannot calculate trade amount for {mint_address}: Price is zero.")
                         return False
                    trade_amount_tokens = trade_amount_usd / current_price
                    
                    # Adjust amount based on whether it's buy or sell and existing position
                    # If SELL, amount should likely be the entire position size. Needs position data.
                    if action == 'SELL' and not has_open_pos:
                        self.logger.warning(f"SELL signal received for {mint_address}, but no open position found in DB. Ignoring signal.")
                        return False
                    # Add logic here to fetch position size if selling the whole position
                    
                    priority = TradePriority.MEDIUM # Default priority for monitored evaluations
                    confidence = signal.get('confidence', 0.6)
                    if confidence >= 0.8:
                        priority = TradePriority.HIGH
                    elif confidence < 0.5:
                        priority = TradePriority.LOW

                    trade_request = TradeRequest(
                        token_address=mint_address,
                        amount=trade_amount_tokens,
                        is_buy=(action == 'BUY'),
                        priority=priority,
                        strategy_id=strategy_name,
                        timestamp=datetime.now(timezone.utc),
                        metadata={
                            'signal_details': signal,
                            'token_price_at_signal': current_price,
                            'evaluation_type': 'monitoring'
                        }
                    )
                    
                    # Enqueue the trade
                    success = await self.trade_queue.add_trade(trade_request)
                    if success:
                        self.logger.info(f"Successfully enqueued {action} request for {mint_address}")
                        return True # Indicate a trade was enqueued
                    else:
                        self.logger.warning(f"Failed to enqueue {action} request for {mint_address}")
                        return False
                else:
                    self.logger.debug(f"Signal generated for {mint_address} is not BUY/SELL ({action}). No trade action taken.")
            else:
                self.logger.debug(f"No actionable signal generated for {mint_address} during monitoring evaluation.")
                
        except Exception as e:
            self.logger.error(f"Error during evaluation of single token {mint_address}: {e}", exc_info=True)
            # Re-raise the exception so asyncio.gather captures it
            raise e 
        
        return False # Indicate no trade was enqueued