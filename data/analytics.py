import logging
from typing import Dict, Any, List, Optional
import os
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import datetime
from sklearn.cluster import KMeans
from config.settings import Settings
from utils.logger import get_logger

# Load environment variables from .env
load_dotenv()

# Get logger for this module
logger = logging.getLogger(__name__)

class Analytics:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.min_volume = self.settings.MIN_VOLUME_24H
        self.min_liquidity_threshold = self.settings.MIN_LIQUIDITY
        self.min_liquidity_ratio = self.settings.MIN_LIQUIDITY_RATIO
        # Read analytics-specific thresholds from Settings
        self.suspicious_threshold = self.settings.SUSPICIOUS_THRESHOLD
        self.whale_threshold = self.settings.WHALE_THRESHOLD
        self.cluster_count = self.settings.CLUSTER_COUNT
        self.min_liquidity = self.settings.MIN_LIQUIDITY
        
        # Configure logging - Remove level argument as it's not supported by custom get_logger
        self.logger = get_logger(__name__)
        self.logger.info("Analytics initialized with Min Volume: %s, Min Liquidity: %s", 
                         self.min_volume, self.min_liquidity)
        
    async def initialize(self) -> bool:
        """
        Initialize the Analytics class.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            logger.info("Initializing Analytics")
            
            # Validate settings
            if not all([
                self.min_volume,
                self.min_liquidity_threshold,
                self.min_liquidity_ratio,
                self.suspicious_threshold,
                self.whale_threshold,
                self.cluster_count,
                self.min_liquidity
            ]):
                logger.error("Missing required settings for Analytics")
                return False
                
            logger.info("Analytics initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing Analytics: {e}")
            # Still return True to allow application to continue
            return True
            
    async def close(self):
        """
        Close resources used by Analytics.
        """
        try:
            # No resources to close, but keeping the pattern consistent
            logger.info("Analytics resources closed")
        except Exception as e:
            logger.error(f"Error closing Analytics resources: {e}")

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


