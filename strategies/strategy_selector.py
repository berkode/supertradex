import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

from config import Settings, FiltersConfig, Thresholds
from utils import logger as logger_utils
from strategies.entry_exit import EntryExitStrategy

logger = logger_utils.get_logger("StrategySelector")


class StrategySelector:
    def __init__(self):
        self.entry_exit = EntryExitStrategy()
        self.executor = ThreadPoolExecutor(max_workers=5)  # Async concurrency setup
        self.settings = Settings()
        self.filters = FiltersConfig()
        self.thresholds = Thresholds()

    def filter_whitelist_coins(self, coins):
        """
        Filter coins based on the whitelist.
        Args:
            coins (list): List of coin data to filter.
        Returns:
            list: Coins that are in the whitelist.
        """
        whitelist = self.filters.criteria["whitelist"]
        filtered_coins = [coin for coin in coins if coin["symbol"] in whitelist]
        logger.info(f"Filtered {len(filtered_coins)} coins from whitelist.")
        return filtered_coins

    def analyze_market_conditions(self, coins):
        """
        Analyze market conditions to determine which strategies to execute.
        Args:
            coins (list): List of coin data to analyze.
        Returns:
            list: A prioritized list of strategies to execute.
        """
        logger.info("Analyzing market conditions for strategy selection.")
        whitelist_coins = self.filter_whitelist_coins(coins)

        strategies = []

        # Breakout strategy: Look for breakout conditions
        breakout_candidates = [
            coin for coin in whitelist_coins
            if coin["price"] > coin["high"] * self.thresholds.BREAKOUT_THRESHOLD
            and coin["volume"] > coin["avg_volume"] * self.thresholds.VOLUME_SPIKE_THRESHOLD
        ]
        if breakout_candidates:
            logger.info(f"{len(breakout_candidates)} coins identified for breakout strategy.")
            strategies.append((self.entry_exit.breakout, breakout_candidates))

        # Trend-following strategy: Identify strong trends
        trend_candidates = [
            coin for coin in whitelist_coins
            if self.thresholds.MIN_TREND_RSI < coin["rsi"] < self.thresholds.MAX_TREND_RSI
            and coin["adx"] > self.thresholds.MIN_TREND_STRENGTH
        ]
        if trend_candidates:
            logger.info(f"{len(trend_candidates)} coins identified for trend-following strategy.")
            strategies.append((self.entry_exit.trend_following, trend_candidates))

        # Mean reversion strategy: Identify overbought/oversold conditions
        mean_reversion_candidates = [
            coin for coin in whitelist_coins
            if coin["price"] < coin["bollinger_lower"] or coin["price"] > coin["bollinger_upper"]
        ]
        if mean_reversion_candidates:
            logger.info(f"{len(mean_reversion_candidates)} coins identified for mean reversion strategy.")
            strategies.append((self.entry_exit.mean_reversion, mean_reversion_candidates))

        # Sniping strategy: Target ultra-new meme coins
        if self.settings.ENABLE_SNIPING:
            strategies.append((self.entry_exit.sniping_new_meme_coins, []))

        # Copy-trading strategy: Mirror trades from profitable wallets
        if self.settings.ENABLE_COPY_TRADING:
            strategies.append((self.entry_exit.copy_trading, []))

        # Default strategy: Buying near untouched support
        if not strategies:
            logger.info("No specific strategy conditions met. Defaulting to untouched support strategy.")
            strategies.append((self.entry_exit.buying_on_untouched_support, whitelist_coins))

        logger.info(f"Strategies selected for execution: {[s[0].__name__ for s in strategies]}")
        return strategies

    async def execute_strategy_async(self, strategy_func, coins):
        """
        Execute a single strategy asynchronously.
        Args:
            strategy_func (callable): The strategy function to execute.
            coins (list): The list of coins to process.
        """
        try:
            await asyncio.to_thread(strategy_func, coins)
            logger.info(f"Successfully executed strategy: {strategy_func.__name__}")
        except Exception as e:
            logger.error(f"Error executing strategy {strategy_func.__name__}: {e}")

    async def execute_strategies(self, coins):
        """
        Dynamically execute strategies based on market conditions.
        Args:
            coins (list): List of coin data to analyze and execute strategies on.
        """
        logger.info("Starting strategy execution based on market conditions.")

        # Analyze market conditions and select strategies
        strategies = self.analyze_market_conditions(coins)

        # Execute selected strategies asynchronously
        tasks = [self.execute_strategy_async(strategy[0], strategy[1]) for strategy in strategies]
        await asyncio.gather(*tasks)

        logger.info("All selected strategies have been executed.")

    def run(self, coins):
        """
        Entry point for the strategy selector. Runs all selected strategies synchronously.
        Args:
            coins (list): List of coin data to analyze and execute strategies on.
        """
        logger.info("Starting synchronous strategy execution.")
        strategies = self.analyze_market_conditions(coins)

        for strategy_func, strategy_coins in strategies:
            try:
                logger.info(f"Executing strategy: {strategy_func.__name__}")
                strategy_func(strategy_coins)
            except Exception as e:
                logger.error(f"Error executing strategy {strategy_func.__name__}: {e}")

        logger.info("Completed all selected strategy executions.")


