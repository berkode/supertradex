import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from data import indicators, analytics, blockchain_listener, filtering, token_metrics, Indicators
from execution import rug_checker, slippage_checker, transaction_tracker
from filters import whitelist, blacklist, volume_filter
from wallet import balance_checker, trade_validator
from utils import helpers, logger as logger_utils, exception_handler
from config import Settings, FiltersConfig, Thresholds

logger = logger_utils.get_logger("EntryExitStrategy")

class EntryExitStrategy:
    def __init__(self):
        self.watchlists = {
            "support": set(),
            "sniping": set(),
            "copy_trading": set(),
            "trend_following": set(),
            "breakout": set(),
            "mean_reversion": set(),
        }
        self.indicators = indicators.Indicators()
        self.whitelist = whitelist.Whitelist()
        self.blacklist = blacklist.Blacklist()
        self.balance_checker = balance_checker.BalanceChecker()
        self.volume_filter = volume_filter.VolumeFilter()

        self.executor = ThreadPoolExecutor(max_workers=10)  # Concurrency setup


    @exception_handler.ExceptionHandler
    def buying_on_untouched_support(self, coins):
        """
        Entry and exit logic for untouched support strategy.
        Integrates risk management, filters, and thresholds for real-world trading.
        """

        filters = FiltersConfig()
        settings = Settings()
        thresholds = Thresholds()

        def process_coin(coin):
            symbol = coin["symbol"]

            # Step 1: Validate token using whitelist and filters
            if not filters.validate_token(coin):
                logger.debug(f"{symbol}: Failed validation. Skipping.")
                return

            # Step 2: Validate thresholds (e.g., liquidity, price, holders)
            if not (thresholds.MIN_LIQUIDITY <= coin["liquidity"] <= thresholds.MAX_LIQUIDITY):
                logger.debug(f"{symbol}: Liquidity {coin['liquidity']} out of range. Skipping.")
                return
            if not (thresholds.MIN_PRICE <= coin["price"] <= thresholds.MAX_PRICE):
                logger.debug(f"{symbol}: Price {coin['price']} out of range. Skipping.")
                return

            # Step 3: Check token for rug pull
            if rug_checker.is_rug_pull(coin):
                logger.warning(f"{symbol}: Identified as a potential rug pull. Skipping.")
                return

            # Step 4: Analyze support and resistance levels
            support_data = analytics.detect_support_resistance(coin)
            if not support_data["is_support"] or support_data["is_tested"]:
                logger.debug(f"{symbol}: No valid untouched support. Skipping.")
                return

            # Step 5: Confirm entry conditions
            near_support = abs(coin["price"] - support_data["support_level"]) <= (
                0.02 * support_data["support_level"]
            )  # Price within 2% of support
            has_buying_volume = coin["volume"] > support_data["avg_volume"]  # Confirm volume spike
            bullish_signal = self.indicators.rsi(coin) < 30  # RSI below 30 indicates oversold conditions

            if self._validate_entry(symbol, "support", near_support and has_buying_volume and bullish_signal):
                # Add to watchlist if entry conditions are met
                self.watchlists["support"].add(symbol)
                logger.info(f"Entering {symbol} near untouched support at ${coin['price']}.")

                # Step 6: Execute the trade
                trade_details = {
                    "symbol": symbol,
                    "price": coin["price"],
                    "quantity": settings.TRADE_SIZE / coin["price"],  # Calculate quantity based on trade size
                }
                transaction_tracker.execute_trade(trade_details)

                # Step 7: Set stop-loss and take-profit levels
                stop_loss = max(support_data["support_level"] * 0.98, coin["price"] * (1 + settings.MAX_LOSS))
                target_price = coin["price"] * (1 + settings.GAIN_MIN_TARGET)
                logger.info(f"Set stop-loss for {symbol}: ${stop_loss}, take-profit: ${target_price}.")

                # Step 8: Monitor exit conditions
                exit_signal = coin["price"] <= stop_loss or coin["price"] >= target_price

                if self._validate_exit(symbol, exit_signal):
                    if coin["price"] <= stop_loss:
                        logger.warning(f"Exiting {symbol}: Price broke support at ${coin['price']}.")
                    elif coin["price"] >= target_price:
                        logger.info(f"Exiting {symbol}: Target profit reached at ${coin['price']}.")

        # Step 9: Process all coins concurrently
        self._process_coins_with_concurrency(coins, process_coin)

    @exception_handler.ExceptionHandler
    def sniping_new_meme_coins(self):
        """
        Entry and exit logic for sniping newly created meme coins within the last 1–3 minutes.
        Strategy Overview:
            - Fetch ultra-new coins from the blockchain (released in the last 1–3 minutes).
            - Validate using filters, thresholds, and rug pull checks.
            - Dynamically calculate position size and optimize for gas fees and SOL balance.
            - Execute trades immediately with pre-set stop-loss and take-profit.
            - Monitor and exit trades based on defined conditions.
        """

        filters = FiltersConfig()
        settings = Settings()
        thresholds = Thresholds()

        # Step 1: Fetch newly created meme coins (last 1–3 minutes only)
        new_coins = [
            coin for coin in helpers.retry_request(blockchain_listener.get_new_meme_coins)
            if coin["age_in_seconds"] <= 180  # Coins launched in the last 3 minutes
        ]
        if not new_coins:
            logger.info("No new coins detected within the last 3 minutes.")
            return

        def process_coin(coin):
            symbol = coin["symbol"]

            # Step 2: Validate token using filters and thresholds
            if not filters.validate_token(coin):
                logger.debug(f"{symbol}: Failed validation. Skipping.")
                return

            # Validate liquidity
            if not (thresholds.MIN_LIQUIDITY <= coin["liquidity"] <= thresholds.MAX_LIQUIDITY):
                logger.debug(f"{symbol}: Liquidity {coin['liquidity']} out of range. Skipping.")
                return

            # Step 3: Check for rug pull
            rug_pull_score = rug_checker.calculate_rug_pull_score(coin)
            if rug_pull_score > filters.criteria["rug_pull_threshold"]:  # Example threshold for rug pull score
                logger.warning(f"{symbol}: High rug pull risk (score: {rug_pull_score}). Skipping.")
                return

            # Step 4: Validate gas fees and SOL balance
            gas_fee = self.gas_manager.estimate_gas_fee(coin, priority_fee=True)
            if gas_fee > thresholds.MAX_GAS_FEE:
                logger.warning(f"{symbol}: Gas fee ${gas_fee} exceeds maximum allowed. Skipping.")
                return

            available_sol = self.balance_checker.get_available_balance()
            if available_sol < gas_fee:
                logger.warning(f"{symbol}: Insufficient SOL balance (${available_sol}) for gas fee (${gas_fee}). Skipping.")
                return

            # Step 5: Calculate position size and execute the trade
            account_balance = self.balance_checker.get_available_balance()
            risk_amount = account_balance * settings.RISK_PER_TRADE  # Risk per trade
            stop_loss_distance = abs(coin["price"] * settings.MAX_LOSS)
            position_size = min(risk_amount / stop_loss_distance, settings.TRADE_SIZE / coin["price"])

            if position_size <= 0:
                logger.warning(f"{symbol}: Invalid position size calculated. Skipping.")
                return

            trade_details = {
                "symbol": symbol,
                "price": coin["price"],
                "quantity": position_size,
                "gas_fee": gas_fee,
                "priority_fee": True,  # Enable priority fee for faster execution
            }

            try:
                transaction_tracker.execute_trade(trade_details)
                logger.info(f"Sniping trade executed for {symbol}: {trade_details}")
            except Exception as e:
                logger.error(f"Failed to execute sniping trade for {symbol}: {e}")
                return

            # Step 6: Set stop-loss and take-profit levels
            stop_loss = coin["price"] * (1 + settings.MAX_LOSS)  # Stop-loss percentage
            target_price = coin["price"] * (1 + settings.GAIN_MIN_TARGET)  # Take-profit percentage
            logger.info(f"Set stop-loss for {symbol}: ${stop_loss}, take-profit: ${target_price}.")

            # Step 7: Monitor exit conditions
            exit_signal = (
                coin["price"] <= stop_loss
                or coin["price"] >= target_price
                or not coin.get("volume_growth", True)
            )

            if self._validate_exit(symbol, exit_signal):
                if coin["price"] <= stop_loss:
                    logger.warning(f"Exiting {symbol}: Price hit stop-loss at ${coin['price']}.")
                elif coin["price"] >= target_price:
                    logger.info(f"Exiting {symbol}: Target profit reached at ${coin['price']}.")
                elif not coin.get("volume_growth", True):
                    logger.info(f"Exiting {symbol}: Volume stagnation detected.")

        # Step 8: Process all coins concurrently
        self._process_coins_with_concurrency(new_coins, process_coin)



    @exception_handler.ExceptionHandler
    def copy_trading(self):
        """
        Entry and exit logic for copy trading strategy.
        Strategy Overview:
            - Use blockchain listener to follow trades from profitable wallets.
            - Validate trades based on filters, thresholds, and risk parameters.
            - Dynamically calculate position size and execute trades.
            - Exit trades in sync with the copied wallet or based on predefined criteria.
        """

        filters = FiltersConfig()
        settings = Settings()
        thresholds = Thresholds()

        # Step 1: Fetch trades from profitable wallets
        trades = helpers.retry_request(blockchain_listener.get_copy_trades)
        if not trades:
            logger.info("No trades detected from profitable wallets.")
            return

        def process_trade(trade):
            symbol = trade["symbol"]
            wallet = trade["wallet_address"]

            # Step 2: Validate the trade
            if not trade_validator.validate_trade(trade):
                logger.debug(f"{symbol}: Invalid trade from wallet {wallet}. Skipping.")
                return

            # Step 3: Check token filters and thresholds
            if not filters.validate_token(trade["token_data"]):
                logger.debug(f"{symbol}: Token failed validation. Skipping.")
                return

            if not (thresholds.MIN_LIQUIDITY <= trade["token_data"]["liquidity"] <= thresholds.MAX_LIQUIDITY):
                logger.debug(f"{symbol}: Liquidity {trade['token_data']['liquidity']} out of range. Skipping.")
                return

            # Step 4: Calculate position size dynamically
            account_balance = self.balance_checker.get_available_balance()
            risk_amount = account_balance * settings.RISK_PER_TRADE  # Risk per trade
            stop_loss_distance = abs(trade["price"] * settings.MAX_LOSS)
            position_size = min(risk_amount / stop_loss_distance, settings.TRADE_SIZE / trade["price"])

            if position_size <= 0:
                logger.warning(f"{symbol}: Insufficient balance or invalid position size. Skipping.")
                return

            # Step 5: Execute the trade
            trade_details = {
                "symbol": symbol,
                "price": trade["price"],
                "quantity": position_size,
                "copied_wallet": wallet,
            }
            try:
                transaction_tracker.execute_trade(trade_details)
                self.watchlists["copy_trading"].add(symbol)
                logger.info(f"Copying trade for {symbol} from wallet {wallet}. Trade details: {trade_details}")
            except Exception as e:
                logger.error(f"Failed to execute copied trade for {symbol}: {e}")
                return

            # Step 6: Set exit conditions
            stop_loss = trade["price"] * (1 + settings.MAX_LOSS)
            target_price = trade["price"] * (1 + settings.GAIN_MIN_TARGET)
            logger.info(f"Set stop-loss for {symbol}: ${stop_loss}, take-profit: ${target_price}.")

            # Step 7: Monitor exit conditions
            exit_signal = (
                trade.get("exit_signal", False)
                or trade["price"] <= stop_loss
                or trade["price"] >= target_price
            )

            if self._validate_exit(symbol, exit_signal):
                if trade["price"] <= stop_loss:
                    logger.warning(f"Exiting {symbol}: Price hit stop-loss at ${trade['price']}.")
                elif trade["price"] >= target_price:
                    logger.info(f"Exiting {symbol}: Target profit reached at ${trade['price']}.")
                elif trade.get("exit_signal", False):
                    logger.info(f"Exiting {symbol}: Copied wallet exited trade.")

        # Step 8: Process all trades concurrently
        self._process_coins_with_concurrency(trades, process_trade)

    @exception_handler.ExceptionHandler
    def trend_following(self):
        """
        Entry and exit logic for trend following strategy.
        Strategy Overview:
            - Analyze all coins in the whitelist for strong trends using multiple indicators.
            - Add coins with strong trends to the watchlist.
            - Re-analyze watchlisted coins for valid trend entries.
            - Execute trades for valid entries with stop-loss and take-profit levels.
        """

        filters = FiltersConfig()
        settings = Settings()
        thresholds = Thresholds()
        indicators = Indicators()

        # Step 1: Get coins from the whitelist
        whitelist_coins = filters.criteria["whitelist"]
        if not whitelist_coins:
            logger.info("No coins in the whitelist for trend following.")
            return

        logger.info(f"Analyzing {len(whitelist_coins)} coins from the whitelist for trends.")

        # Step 2: Analyze whitelist coins for strong trends using RSI, MA, EMA, and ADX
        strong_trend_coins = []
        for coin in whitelist_coins:
            symbol = coin["symbol"]

            # Indicators
            rsi_value = indicators.rsi(coin, period=14)
            ma_signal = indicators.moving_average_signal(coin, short_window=10, long_window=50)
            ema_signal = indicators.ema_crossover_signal(coin, short_period=10, long_period=50)
            adx_value = indicators.adx(coin, period=14)

            # Trend confirmation: RSI, MA, EMA, ADX
            is_rsi_bullish = 40 < rsi_value < 70
            is_ma_bullish = ma_signal == "bullish"
            is_ema_bullish = ema_signal == "bullish"
            is_trend_strong = adx_value > thresholds.MIN_TREND_STRENGTH

            if is_rsi_bullish and is_ma_bullish and is_ema_bullish and is_trend_strong:
                logger.info(f"{symbol}: Strong trend confirmed with RSI={rsi_value}, ADX={adx_value}.")
                strong_trend_coins.append(coin)
            else:
                logger.debug(f"{symbol}: Weak trend. Skipping.")

        if not strong_trend_coins:
            logger.info("No strong trends detected in whitelist coins.")
            return

        # Step 3: Add coins with strong trends to the watchlist
        for coin in strong_trend_coins:
            self.watchlists["trend_following"].add(coin["symbol"])

        logger.info(f"Watchlist updated with {len(strong_trend_coins)} coins.")

        # Step 4: Re-analyze watchlist coins for valid entries using indicators
        def process_coin(coin):
            symbol = coin["symbol"]

            # Confirm entry using indicators
            ma_signal = indicators.moving_average_signal(coin, short_window=10, long_window=50)
            ema_signal = indicators.ema_crossover_signal(coin, short_period=10, long_period=50)
            rsi_value = indicators.rsi(coin, period=14)

            is_bullish_entry = (
                ma_signal == "bullish"
                and ema_signal == "bullish"
                and 40 < rsi_value < 70  # RSI indicates neutral-to-bullish conditions
            )

            if not is_bullish_entry:
                logger.debug(f"{symbol}: Entry conditions not met. Skipping.")
                return

            # Validate token using thresholds
            if not (thresholds.MIN_LIQUIDITY <= coin["liquidity"] <= thresholds.MAX_LIQUIDITY):
                logger.debug(f"{symbol}: Liquidity {coin['liquidity']} out of range. Skipping.")
                return

            # Calculate position size dynamically
            account_balance = self.balance_checker.get_available_balance()
            risk_amount = account_balance * settings.RISK_PER_TRADE
            stop_loss_distance = abs(coin["price"] - indicators.support_level(coin))
            position_size = min(risk_amount / stop_loss_distance, settings.TRADE_SIZE / coin["price"])

            if position_size <= 0:
                logger.warning(f"{symbol}: Invalid position size. Skipping.")
                return

            # Execute the trade
            trade_details = {
                "symbol": symbol,
                "price": coin["price"],
                "quantity": position_size,
            }
            try:
                transaction_tracker.execute_trade(trade_details)
                logger.info(f"Executed trend-following trade for {symbol}. Trade details: {trade_details}")
            except Exception as e:
                logger.error(f"Failed to execute trade for {symbol}: {e}")
                return

            # Set stop-loss and take-profit levels
            stop_loss = indicators.support_level(coin) * (1 - settings.MAX_LOSS)  # Stop-loss below support
            target_price = coin["price"] * (1 + settings.GAIN_MIN_TARGET)  # Take-profit above entry price
            logger.info(f"Set stop-loss for {symbol}: ${stop_loss}, take-profit: ${target_price}.")

            # Monitor exit conditions
            exit_signal = (
                ma_signal != "bullish"
                or ema_signal != "bullish"
                or coin["price"] <= stop_loss
                or coin["price"] >= target_price
            )

            if self._validate_exit(symbol, exit_signal):
                if ma_signal != "bullish" or ema_signal != "bullish":
                    logger.warning(f"Exiting {symbol}: Trend invalidated.")
                elif coin["price"] <= stop_loss:
                    logger.warning(f"Exiting {symbol}: Price hit stop-loss at ${coin['price']}.")
                elif coin["price"] >= target_price:
                    logger.info(f"Exiting {symbol}: Target profit reached at ${coin['price']}.")

        # Step 5: Process all coins in the watchlist concurrently for valid entries
        self._process_coins_with_concurrency(strong_trend_coins, process_coin)

    @exception_handler.ExceptionHandler
    def breakout(self):
        """
        Entry and exit logic for breakout trading strategy.
        Strategy Overview:
            - Analyze coins in the whitelist for breakout opportunities.
            - Validate breakout indicators such as Bollinger Bands, Price Channels, and Volume Analysis.
            - Validate trend strength using ADX and SMA.
            - Validate tokens against filters and thresholds.
            - Add qualified tokens to the watchlist.
            - Re-analyze watchlist for breakout entries and execute trades.
            - Monitor and exit trades based on predefined conditions.
        """

        filters = FiltersConfig()
        settings = Settings()
        thresholds = Thresholds()
        indicators = Indicators()

        # Step 1: Analyze coins in the whitelist
        whitelist_coins = filters.criteria["whitelist"]
        if not whitelist_coins:
            logger.info("No coins in the whitelist for breakout strategy.")
            return

        logger.info(f"Analyzing {len(whitelist_coins)} coins from the whitelist for breakout opportunities.")

        # Step 2: Analyze breakout indicators and trend strength
        breakout_candidates = []
        for coin in whitelist_coins:
            symbol = coin["symbol"]
            prices = coin["prices"]
            volumes = coin["volumes"]

            # Analyze breakout indicators
            upper_band, lower_band = indicators.bollinger_bands(prices)
            high_channel, low_channel = indicators.price_channels(prices)
            avg_volume = indicators.volume_analysis(volumes)
            current_price = prices.iloc[-1]
            current_volume = volumes.iloc[-1]

            is_bollinger_breakout = current_price > upper_band.iloc[-1]
            is_price_channel_breakout = current_price > high_channel.iloc[-1]
            is_volume_spike = current_volume > avg_volume.iloc[-1] * thresholds.VOLUME_SPIKE_THRESHOLD

            if not (is_bollinger_breakout and is_price_channel_breakout and is_volume_spike):
                logger.debug(f"{symbol}: No valid breakout detected. Skipping.")
                continue

            # Validate trend strength
            adx_value = indicators.adx(coin["highs"], coin["lows"], prices).iloc[-1]
            sma_signal = indicators.moving_averages(prices, period=20).iloc[-1] < current_price
            if adx_value <= thresholds.MIN_TREND_STRENGTH or not sma_signal:
                logger.debug(f"{symbol}: Weak trend strength. Skipping.")
                continue

            # Validate token using filters and thresholds
            if not filters.validate_token(coin):
                logger.debug(f"{symbol}: Failed validation. Skipping.")
                continue

            if not (thresholds.MIN_LIQUIDITY <= coin["liquidity"] <= thresholds.MAX_LIQUIDITY):
                logger.debug(f"{symbol}: Liquidity {coin['liquidity']} out of range. Skipping.")
                continue

            # Add to breakout candidates
            breakout_candidates.append(coin)
            self.watchlists["breakout"].add(symbol)
            logger.info(f"Added {symbol} to breakout watchlist.")

        if not breakout_candidates:
            logger.info("No breakout candidates detected in the whitelist.")
            return

        # Step 3: Re-analyze watchlist for breakout entries
        def process_coin(coin):
            symbol = coin["symbol"]
            prices = coin["prices"]

            # Analyze breakout re-entry
            upper_band, _ = indicators.bollinger_bands(prices)
            current_price = prices.iloc[-1]

            is_breakout_valid = current_price > upper_band.iloc[-1]
            if not is_breakout_valid:
                logger.debug(f"{symbol}: Breakout invalidated during re-analysis. Skipping.")
                return

            # Calculate risk/reward and position size
            fib_levels = indicators.fibonacci_retracement(prices)
            target_price = fib_levels[1]  # Example: 38.2% retracement
            stop_loss = upper_band.iloc[-1] * (1 - settings.MAX_LOSS)  # Example: Stop-loss below upper band
            risk_reward_ratio = indicators.risk_reward_analysis(entry=current_price, stop_loss=stop_loss, take_profit=target_price)

            if not risk_reward_ratio or risk_reward_ratio < thresholds.MIN_RISK_REWARD_RATIO:
                logger.debug(f"{symbol}: Unfavorable risk/reward ratio. Skipping.")
                return

            account_balance = self.balance_checker.get_available_balance()
            risk_amount = account_balance * settings.RISK_PER_TRADE
            stop_loss_distance = abs(current_price - stop_loss)
            position_size = min(risk_amount / stop_loss_distance, settings.TRADE_SIZE / current_price)

            if position_size <= 0:
                logger.warning(f"{symbol}: Invalid position size. Skipping.")
                return

            # Execute the trade
            trade_details = {
                "symbol": symbol,
                "price": current_price,
                "quantity": position_size,
            }
            try:
                transaction_tracker.execute_trade(trade_details)
                logger.info(f"Executed breakout trade for {symbol}. Trade details: {trade_details}")
            except Exception as e:
                logger.error(f"Failed to execute breakout trade for {symbol}: {e}")
                return

            # Monitor exit conditions
            logger.info(f"Set stop-loss for {symbol}: ${stop_loss}, take-profit: ${target_price}.")
            exit_signal = (
                current_price <= stop_loss  # Breakout failed
                or current_price >= target_price  # Target profit achieved
            )

            if self._validate_exit(symbol, exit_signal):
                if current_price <= stop_loss:
                    logger.warning(f"Exiting {symbol}: Price hit stop-loss at ${current_price}.")
                elif current_price >= target_price:
                    logger.info(f"Exiting {symbol}: Target profit reached at ${current_price}.")

        # Step 4: Process all coins on the watchlist concurrently
        self._process_coins_with_concurrency(breakout_candidates, process_coin)


    @exception_handler.ExceptionHandler
    def mean_reversion(self):
        """
        Entry and exit logic for mean reversion trading strategy.
        Strategy Overview:
            1. Analyze the whitelist for potential mean reversion candidates.
            2. Use Bollinger Bands, RSI, and Z-Score for candidate validation.
            3. Add validated candidates to the mean reversion watchlist.
            4. Re-analyze the watchlist for entry points using additional checks.
            5. Execute trades with calculated position size and risk management.
            6. Monitor and exit trades based on mean reversion or extreme deviation.
        """

        filters = FiltersConfig()
        settings = Settings()
        thresholds = Thresholds()
        indicators = Indicators()

        # Step 1: Analyze the whitelist for mean reversion candidates
        whitelist_coins = filters.criteria["whitelist"]
        if not whitelist_coins:
            logger.info("No coins in the whitelist for mean reversion strategy.")
            return

        logger.info(f"Analyzing {len(whitelist_coins)} coins from the whitelist for mean reversion opportunities.")

        # Step 2: Analyze indicators and add candidates to the watchlist
        mean_reversion_candidates = []
        for coin in whitelist_coins:
            symbol = coin["symbol"]
            prices = coin["prices"]
            volumes = coin["volumes"]

            # Indicator calculations
            upper_band, lower_band = indicators.bollinger_bands(prices)
            rsi = indicators.relative_strength_index(prices)
            z_score = indicators.z_score(prices)

            current_price = prices.iloc[-1]
            current_rsi = rsi.iloc[-1]
            current_z_score = z_score.iloc[-1]

            # Validate mean reversion conditions
            is_mean_reversion_candidate = (
                current_price < lower_band.iloc[-1] or current_price > upper_band.iloc[-1]
            ) and (
                current_rsi < thresholds.OVERSOLD_RSI or current_rsi > thresholds.OVERBOUGHT_RSI
            ) and (
                abs(current_z_score) > 2
            )

            if is_mean_reversion_candidate:
                # Token validation
                if not filters.validate_token(coin):
                    logger.debug(f"{symbol}: Failed token validation. Skipping.")
                    continue

                if not (thresholds.MIN_LIQUIDITY <= coin["liquidity"] <= thresholds.MAX_LIQUIDITY):
                    logger.debug(f"{symbol}: Liquidity out of range. Skipping.")
                    continue

                # Add to candidates and watchlist
                mean_reversion_candidates.append(coin)
                self.watchlists["mean_reversion"].add(symbol)
                logger.info(f"Added {symbol} to the mean reversion watchlist.")

        if not mean_reversion_candidates:
            logger.info("No mean reversion candidates identified.")
            return

        logger.info(f"Re-evaluating {len(mean_reversion_candidates)} candidates for entry opportunities.")

        # Step 3: Re-evaluate candidates for entry
        def process_coin(coin):
            symbol = coin["symbol"]
            prices = coin["prices"]

            # Additional Bollinger Band and price analysis
            upper_band, lower_band = indicators.bollinger_bands(prices)
            current_price = prices.iloc[-1]
            mean_price = (upper_band.iloc[-1] + lower_band.iloc[-1]) / 2

            # Risk/reward and stop-loss/take-profit levels
            stop_loss = lower_band.iloc[-1] if current_price < mean_price else upper_band.iloc[-1]
            target_price = mean_price
            risk_reward_ratio = indicators.risk_reward_analysis(entry=current_price, stop_loss=stop_loss, take_profit=target_price)

            if not risk_reward_ratio or risk_reward_ratio < thresholds.MIN_RISK_REWARD_RATIO:
                logger.debug(f"{symbol}: Unfavorable risk/reward ratio. Skipping.")
                return

            # Position size calculation
            account_balance = self.balance_checker.get_available_balance()
            risk_amount = account_balance * settings.RISK_PER_TRADE
            stop_loss_distance = abs(current_price - stop_loss)
            position_size = min(risk_amount / stop_loss_distance, settings.TRADE_SIZE / current_price)

            if position_size <= 0:
                logger.warning(f"{symbol}: Invalid position size. Skipping.")
                return

            # Execute the trade
            trade_details = {
                "symbol": symbol,
                "price": current_price,
                "quantity": position_size,
            }
            try:
                transaction_tracker.execute_trade(trade_details)
                logger.info(f"Executed mean reversion trade for {symbol}. Trade details: {trade_details}")
            except Exception as e:
                logger.error(f"Failed to execute mean reversion trade for {symbol}: {e}")
                return

            # Monitor exit conditions
            logger.info(f"Set stop-loss for {symbol}: ${stop_loss}, take-profit: ${target_price}.")
            exit_signal = (
                current_price >= target_price  # Mean reversion complete
                or current_price <= stop_loss  # Extreme deviation continues
            )

            if self._validate_exit(symbol, exit_signal):
                if current_price <= stop_loss:
                    logger.warning(f"Exiting {symbol}: Price hit stop-loss at ${current_price}.")
                elif current_price >= target_price:
                    logger.info(f"Exiting {symbol}: Target profit reached at ${current_price}.")

        # Step 4: Process all coins in the watchlist concurrently
        self._process_coins_with_concurrency(mean_reversion_candidates, process_coin)


    def _process_coins_with_concurrency(self, coins, process_func):
        """
        Process coins concurrently with detailed logging and retries.
        Args:
            coins (list): List of coin data to process.
            process_func (callable): Function to apply to each coin.
        """
        logger.info(f"Starting concurrent processing for {len(coins)} coins.")
        futures = {self.executor.submit(process_func, coin): coin for coin in coins}

        for future in as_completed(futures):
            coin = futures[future]
            try:
                future.result()
                logger.info(f"Successfully processed coin: {coin['symbol']}.")
            except Exception as e:
                logger.error(f"Error processing coin {coin['symbol']}: {e}")
                # Optional: Retry logic
                try:
                    logger.info(f"Retrying coin: {coin['symbol']}.")
                    process_func(coin)
                    logger.info(f"Retry successful for coin: {coin['symbol']}.")
                except Exception as retry_error:
                    logger.error(f"Retry failed for coin {coin['symbol']}: {retry_error}")

        logger.info("Concurrent processing completed.")


    def get_watchlists(self, strategy=None):
        """
        Return the current watchlists. Optionally, return a specific strategy's watchlist.
        Args:
            strategy (str, optional): The strategy name for which the watchlist is requested.
        Returns:
            dict or set: The full watchlists dictionary or a specific strategy's watchlist.
        """
        if strategy:
            if strategy in self.watchlists:
                logger.info(f"Fetching watchlist for strategy: {strategy}.")
                return self.watchlists[strategy]
            else:
                logger.warning(f"Strategy {strategy} does not exist in watchlists.")
                return None
        logger.info("Fetching all watchlists.")
        return self.watchlists


    def clear_watchlists(self):
        """
        Clear all watchlists for every strategy, with detailed logging.
        """
        logger.info("Clearing all watchlists.")
        for strategy, watchlist in self.watchlists.items():
            watchlist.clear()
            logger.info(f"Cleared watchlist for strategy: {strategy}.")
        logger.info("All watchlists have been successfully cleared.")

            
    def combine_into_one_strategy(self, coins):
        """
        Combine all strategies into a single function for sequential execution.
        This method ensures that all strategies are executed in a structured manner,
        with robust error handling, logging, and performance tracking.

        Args:
            coins (list): List of coin data to process across all strategies.
        """
        if not coins:
            logger.warning("No coins provided. Aborting unified strategy execution.")
            return

        logger.info("Initiating unified execution of all strategies.")

        # Map strategies to their corresponding functions
        strategy_functions = [
            self.buying_on_untouched_support,
            self.sniping_new_meme_coins,
            self.copy_trading,
            self.trend_following,
            self.breakout,
            self.mean_reversion,
        ]

        # Initialize performance tracking
        total_strategies = len(strategy_functions)
        successful_strategies = 0
        failed_strategies = 0

        for strategy_func in strategy_functions:
            strategy_name = strategy_func.__name__

            # Measure execution time for each strategy
            logger.info(f"Starting execution of strategy: {strategy_name}.")
            start_time = time.time()

            try:
                # Execute the strategy
                strategy_func(coins)
                successful_strategies += 1
                execution_time = time.time() - start_time
                logger.info(f"Completed execution of {strategy_name} in {execution_time:.2f} seconds.")

            except Exception as e:
                failed_strategies += 1
                logger.error(f"Error during execution of strategy {strategy_name}: {e}")
                execution_time = time.time() - start_time
                logger.warning(f"Execution of {strategy_name} failed after {execution_time:.2f} seconds.")

        # Final summary of execution
        logger.info(
            f"Unified strategy execution completed. "
            f"Total strategies: {total_strategies}, Successful: {successful_strategies}, Failed: {failed_strategies}."
        )

        # Alert for failures
        if failed_strategies > 0:
            logger.warning(
                f"Some strategies encountered errors during execution. "
                f"Check logs for more details on failed strategies."
            )

