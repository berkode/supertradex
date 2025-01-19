import logging
import json
from datetime import datetime
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()


class DrawdownTracker:
    def __init__(self, initial_equity, max_drawdown_percentage, alert_callback=None, auto_save_path=None):
        """
        Initializes the drawdown tracker.
        :param initial_equity: Starting account equity.
        :param max_drawdown_percentage: Maximum allowed drawdown as a percentage.
        :param alert_callback: Optional callback function for sending alerts.
        :param auto_save_path: Optional path for periodic auto-saving of drawdown history.
        """
        self.initial_equity = initial_equity
        self.current_equity = initial_equity
        self.max_drawdown_percentage = max_drawdown_percentage
        self.alert_callback = alert_callback
        self.drawdowns = []
        self.is_trading_active = True
        self.auto_save_path = auto_save_path
        self.timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Configure logging
        log_file = os.getenv("LOG_FILE", "drawdown_tracker.log")
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        logging.info("DrawdownTracker initialized with equity: %s", initial_equity)

    def calculate_drawdown(self):
        """
        Calculate the current drawdown percentage.
        """
        try:
            peak_equity = max(self.initial_equity, self.current_equity)
            drawdown = (peak_equity - self.current_equity) / peak_equity * 100
            return drawdown
        except Exception as e:
            logging.error(f"Error calculating drawdown: {e}")
            raise

    def calculate_recovery(self):
        """
        Calculate the recovery percentage after a drawdown.
        """
        try:
            peak_equity = max(self.initial_equity, self.current_equity)
            recovery = (self.current_equity - self.initial_equity) / (peak_equity - self.initial_equity) * 100
            recovery = max(0, min(recovery, 100))  # Ensure valid range [0, 100]
            return recovery
        except Exception as e:
            logging.error(f"Error calculating recovery: {e}")
            raise

    def update_equity(self, trade_profit):
        """
        Update the current equity after a trade and check drawdown.
        :param trade_profit: Profit or loss from the trade.
        """
        try:
            if not self.is_trading_active:
                logging.warning("Trading is currently disabled due to drawdown limits.")
                return

            # Update equity
            self.current_equity += trade_profit
            current_drawdown = self.calculate_drawdown()

            # Log drawdown
            drawdown_entry = {
                "current_equity": self.current_equity,
                "drawdown_percentage": current_drawdown,
                "recovery_percentage": self.calculate_recovery(),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.drawdowns.append(drawdown_entry)
            logging.info("Equity updated: %s, Drawdown: %s%%", self.current_equity, current_drawdown)

            # Check drawdown limits
            if current_drawdown >= self.max_drawdown_percentage:
                self.trigger_drawdown_alert(current_drawdown)

            # Auto-save drawdown history
            if self.auto_save_path:
                self.save_drawdowns(self.auto_save_path)

        except Exception as e:
            logging.error(f"Error updating equity: {e}")
            raise

    def trigger_drawdown_alert(self, current_drawdown):
        """
        Trigger an alert and disable trading when drawdown limits are breached.
        :param current_drawdown: Current drawdown percentage.
        """
        try:
            logging.warning("Maximum drawdown limit breached! Trading disabled.")
            self.is_trading_active = False

            alert_message = {
                "message": "Maximum drawdown limit breached.",
                "current_equity": self.current_equity,
                "drawdown_percentage": current_drawdown,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            # Log alert
            logging.info("Drawdown alert triggered: %s", alert_message)

            # Send alert via callback
            if self.alert_callback:
                self.alert_callback(alert_message)
        except Exception as e:
            logging.error(f"Error triggering drawdown alert: {e}")
            raise

    def reset_drawdown(self):
        """
        Reset the drawdown tracker and re-enable trading.
        """
        try:
            logging.info("Resetting drawdown tracker.")
            self.current_equity = self.initial_equity
            self.is_trading_active = True
            self.drawdowns = []
            logging.info("Drawdown tracker reset successfully.")
        except Exception as e:
            logging.error(f"Error resetting drawdown tracker: {e}")
            raise

    def save_drawdowns(self, filepath):
        """
        Save drawdown history to a JSON file.
        :param filepath: Path to save the drawdown history.
        """
        try:
            os.makedirs(filepath, exist_ok=True)
            drawdown_path = f"{filepath}/drawdowns_{self.timestamp}.json"
            with open(drawdown_path, "w") as json_file:
                json.dump(self.drawdowns, json_file, indent=4)
            logging.info(f"Drawdowns saved to {drawdown_path}")
        except Exception as e:
            logging.error(f"Error saving drawdowns: {e}")
            raise

    def get_drawdown_summary(self):
        """
        Get a summary of the drawdown history.
        :return: Summary dictionary containing peak drawdown and recovery details.
        """
        try:
            if not self.drawdowns:
                return {
                    "message": "No drawdown history available.",
                    "peak_drawdown_percentage": 0,
                    "current_equity": self.current_equity,
                }

            peak_drawdown = max(entry["drawdown_percentage"] for entry in self.drawdowns)
            summary = {
                "peak_drawdown_percentage": peak_drawdown,
                "current_equity": self.current_equity,
                "recovery_percentage": self.calculate_recovery(),
                "trading_status": "Active" if self.is_trading_active else "Disabled",
            }
            logging.info("Drawdown summary: %s", summary)
            return summary
        except Exception as e:
            logging.error(f"Error generating drawdown summary: {e}")
            raise
