import os
import logging
from dotenv import load_dotenv
from config import Settings
from execution import transaction_tracker

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RiskManagement")


class RiskManagement:
    def __init__(self):
        self.settings = Settings()

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
                transaction_tracker.execute_trade(trade_details)
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
                transaction_tracker.execute_trade(trade_details)
                continue

            if current_price >= take_profit:
                logger.info(f"{symbol} ({strategy}): Current price {current_price} reached take-profit {take_profit}. Closing position.")
                trade_details = {"symbol": symbol, "quantity": -position_size, "price": current_price}
                transaction_tracker.execute_trade(trade_details)
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

