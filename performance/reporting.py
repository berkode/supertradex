import os
import pandas as pd
import matplotlib.pyplot as plt
import logging
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Reporting:
    def __init__(self, results):
        """
        Initializes the reporting class with trade results.
        :param results: List of trade dictionaries (trade logs).
        """
        self.results = pd.DataFrame(results)
        self.metrics = {}
        self.timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Load configuration from .env
        self.default_output_path = os.getenv("DEFAULT_OUTPUT_PATH", "reports")
        self.logging_level = os.getenv("LOGGING_LEVEL", "INFO").upper()

        # Configure logging
        logging.basicConfig(
            filename="reporting.log",
            level=getattr(logging, self.logging_level, logging.INFO),
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        logging.info("Reporting initialized.")

    def calculate_metrics(self):
        """
        Calculate performance metrics based on trade results.
        """
        try:
            if self.results.empty:
                raise ValueError("No trade results to analyze.")

            total_profit = self.results['profit'].sum()
            roi = (total_profit / self.results['profit'].abs().sum()) * 100 if self.results['profit'].abs().sum() > 0 else 0
            max_drawdown = self.results['profit'].min()
            win_rate = (self.results['profit'] > 0).mean() * 100
            average_trade = self.results['profit'].mean()

            self.metrics = {
                "total_profit": total_profit,
                "ROI (%)": roi,
                "max_drawdown": max_drawdown,
                "win_rate (%)": win_rate,
                "average_trade": average_trade,
                "total_trades": len(self.results),
            }

            logging.info("Performance metrics calculated: %s", self.metrics)
        except Exception as e:
            logging.error(f"Error calculating metrics: {e}")
            raise

    def save_report(self, filepath=None):
        """
        Save the trade results and metrics to CSV, JSON, and Excel files.
        :param filepath: Directory to save the report. Defaults to self.default_output_path.
        """
        try:
            filepath = filepath or self.default_output_path
            os.makedirs(filepath, exist_ok=True)

            report_path = f"{filepath}/trading_report_{self.timestamp}.csv"
            metrics_path = f"{filepath}/metrics_{self.timestamp}.json"
            excel_path = f"{filepath}/trading_report_{self.timestamp}.xlsx"

            # Save trade results to CSV
            self.results.to_csv(report_path, index=False)
            logging.info(f"Trade results saved to {report_path}")

            # Save trade results to Excel
            self.results.to_excel(excel_path, index=False)
            logging.info(f"Trade results saved to {excel_path}")

            # Save metrics to JSON
            with open(metrics_path, "w") as json_file:
                json.dump(self.metrics, json_file, indent=4)
            logging.info(f"Performance metrics saved to {metrics_path}")
        except Exception as e:
            logging.error(f"Error saving report: {e}")
            raise

    def generate_visualizations(self, filepath=None):
        """
        Generate visualizations for trade performance.
        :param filepath: Directory to save the visualizations. Defaults to self.default_output_path.
        """
        try:
            filepath = filepath or self.default_output_path
            os.makedirs(filepath, exist_ok=True)

            if self.results.empty:
                raise ValueError("No trade results for visualization.")

            # Equity Curve
            self.results['cumulative_profit'] = self.results['profit'].cumsum()
            self.results['timestamp'] = pd.to_datetime(self.results['timestamp'])

            plt.figure(figsize=(10, 6))
            plt.plot(self.results['timestamp'], self.results['cumulative_profit'], label="Equity Curve", linewidth=2)
            plt.xlabel("Time")
            plt.ylabel("Cumulative Profit")
            plt.title("Equity Curve")
            plt.legend()
            plt.grid()
            equity_curve_path = f"{filepath}/equity_curve_{self.timestamp}.png"
            plt.savefig(equity_curve_path)
            logging.info(f"Equity curve saved to {equity_curve_path}")
            plt.close()

            # Profit/Loss Distribution
            plt.figure(figsize=(8, 5))
            self.results['profit'].plot(kind='hist', bins=20, alpha=0.75, label="Profit/Loss Distribution", color="blue")
            plt.xlabel("Profit/Loss")
            plt.ylabel("Frequency")
            plt.title("Trade Profit/Loss Distribution")
            plt.legend()
            plt.grid()
            profit_distribution_path = f"{filepath}/profit_distribution_{self.timestamp}.png"
            plt.savefig(profit_distribution_path)
            logging.info(f"Profit/Loss distribution saved to {profit_distribution_path}")
            plt.close()
        except Exception as e:
            logging.error(f"Error generating visualizations: {e}")
            raise

    def generate_full_report(self, filepath=None):
        """
        Generate a full report including metrics, trade logs, and visualizations.
        :param filepath: Directory to save the full report. Defaults to self.default_output_path.
        """
        try:
            filepath = filepath or self.default_output_path
            os.makedirs(filepath, exist_ok=True)

            self.calculate_metrics()
            self.save_report(filepath)
            self.generate_visualizations(filepath)
            logging.info("Full report generated successfully.")
        except Exception as e:
            logging.error(f"Error generating full report: {e}")
            raise
