import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime


class Metrics:
    def __init__(self, results, base_currency="dSOL"):
        """
        Initializes the metrics class with trade results.
        :param results: List of trade dictionaries (trade logs).
        :param base_currency: The trading system's base currency.
        """
        self.results = pd.DataFrame(results)
        self.metrics = {}
        self.base_currency = base_currency
        self.timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Configure logging
        logging.basicConfig(
            filename="metrics.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        logging.info(f"Metrics initialized for base currency: {base_currency}")

    def calculate_total_made(self):
        """
        Calculate the total profit made in the base currency.
        """
        try:
            total_made = self.results['profit'].sum()
            self.metrics[f"Total Made ({self.base_currency})"] = total_made
            logging.info("Total Made calculated: %s %s", total_made, self.base_currency)
        except Exception as e:
            logging.error(f"Error calculating Total Made: {e}")
            raise

    def calculate_total_roi(self):
        """
        Calculate the total ROI (Return on Investment).
        """
        try:
            total_profit = self.results['profit'].sum()
            invested_capital = self.results['profit'].abs().sum()
            roi = (total_profit / invested_capital) * 100 if invested_capital > 0 else 0
            self.metrics["Total ROI (%)"] = roi
            logging.info("Total ROI calculated: %s", roi)
        except Exception as e:
            logging.error(f"Error calculating Total ROI: {e}")
            raise

    def calculate_tokens_per_day(self):
        """
        Calculate total tokens bought and sold per day.
        """
        try:
            self.results['date'] = pd.to_datetime(self.results['timestamp']).dt.date
            daily_summary = self.results.groupby('date').agg(
                tokens_bought=('quantity', lambda x: x[self.results['action'] == 'buy'].sum()),
                tokens_sold=('quantity', lambda x: x[self.results['action'] == 'sell'].sum()),
            ).reset_index()

            self.metrics["Daily Token Summary"] = daily_summary.to_dict(orient="records")
            logging.info("Tokens per day calculated: %s", self.metrics["Daily Token Summary"])
        except Exception as e:
            logging.error(f"Error calculating tokens per day: {e}")
            raise

    def calculate_max_gain_loss(self):
        """
        Calculate the maximum gain and maximum loss during the period.
        """
        try:
            max_gain = self.results['profit'].max()
            max_loss = self.results['profit'].min()
            gain_loss_ratio = (max_gain / abs(max_loss)) if max_loss < 0 else np.inf
            self.metrics[f"Max Gain ({self.base_currency})"] = max_gain
            self.metrics[f"Max Loss ({self.base_currency})"] = max_loss
            self.metrics["Max Gain/Loss Ratio"] = gain_loss_ratio
            logging.info(
                "Max Gain: %s %s, Max Loss: %s %s, Max Gain/Loss Ratio: %s",
                max_gain, self.base_currency, max_loss, self.base_currency, gain_loss_ratio
            )
        except Exception as e:
            logging.error(f"Error calculating Max Gain/Loss: {e}")
            raise

    def calculate_sharpe_ratio(self, risk_free_rate=0):
        """
        Calculate Sharpe Ratio.
        :param risk_free_rate: Risk-free rate for the calculation.
        """
        try:
            returns = self.results['profit']
            avg_return = returns.mean()
            return_std = returns.std()
            sharpe_ratio = (avg_return - risk_free_rate) / return_std if return_std > 0 else 0
            self.metrics["Sharpe Ratio"] = sharpe_ratio
            logging.info("Sharpe Ratio calculated: %s", sharpe_ratio)
        except Exception as e:
            logging.error(f"Error calculating Sharpe Ratio: {e}")
            raise

    def calculate_all_metrics(self):
        """
        Calculate all metrics: Total Made in dSOL, Total ROI, Tokens Per Day, Max Gain/Loss, and Sharpe Ratio.
        """
        try:
            logging.info("Calculating all metrics...")
            self.calculate_total_made()
            self.calculate_total_roi()
            self.calculate_tokens_per_day()
            self.calculate_max_gain_loss()
            self.calculate_sharpe_ratio()
            logging.info("All metrics calculated successfully: %s", self.metrics)
            return self.metrics
        except Exception as e:
            logging.error(f"Error calculating all metrics: {e}")
            raise

    def save_metrics(self, filepath):
        """
        Save metrics to a JSON file.
        :param filepath: File path to save the metrics.
        """
        try:
            if not self.metrics:
                raise ValueError("No metrics to save. Calculate metrics first.")

            metrics_path = f"{filepath}/metrics_{self.timestamp}.json"
            with open(metrics_path, "w") as json_file:
                json.dump(self.metrics, json_file, indent=4)
            logging.info(f"Metrics saved to {metrics_path}")
        except Exception as e:
            logging.error(f"Error saving metrics: {e}")
            raise
