import os
import logging
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import datetime
from sklearn.cluster import KMeans

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("analytics.log"),
        logging.StreamHandler() if os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true" else None
    ]
)


class Analytics:
    def __init__(self):
        self.suspicious_threshold = float(os.getenv("SUSPICIOUS_THRESHOLD", 1000))  # Suspicious transfer threshold
        self.whale_threshold = float(os.getenv("WHALE_THRESHOLD", 100_000))  # Whale activity threshold
        self.cluster_count = int(os.getenv("CLUSTER_COUNT", 5))  # Number of clusters for KMeans
        self.min_liquidity = float(os.getenv("MIN_LIQUIDITY", 1000))  # Minimum liquidity for analysis

    @staticmethod
    def calculate_price_trend(prices: pd.Series) -> str:
        """
        Analyze price trends.

        Args:
            prices (pd.Series): Series of token prices.

        Returns:
            str: Trend description ('uptrend', 'downtrend', 'sideways').
        """
        logging.info("Calculating price trend...")
        diff = prices.diff()
        trend = "uptrend" if diff.mean() > 0 else "downtrend" if diff.mean() < 0 else "sideways"
        logging.info(f"Price trend detected: {trend}")
        return trend

    def analyze_liquidity(self, liquidity_data: pd.DataFrame) -> dict:
        """
        Analyze liquidity trends.

        Args:
            liquidity_data (pd.DataFrame): Liquidity data with columns ['timestamp', 'liquidity'].

        Returns:
            dict: Liquidity analysis summary.
        """
        logging.info("Analyzing liquidity...")
        liquidity_data['timestamp'] = pd.to_datetime(liquidity_data['timestamp'])
        liquidity_data.set_index('timestamp', inplace=True)
        avg_liquidity = liquidity_data['liquidity'].mean()
        liquidity_trend = self.calculate_price_trend(liquidity_data['liquidity'])

        summary = {"average_liquidity": avg_liquidity, "liquidity_trend": liquidity_trend}
        logging.info(f"Liquidity analysis complete: {summary}")
        return summary

    def detect_suspicious_wallets(self, transfer_data: pd.DataFrame) -> list:
        """
        Detect suspicious wallets based on transaction amounts.

        Args:
            transfer_data (pd.DataFrame): Transfer data with columns ['wallet', 'amount'].

        Returns:
            list: List of suspicious wallets.
        """
        logging.info("Detecting suspicious wallets...")
        suspicious_wallets = transfer_data[transfer_data['amount'] > self.suspicious_threshold]['wallet'].unique().tolist()
        logging.info(f"Suspicious wallets: {suspicious_wallets}")
        return suspicious_wallets

    def monitor_whale_movements(self, transfer_data: pd.DataFrame) -> pd.DataFrame:
        """
        Monitor whale movements based on large transaction amounts.

        Args:
            transfer_data (pd.DataFrame): Transfer data with columns ['wallet', 'amount'].

        Returns:
            pd.DataFrame: DataFrame of whale movements.
        """
        logging.info("Monitoring whale movements...")
        whales = transfer_data[transfer_data['amount'] > self.whale_threshold]
        logging.info(f"Whale movements detected: {whales}")
        return whales

    def track_developer_activity(self, dev_wallets: list, activity_data: pd.DataFrame) -> dict:
        """
        Track activity of developer wallets.

        Args:
            dev_wallets (list): List of developer wallet addresses.
            activity_data (pd.DataFrame): Activity data with columns ['wallet', 'activity_type', 'timestamp'].

        Returns:
            dict: Summary of developer wallet activities.
        """
        logging.info("Tracking developer activity...")
        dev_activity = activity_data[activity_data['wallet'].isin(dev_wallets)]
        activity_summary = dev_activity.groupby('activity_type').size().to_dict()
        logging.info(f"Developer activity summary: {activity_summary}")
        return activity_summary

    def cluster_transactions(self, transaction_data: pd.DataFrame) -> dict:
        """
        Apply clustering to transactions to identify patterns.

        Args:
            transaction_data (pd.DataFrame): Transaction data with numerical features.

        Returns:
            dict: Cluster assignment summary.
        """
        logging.info("Clustering transactions...")
        features = transaction_data.select_dtypes(include=np.number)
        if features.empty:
            logging.warning("No numerical features for clustering.")
            return {}

        kmeans = KMeans(n_clusters=self.cluster_count, random_state=42)
        transaction_data['cluster'] = kmeans.fit_predict(features)
        cluster_summary = transaction_data.groupby('cluster').size().to_dict()
        logging.info(f"Transaction clusters: {cluster_summary}")
        return cluster_summary


