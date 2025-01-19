import logging
from typing import List, Dict

from config import Settings, Thresholds
from utils import logger as logger_utils
from wallet import balance_checker, trade_validator
from execution import transaction_tracker

logger = logger_utils.get_logger("PositionManagement")


class PositionManagement:
    def __init__(self):
        self.settings = Settings()
        self.thresholds = Thresholds()
        self.balance_checker = balance_checker.BalanceChecker()
        self.trade_validator = trade_validator.TradeValidator()

    def calculate_position_size(self, account_balance: float, risk_per_trade: float, entry_price: float, stop_loss: float) -> float:
        """
        Calculate position size dynamically based on risk tolerance and trade parameters.
        """
        try:
            risk_amount = account_balance * risk_per_trade
            stop_loss_distance = abs(entry_price - stop_loss)
            if stop_loss_distance == 0:
                raise ValueError("Stop-loss distance cannot be zero.")
            position_size = risk_amount / stop_loss_distance
            logger.info(f"Calculated position size: {position_size} (Entry: {entry_price}, Stop Loss: {stop_loss}).")
            return position_size
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0

    def scale_in(self, symbol: str, current_price: float, target_price: float, max_position_size: float):
        """
        Dynamically scale into a position based on price proximity to the target.
        """
        try:
            scale_factor = (target_price - current_price) / target_price
            additional_size = max_position_size * max(scale_factor, 0)
            if additional_size <= 0:
                logger.info(f"Scale-in size for {symbol} is zero or negative. Skipping scale-in.")
                return

            trade_details = {"symbol": symbol, "price": current_price, "quantity": additional_size}
            transaction_tracker.execute_trade(trade_details)
            logger.info(f"Successfully scaled into {symbol}. Trade details: {trade_details}.")
        except Exception as e:
            logger.error(f"Failed to execute scale-in for {symbol}: {e}")

    def scale_out(self, symbol: str, current_price: float, position_size: float, scale_out_ratio: float):
        """
        Dynamically scale out of a position by reducing position size proportionally.
        """
        try:
            size_to_scale_out = position_size * scale_out_ratio
            if size_to_scale_out <= 0:
                logger.info(f"Scale-out size for {symbol} is zero or negative. Skipping scale-out.")
                return

            trade_details = {"symbol": symbol, "price": current_price, "quantity": -size_to_scale_out}
            transaction_tracker.execute_trade(trade_details)
            logger.info(f"Successfully scaled out of {symbol}. Trade details: {trade_details}.")
        except Exception as e:
            logger.error(f"Failed to execute scale-out for {symbol}: {e}")

    def take_partial_profits(self, symbol: str, current_price: float, position_size: float, profit_target: float):
        """
        Take partial profits if the current price meets or exceeds the profit target.
        """
        try:
            if current_price < profit_target:
                logger.debug(f"{symbol}: Current price {current_price} is below profit target {profit_target}. No partial profits taken.")
                return

            partial_size = position_size * self.thresholds.PARTIAL_PROFIT_RATIO
            trade_details = {"symbol": symbol, "price": current_price, "quantity": -partial_size}
            transaction_tracker.execute_trade(trade_details)
            logger.info(f"Partial profits taken for {symbol}. Trade details: {trade_details}.")
        except Exception as e:
            logger.error(f"Failed to execute partial profits for {symbol}: {e}")

    def rebalance_positions(self, positions: List[Dict], account_balance: float):
        """
        Rebalance positions dynamically to maintain risk and portfolio alignment.
        """
        try:
            for position in positions:
                symbol = position["symbol"]
                current_size = position["size"]
                entry_price = position["entry_price"]
                stop_loss = position["stop_loss"]
                current_price = position["current_price"]

                target_size = self.calculate_position_size(account_balance, self.settings.RISK_PER_TRADE, entry_price, stop_loss)

                if current_size < target_size:
                    logger.info(f"{symbol}: Current size {current_size} below target {target_size}. Scaling in.")
                    self.scale_in(symbol, current_price, entry_price, target_size)
                elif current_size > target_size:
                    logger.info(f"{symbol}: Current size {current_size} exceeds target {target_size}. Scaling out.")
                    self.scale_out(symbol, current_price, current_size, 0.5)
        except Exception as e:
            logger.error(f"Error during position rebalancing: {e}")

    def manage_positions(self, positions: List[Dict], account_balance: float):
        """
        Manage positions comprehensively, including taking partial profits and rebalancing.
        """
        try:
            for position in positions:
                symbol = position["symbol"]
                current_price = position["current_price"]
                position_size = position["size"]
                profit_target = position.get("profit_target", current_price * (1 + self.thresholds.GAIN_TARGET_RATIO))

                # Take partial profits
                self.take_partial_profits(symbol, current_price, position_size, profit_target)

            # Rebalance positions after taking partial profits
            self.rebalance_positions(positions, account_balance)
            logger.info("Position management completed successfully.")
        except Exception as e:
            logger.error(f"Error during position management: {e}")

