import logging
from typing import Dict, Any, Optional, TYPE_CHECKING
import asyncio
from datetime import datetime, timezone

from config import Settings, Thresholds
from data.market_data import MarketData
from data.token_database import TokenDatabase
from strategies.strategy_selector import StrategySelector
from data.indicators import Indicators
from execution.trade_queue import TradeQueue
from execution.order_manager import OrderManager
from utils.logger import get_logger
from .entry_exit import EntryExitStrategy

if TYPE_CHECKING:
    from execution.trade_executor import TradeExecutor
    from wallet.wallet_manager import WalletManager

logger = get_logger(__name__)

class StrategyEvaluator:
    """
    Evaluates trading strategies based on market data and selected strategy logic.
    """
    def __init__(
        self,
        market_data: MarketData,
        db: TokenDatabase,
        settings: Settings,
        thresholds: Thresholds,
        trade_executor: 'TradeExecutor',
        wallet_manager: 'WalletManager',
        indicators: Optional[Indicators] = None,
        trade_queue: Optional[TradeQueue] = None,
        order_manager: Optional[OrderManager] = None,
        entry_exit_strategy: Optional['EntryExitStrategy'] = None,
        strategy_selector: Optional['StrategySelector'] = None
    ):
        """
        Initializes the StrategyEvaluator.

        Args:
            market_data: Instance of MarketData to get market information.
            db: Instance of TokenDatabase for accessing token data.
            settings: Application settings.
            thresholds: Configured thresholds.
            trade_executor: Instance of TradeExecutor for executing trades.
            wallet_manager: Instance of WalletManager for managing wallets.
            indicators: Optional Indicators instance.
            trade_queue: Optional TradeQueue instance.
            order_manager: Optional OrderManager instance.
            entry_exit_strategy: Optional EntryExitStrategy instance.
            strategy_selector: Optional StrategySelector instance.
        """
        self.logger = get_logger(__name__)
        self.market_data = market_data
        self.db = db
        self.settings = settings
        self.thresholds = thresholds
        self.trade_executor = trade_executor
        self.wallet_manager = wallet_manager
        self.indicators = indicators
        self.trade_queue = trade_queue
        self.order_manager = order_manager
        self.entry_exit_strategy = entry_exit_strategy
        self.strategy_selector = strategy_selector
        self.current_market_data: Dict[str, Any] = {} # Stores latest market data per mint
        self.current_evaluating_mint: Optional[str] = None
        self.current_pool_address: Optional[str] = None
        self.current_dex_id: Optional[str] = None
        self._is_active = False

        # Subscribe to market data updates
        if self.market_data:
            self.market_data.subscribe('realtime_price_update', self.handle_price_update)
            logger.info("StrategyEvaluator subscribed to realtime_price_update from MarketData.")
        else:
            logger.error("MarketData instance not provided to StrategyEvaluator. Cannot subscribe to price updates.")

        logger.info("StrategyEvaluator initialized.")

    async def update_market_data(self, mint: str, market_data_dict: Dict[str, Any]):
        """
        Updates the evaluator with the latest market data for a specific mint.
        """
        self.current_market_data[mint] = market_data_dict
        logger.debug(f"Market data updated for mint {mint}: {market_data_dict}")

    async def evaluate_trading_conditions(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Evaluates whether to enter or exit a position for a given mint
        based on the currently selected strategy and market conditions.

        Args:
            mint: The token mint address to evaluate.

        Returns:
            A dictionary with trading signals (e.g., {'action': 'buy', 'price': 10.5, 'confidence': 0.8})
            or None if no action is advised.
        """
        if not mint:
            logger.warning("Mint address is required for evaluation.")
            return None

        current_strategy_config = await self.strategy_selector.get_active_strategy_for_token(mint)
        if not current_strategy_config:
            logger.warning(f"No active strategy found for mint {mint}. Cannot evaluate.")
            return None

        market_data_for_mint = self.current_market_data.get(mint)
        if not market_data_for_mint:
            logger.warning(f"No market data available for mint {mint} in StrategyEvaluator. Fetching...")
            # Attempt to fetch if not present, though ideally it's pushed by manage_top_token_trading
            market_data_for_mint = await self.market_data.get_market_data(mint)
            if market_data_for_mint:
                await self.update_market_data(mint, market_data_for_mint)
            else:
                logger.error(f"Failed to fetch market data for mint {mint}. Evaluation aborted.")
                return None
        
        logger.info(f"Evaluating trading conditions for mint {mint} using strategy: {current_strategy_config.get('name', 'N/A')}")
        logger.debug(f"Market data for {mint}: {market_data_for_mint}")

        # This is where the core logic of applying the selected strategy will go.
        # For now, it's a placeholder.
        # Example:
        #   if current_strategy_config['name'] == 'SimpleThresholdStrategy':
        #       return await self._evaluate_simple_threshold(mint, market_data_for_mint, current_strategy_config['params'])

        # Placeholder: For now, let's assume the strategy selector provides direct actionable signals
        # In a real scenario, this would involve more complex logic based on strategy_type
        # from current_strategy_config and market_data_for_mint.
        
        # The EntryExitStrategy is now a primary component of StrategySelector
        # We can call its methods via strategy_selector if needed, or delegate to it.
        
        # Let's assume StrategySelector's get_active_strategy_for_token now might return
        # an object or a configuration that StrategyEvaluator can use directly with EntryExitStrategy
        # or other strategy execution modules.

        # Direct call to EntryExitStrategy through StrategySelector might look like:
        trade_action = await self.strategy_selector.entry_exit_strategy.get_signal_on_price_event(
            event_data={
                'mint': mint,
                'price': market_data_for_mint.get('price'),
                'timestamp': datetime.now(timezone.utc)
            },
            pool_address=None,  # Could be passed from market_data_for_mint if available
            dex_id=None  # Could be passed from market_data_for_mint if available
        )

        if trade_action:
            logger.info(f"Trade action for {mint} from EntryExitStrategy: {trade_action}")
            # trade_action should be a dict like {'action': 'buy'/'sell'/'hold', 'price': ..., 'reason': ...}
            return trade_action
        else:
            logger.debug(f"No trade action advised for {mint} by EntryExitStrategy.")
            return None

    async def _evaluate_simple_threshold(self, mint: str, market_data: Dict[str, Any], params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Example of a specific strategy evaluation logic.
        """
        price = market_data.get('price')
        buy_threshold = params.get('buy_price')
        sell_threshold = params.get('sell_price')

        if not price:
            logger.warning(f"No price data for {mint} in _evaluate_simple_threshold.")
            return None

        if buy_threshold and price <= buy_threshold:
            return {'action': 'buy', 'price': price, 'reason': f'Price {price} <= buy threshold {buy_threshold}'}
        
        if sell_threshold and price >= sell_threshold:
            return {'action': 'sell', 'price': price, 'reason': f'Price {price} >= sell threshold {sell_threshold}'}
            
        return None

    async def select_and_evaluate_for_token(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Combines strategy selection and evaluation for a single token.
        This might be called by an external process managing multiple tokens.
        """
        logger.info(f"Selecting and evaluating strategy for mint: {mint}")
        
        # 1. Select Strategy (or confirm active one)
        # The StrategySelector is responsible for determining the best strategy.
        # This might involve re-evaluating if conditions changed significantly.
        # For now, assume get_active_strategy_for_token is sufficient.
        active_strategy = await self.strategy_selector.get_active_strategy_for_token(mint)
        if not active_strategy:
            logger.warning(f"No active strategy could be determined for {mint}. Cannot evaluate.")
            return None
        
        logger.info(f"Active strategy for {mint}: {active_strategy.get('name', 'Unknown Strategy')}")

        # 2. Evaluate Trading Conditions using the selected strategy
        trade_signal = await self.evaluate_trading_conditions(mint)

        if trade_signal:
            logger.info(f"Generated trade signal for {mint}: {trade_signal}")
        else:
            logger.info(f"No trade signal generated for {mint} after evaluation.")
            
        return trade_signal 

    async def initialize_strategies(self):
        """Initializes the underlying strategies, e.g., EntryExitStrategy."""
        # EntryExitStrategy's initialize method might expect more components.
        # We need to ensure it's compatible with what StrategyEvaluator provides.
        # For now, let's assume a simplified or adapted initialize for EntryExitStrategy
        # or that its core logic doesn't strictly need all original components when used by StrategyEvaluator.
        
        # Looking at EntryExitStrategy's __init__ and initialize, it expects trade_queue, order_manager etc.
        # This implies EES is designed to be more independent.
        # We might need to refactor EES or how SE uses it.
        
        # For now, let's assume EES can operate in a 'signal generation mode'
        # or its initialize can handle None for some params if SE is the caller.
        # Awaiting EntryExitStrategy.initialize() if it's an async function
        if hasattr(self.entry_exit_strategy, 'initialize') and asyncio.iscoroutinefunction(self.entry_exit_strategy.initialize):
            # We need to pass the components EES expects for initialization if any.
            # This is a placeholder, EES might need specific instances for order_manager etc.
            # If SE is handling execution, these might be simplified or mocked if EES must have them.
            initialized = await self.entry_exit_strategy.initialize(
                order_manager=self.order_manager, # Pass the actual order_manager
                transaction_tracker=None, # Placeholder
                balance_checker=None, # Placeholder
                trade_validator=None # Placeholder
            )
            if initialized:
                logger.info("EntryExitStrategy initialized successfully via StrategyEvaluator.")
            else:
                logger.error("Failed to initialize EntryExitStrategy via StrategyEvaluator.")
        else:
            logger.info("EntryExitStrategy does not have an async initialize method or it's not suitable for this call.")

    def start_evaluating_token(self, mint: str, pool_address: str, dex_id: str):
        if not mint or not pool_address or not dex_id:
            logger.error(f"Cannot start evaluating token: mint, pool_address, or dex_id is missing. Mint: {mint}, Pool: {pool_address}, Dex: {dex_id}")
            return

        logger.info(f"StrategyEvaluator starting evaluation for token: {mint} on pool {pool_address} (DEX: {dex_id})")
        self.current_evaluating_mint = mint
        self.current_pool_address = pool_address
        self.current_dex_id = dex_id
        self._is_active = True
        
        if hasattr(self.entry_exit_strategy, 'set_active_mint'):
             self.entry_exit_strategy.set_active_mint(mint)
        elif hasattr(self.entry_exit_strategy, 'reset_state_for_token'): # Fallback
            self.entry_exit_strategy.reset_state_for_token(mint)
        else:
            logger.warning("EntryExitStrategy does not have set_active_mint or reset_state_for_token method.")

    def stop_evaluating_token(self):
        logger.info(f"StrategyEvaluator stopping evaluation for token: {self.current_evaluating_mint}")
        prev_mint = self.current_evaluating_mint
        self.current_evaluating_mint = None
        self.current_pool_address = None
        self.current_dex_id = None
        self._is_active = False
        if hasattr(self.entry_exit_strategy, 'clear_active_mint'): 
            self.entry_exit_strategy.clear_active_mint(prev_mint) # Pass prev_mint if method expects it
        elif hasattr(self.entry_exit_strategy, 'reset_state_for_token'): # Fallback, less specific
             self.entry_exit_strategy.reset_state_for_token(None) # Or prev_mint

    async def handle_price_update(self, event_data: Dict):
        """
        Callback for real-time price updates from MarketData.
        event_data is expected to be: {'mint': str, 'price': float, 'source': str, 'timestamp': datetime}
        """
        if not self._is_active or not self.current_evaluating_mint:
            return

        mint = event_data.get('mint')
        price = event_data.get('price')
        timestamp = event_data.get('timestamp')

        if mint != self.current_evaluating_mint:
            return # Not the token we are currently evaluating

        if price is None or timestamp is None:
            logger.warning(f"Received price update for {mint} with missing price or timestamp. Data: {event_data}")
            return

        logger.debug(f"StrategyEvaluator received price update for {mint}: Price={price} at {timestamp}")

        # Pass data to EntryExitStrategy to get a signal
        # The EntryExitStrategy.handle_realtime_price_update method is async
        # and seems to be designed to be the direct subscriber and then act.
        # If we call it directly, it might try to enqueue trades itself.
        # We need EntryExitStrategy to RETURN a signal.
        
        # Let's assume/create a method in EES like `get_signal_for_price_update`
        # For now, we will adapt by calling its existing `handle_realtime_price_update`
        # but we need to ensure it doesn't execute trades directly and instead returns a signal.
        # This will likely require modification of EntryExitStrategy.

        # --- Refined approach: EES should have a method that takes price data and returns a signal ---
        # e.g., signal = await self.entry_exit_strategy.evaluate_price_event(event_data, self.current_pool_address, self.current_dex_id)
        
        # For now, we stick to the design that EES itself subscribes.
        # StrategyEvaluator's role is to set the context (active token) for EES,
        # and EES, upon generating a signal for that active token, will call back to SE or TradeExecutor.

        # The current EntryExitStrategy subscribes itself and uses a trade_queue.
        # This means StrategyEvaluator might be redundant for price handling if EES does it all.
        # OR, StrategyEvaluator tells EES which token to focus on, and EES uses its own subscription.
        # EES then needs to send signals to TradeExecutor via StrategyEvaluator.

        # Let's assume EES is modified to have a signal_callback.
        # StrategyEvaluator sets this callback during EES initialization.
        # self.entry_exit_strategy.register_signal_callback(self.process_trade_signal)

        # If EES `handle_realtime_price_update` directly calls `self.trade_queue.put(...)`,
        # we need to intercept that.
        # The simplest modification to EES for now:
        # 1. Add `set_active_mint(self, mint)` to EES.
        # 2. In EES.handle_realtime_price_update, check `if event_data['mint'] == self.active_mint`.
        # 3. EES needs a way to output its decision. Let's assume it returns a signal.
        #    If EES is modified to return a signal, then SE's subscription to MD makes sense.

        # If EES is not modified yet to return a signal, this `handle_price_update` in SE
        # might not be able to get a signal directly from EES.
        # The original EES uses a `trade_queue`.
        
        # For the purpose of this step, let's assume `StrategyEvaluator` is the primary subscriber.
        # It will call a method on `EntryExitStrategy` that is adapted to return a signal
        # rather than queueing a trade. This is a pending change for `EntryExitStrategy`.

        if hasattr(self.entry_exit_strategy, 'get_signal_on_price_event'):
            signal_decision = await self.entry_exit_strategy.get_signal_on_price_event(
                event_data, 
                current_pool_address=self.current_pool_address,
                current_dex_id=self.current_dex_id
            )
            if signal_decision:
                await self.process_trade_signal(signal_decision)
        else:
            # This branch means EntryExitStrategy is not yet adapted.
            # For now, log this. Later, EntryExitStrategy will be modified.
            logger.debug(f"EntryExitStrategy needs 'get_signal_on_price_event' method for StrategyEvaluator to process signals.")
            # In this case, EES would be handling signals via its own subscription if it's active.
            # This can lead to double processing if EES also subscribed.
            # It's cleaner if EES does *not* subscribe itself when managed by SE.
            # SE should be the sole subscriber for the token it manages.
            pass

    async def process_trade_signal(self, signal: Dict):
        """
        Processes a trade signal received from the EntryExitStrategy.
        Signal format: {'mint': str, 'action': 'BUY'/'SELL', 'price': float, 'quantity': float, 
                        'confidence': float, 'reason': str, 'order_type': 'LIMIT'/'MARKET', etc.}
        """
        if not self.trade_executor:
            logger.error("TradeExecutor not available. Cannot process trade signal.")
            return

        mint_signal = signal.get('mint')
        action = signal.get('action') # BUY or SELL
        
        if mint_signal != self.current_evaluating_mint:
            logger.warning(f"Received signal for {mint_signal} but currently evaluating {self.current_evaluating_mint}. Signal ignored.")
            return

        logger.info(f"StrategyEvaluator received trade signal: {action} {mint_signal} at price {signal.get('price')}. Reason: {signal.get('reason')}")

        # Here, we would convert the signal into a trade order and send it to TradeExecutor
        # This might involve fetching current wallet balances, position sizes, etc.
        # For now, a direct pass-through, assuming signal contains enough info or TE handles it.

        try:
            # Example: Constructing an order
            # This needs to align with what TradeExecutor.execute_trade expects.
            # The signal from EES needs to be rich enough.
            order_details = {
                "mint": mint_signal,
                "pool_address": self.current_pool_address, 
                "dex_id": self.current_dex_id,             
                "action": action, 
                "order_type": signal.get('order_type', 'MARKET'), 
                "amount_usd": signal.get('amount_usd'), 
                "slippage_bps": signal.get('slippage_bps', self.settings.DEFAULT_SLIPPAGE_BPS if hasattr(self.settings, 'DEFAULT_SLIPPAGE_BPS') else 50),
                "price": signal.get('price'), 
                "base_token_amount": signal.get('base_token_amount'), 
                "quote_token_amount": signal.get('quote_token_amount'), 
                "signal_details": signal 
            }
            
            # Ensure either amount_usd or base_token_amount is provided for the trade
            if not order_details["amount_usd"] and not order_details["base_token_amount"]:
                 logger.error(f"Trade signal for {mint_signal} missing trade amount (amount_usd or base_token_amount). Signal: {signal}")
                 return

            # TradeExecutor should handle the logic of buy/sell based on action
            trade_result = await self.trade_executor.execute_trade_from_signal(order_details)

            if trade_result and trade_result.get("success"):
                logger.info(f"Trade signal for {mint_signal} ({action}) executed successfully. Tx: {trade_result.get('transaction_id')}")
            else:
                logger.error(f"Trade signal for {mint_signal} ({action}) failed execution. Result: {trade_result}")

        except Exception as e:
            logger.error(f"Error processing trade signal for {mint_signal} in StrategyEvaluator: {e}", exc_info=True)

    async def close(self):
        logger.info("Closing StrategyEvaluator.")
        if self.market_data and hasattr(self.market_data, 'unsubscribe'):
            self.market_data.unsubscribe('realtime_price_update', self.handle_price_update)
            logger.info("StrategyEvaluator unsubscribed from MarketData price updates.")
        if hasattr(self.entry_exit_strategy, 'close') and asyncio.iscoroutinefunction(self.entry_exit_strategy.close):
            await self.entry_exit_strategy.close()
        self._is_active = False
        self.current_evaluating_mint = None

    async def run_evaluations(self, shutdown_event: asyncio.Event):
        """
        Runs periodic strategy evaluations for the currently active token.
        This method runs in a background task and evaluates trading conditions
        at regular intervals for the token being monitored.
        """
        logger.info("🎯 StrategyEvaluator periodic evaluation task started")
        
        # Evaluation interval from settings (default 30 seconds)
        evaluation_interval = getattr(self.settings, 'STRATEGY_EVALUATION_INTERVAL', 30)
        
        while not shutdown_event.is_set():
            try:
                # Only evaluate if we have an active token
                if self._is_active and self.current_evaluating_mint:
                    logger.debug(f"🔍 Evaluating strategy for active token: {self.current_evaluating_mint}")
                    
                    # Perform strategy evaluation
                    trade_signal = await self.evaluate_trading_conditions(self.current_evaluating_mint)
                    
                    if trade_signal:
                        logger.info(f"📊 Strategy evaluation generated signal for {self.current_evaluating_mint}: {trade_signal}")
                        await self.process_trade_signal(trade_signal)
                    else:
                        logger.debug(f"📊 Strategy evaluation for {self.current_evaluating_mint}: No action recommended")
                
                else:
                    logger.debug("🔍 StrategyEvaluator: No active token to evaluate")
                
                # Wait for next evaluation cycle
                await asyncio.sleep(evaluation_interval)
                
            except asyncio.CancelledError:
                logger.info("🛑 StrategyEvaluator periodic evaluation task cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in StrategyEvaluator periodic evaluation: {e}", exc_info=True)
                # Continue after error with a short delay
                await asyncio.sleep(5)
        
        logger.info("✅ StrategyEvaluator periodic evaluation task completed") 