import pandas as pd
import time
import requests
import logging
import os
from dotenv import load_dotenv
from config.settings import Settings

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class Backtesting:
    def __init__(self, strategy):
        """
        Initializes the backtesting class.
        :param strategy: Strategy function or class.
        """
        # Load configuration from .env
        self.api_base_url = os.getenv("DEXSCREENER_API_BASE_URL")
        self.testnet = os.getenv("TESTNET") == "true"
        self.capital = float(os.getenv("STARTING_CAPITAL", 10000))
        self.logging_level = os.getenv("LOGGING_LEVEL", "INFO").upper()

        # Configure logging
        logging.basicConfig(
            filename="backtesting.log",
            level=getattr(logging, self.logging_level, logging.INFO),
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        logging.info("Backtesting initialized with capital: %s", self.capital)

        self.strategy = strategy
        self.results = []
        self.data = None

        self.settings = Settings()
        self.trade_size = self.settings.TRADE_SIZE
        self.slippage_tolerance = self.settings.SLIPPAGE_TOLERANCE
        self.risk_per_trade = self.settings.RISK_PER_TRADE

    def load_data(self, source=None, live=False, symbol=None):
        """
        Load historical data from CSV or fetch live data from DexScreener.
        :param source: Path to CSV or None for API fetching.
        :param live: Boolean, fetch live data if True.
        :param symbol: Trading pair symbol for live data (e.g., "SOL/USDT").
        """
        try:
            if live and symbol:
                logging.info(f"Fetching live data for {symbol}...")
                api_url = f"{self.api_base_url}/{symbol}"
                response = requests.get(api_url)
                response.raise_for_status()
                # Extract relevant data from DexScreener API response
                market_data = response.json()
                self.data = pd.DataFrame(market_data.get("pairs", []))
                logging.info("Live data fetched successfully.")
            elif source:
                logging.info(f"Loading historical data from {source}...")
                self.data = pd.read_csv(source)
                logging.info("Historical data loaded successfully.")
            else:
                raise ValueError("Invalid data source or symbol.")
        except Exception as e:
            logging.error(f"Failed to load data: {e}")
            raise

    def simulate_trade(self, action, price, quantity):
        """
        Simulate a trade (buy/sell).
        :param action: 'buy' or 'sell'.
        :param price: Trade price.
        :param quantity: Quantity of asset.
        """
        try:
            trade_cost = price * quantity
            if action == 'buy' and self.capital >= trade_cost:
                self.capital -= trade_cost
                profit = 0  # No immediate profit for buy
            elif action == 'sell':
                self.capital += trade_cost
                profit = trade_cost - (price * quantity)
            else:
                raise ValueError("Invalid trade action or insufficient capital.")
            self.record_trade(action, price, quantity, profit)
        except Exception as e:
            logging.error(f"Trade simulation error: {e}")
            raise

    def record_trade(self, action, price, quantity, profit):
        """
        Record trade details in the results log.
        :param action: Trade action ('buy' or 'sell').
        :param price: Trade price.
        :param quantity: Quantity traded.
        :param profit: Profit/loss from the trade.
        """
        trade_log = {
            "action": action,
            "price": price,
            "quantity": quantity,
            "profit": profit,
            "timestamp": time.time(),
        }
        self.results.append(trade_log)
        logging.info(f"Recorded trade: {trade_log}")

    def evaluate_metrics(self):
        """
        Evaluate performance metrics based on trade results.
        """
        try:
            df = pd.DataFrame(self.results)
            total_profit = df['profit'].sum()
            roi = (total_profit / self.capital) * 100
            max_drawdown = df['profit'].min()
            metrics = {"total_profit": total_profit, "ROI": roi, "max_drawdown": max_drawdown}
            logging.info(f"Performance metrics: {metrics}")
            return metrics
        except Exception as e:
            logging.error(f"Error evaluating metrics: {e}")
            raise

    def run_backtest(self):
        """
        Run backtesting on historical data.
        """
        logging.info("Starting backtesting...")
        try:
            if self.data is None:
                raise ValueError("No data loaded. Call load_data() first.")
                
            for _, row in self.data.iterrows():
                signal = self.strategy(row)
                if signal == 'buy':
                    self.simulate_trade('buy', row['price'], row['volume'])
                elif signal == 'sell':
                    self.simulate_trade('sell', row['price'], row['volume'])
            logging.info("Backtesting completed successfully.")
        except Exception as e:
            logging.error(f"Backtesting error: {e}")
            raise

    def run_forward_test(self, symbol):
        """
        Run forward testing on live data using the testnet.
        """
        logging.info("Starting forward test...")
        while True:
            try:
                self.load_data(live=True, symbol=symbol)
                if self.data is None or len(self.data) == 0:
                    logging.warning("No data available, retrying...")
                    time.sleep(1)
                    continue
                    
                signal = self.strategy(self.data.iloc[-1])
                if signal == 'buy':
                    self.simulate_trade('buy', self.data.iloc[-1]['price'], self.data.iloc[-1]['volume'])
                elif signal == 'sell':
                    self.simulate_trade('sell', self.data.iloc[-1]['price'], self.data.iloc[-1]['volume'])
                time.sleep(1)  # Delay to simulate real-time conditions
            except Exception as e:
                logging.error(f"Forward test error: {e}")
                break

    def save_results(self, filepath):
        """
        Save results to a CSV file.
        :param filepath: File path to save the results.
        """
        try:
            df = pd.DataFrame(self.results)
            df.to_csv(filepath, index=False)
            logging.info(f"Results saved to {filepath}")
        except Exception as e:
            logging.error(f"Error saving results: {e}")
            raise
